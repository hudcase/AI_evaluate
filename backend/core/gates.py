"""core/gates.py — 九项门禁

门禁回答的是一个和分数无关的问题：**这次课的数据够不够格被计分**。
它把"测不准"与"教得差"分开——门禁不过，分项宁可不输出，也不能把采集故障算成教师失职。

判定输入分三类，缺哪类就明确说"未测"，绝不用 0 或默认值顶替：
  1. 结构证据：通道数、时长、抽帧数、课件页数、课程目标——本地就能算，全部真算
  2. 模型证据：SNR、CER、DER、后排误差与检测率——由 ASR／音频质量／VLM 产出，落在 task.result_json.model_metrics
  3. 无 → status 记 warn，value 写"未测"，detail 写明缺哪一路证据

阈值只来自三类来源（法规标准、实证分布分位数、效标切点）。下列数值是**示意阈值**，
接真实课例后必须按本校分布重标定——写在这里是为了让判定可复现，不是宣称它们已标定。
"""

GATE_DEFS = [
    ('capture_integrity', '采集完整性', '作废或降级，必要时重采'),
    ('speech_intelligibility', '语音可懂度', '标为低证据并人工抽听'),
    ('transcript_quality', '转写质量', '不得自动计分'),
    ('role_separation', '角色分离', '互动类指标暂停输出'),
    ('time_alignment', '时间对齐', '重做对齐后计算'),
    ('group_robustness', '分组稳健性', '触发复训或模型调整'),
    ('detection_sensitivity', '视频检测敏感性', '按区域加权校正或降级'),
    ('frame_usability', '画面可用性', '相应分项不予输出'),
    ('metadata_completeness', '元数据完整性', '目标匹配域记为空值'),
]

EXPECTED_CHANNELS = 4          # 2 路视频 + 领夹 + 环境声


def _g(key, status, value, detail):
    name, action = key, ''
    for k, n, a in GATE_DEFS:
        if k == key:
            name, action = n, a
            break
    return {'key': key, 'name': name, 'status': status, 'value': value,
            'detail': detail, 'action': action}


def _pct(v):
    return '%.1f%%' % (float(v) * 100)


def compute(session, media, metrics=None, derived=None):
    """返回 (overall, gates[])。overall ∈ {pass, warn, reject}"""
    metrics = metrics or {}
    derived = derived or {}

    videos = [m for m in media if m['type'] == 'video']
    audios = [m for m in media if m['type'] == 'audio']
    channels = len(videos) + len(audios)
    gates = []

    # 1 采集完整性 ------------------------------------------------------
    durs = [m['duration_s'] for m in media if m.get('duration_s')]
    dev = (max(durs) - min(durs)) if len(durs) >= 2 else 0.0
    if channels == 0:
        gates.append(_g('capture_integrity', 'reject', '0/%d 通道' % EXPECTED_CHANNELS,
                        '未登记任何音视频资产，无法评价'))
    elif channels < EXPECTED_CHANNELS - 2 or dev > 30:
        gates.append(_g('capture_integrity', 'reject', '%d/%d 通道' % (channels, EXPECTED_CHANNELS),
                        '缺路或时长偏差 %.0fs，超出可对齐范围' % dev))
    elif channels < EXPECTED_CHANNELS or dev > 2:
        gates.append(_g('capture_integrity', 'warn', '%d/%d 通道' % (channels, EXPECTED_CHANNELS),
                        '音视频时长偏差 %.1fs，需在抽帧前校正' % dev))
    else:
        gates.append(_g('capture_integrity', 'pass', '%d/%d 通道' % (channels, EXPECTED_CHANNELS),
                        '无丢帧，音视频时长偏差 %.1fs' % dev))

    # 2 语音可懂度 ------------------------------------------------------
    if 'snr_db' in metrics:
        db = float(metrics['snr_db'])
        low = metrics.get('low_snr_ratio')
        st = 'pass' if db >= 15 else ('warn' if db >= 10 else 'reject')
        gates.append(_g('speech_intelligibility', st, 'SNR %.1f dB' % db,
                        '低信噪比片段占 %s' % (_pct(low) if low is not None else '未统计')))
    else:
        gates.append(_g('speech_intelligibility', 'warn', '未测',
                        '需音频质量分析结果（SNR／低信噪比占比）；按缺测处理，不补零'))

    # 3 转写质量 --------------------------------------------------------
    if 'cer' in metrics:
        cer = float(metrics['cer'])
        hi = metrics.get('high_conf_ratio')
        st = 'pass' if cer <= 0.15 else ('warn' if cer <= 0.25 else 'reject')
        gates.append(_g('transcript_quality', st, 'CER %s' % _pct(cer),
                        '高置信字符 %s' % (_pct(hi) if hi is not None else '未统计')))
    else:
        gates.append(_g('transcript_quality', 'warn', '未测',
                        '需 ASR 转写结果；转写未完成时音频分项不得计分'))

    # 4 角色分离 --------------------------------------------------------
    if 'der' in metrics:
        der = float(metrics['der'])
        st = 'pass' if der <= 0.10 else ('warn' if der <= 0.20 else 'reject')
        gates.append(_g('role_separation', st, '混淆 %s' % _pct(der),
                        '重叠语音漏检 %s 段' % metrics.get('overlap_miss', '—')))
    else:
        gates.append(_g('role_separation', 'warn', '未测',
                        '需说话人分离结果；未分离时互动类指标暂停输出'))

    # 5 时间对齐 --------------------------------------------------------
    expect = float(session.get('duration_min') or 0) * 60
    if durs and expect:
        worst = max(abs(d - expect) for d in durs)
        st = 'pass' if worst <= 2 else ('warn' if worst <= 30 else 'reject')
        gates.append(_g('time_alignment', st, '偏差 %.2fs' % worst,
                        '以 t=0 为课程起点；场次登记时长 %.0f 分钟' % (expect / 60)))
    else:
        gates.append(_g('time_alignment', 'warn', '未测', '缺媒资时长或场次时长，无法对齐'))

    # 6 分组稳健性 ------------------------------------------------------
    if 'back_row_error' in metrics:
        e = float(metrics['back_row_error'])
        st = 'pass' if e <= 0.05 else ('warn' if e <= 0.15 else 'reject')
        gates.append(_g('group_robustness', st, '后排误差 +%s' % _pct(e), '按区域加权校正后计入'))
    else:
        gates.append(_g('group_robustness', 'warn', '未测',
                        '需分区检测统计；未做分区标定时该结论不可得'))

    # 7 视频检测敏感性 --------------------------------------------------
    if 'back_row_detect' in metrics:
        r = float(metrics['back_row_detect'])
        st = 'pass' if r >= 0.70 else ('warn' if r >= 0.55 else 'reject')
        detail = '低于 70% 建议线，VB1 需按区域加权' if st != 'pass' else '达到建议线'
        gates.append(_g('detection_sensitivity', st, '后排检测率 %.0f%%' % (r * 100), detail))
    else:
        gates.append(_g('detection_sensitivity', 'warn', '未测',
                        '需 VLM 分区检测结果；未检测时 VB1／VB2 不予输出'))

    # 8 画面可用性 ------------------------------------------------------
    frames = int(derived.get('frames') or 0)
    offscreen = metrics.get('teacher_offscreen_s')
    if frames <= 0:
        gates.append(_g('frame_usability', 'warn', '抽帧 0 张',
                        '未抽帧，视频分项不可算'))
    elif offscreen is not None and float(offscreen) > 60:
        gates.append(_g('frame_usability', 'warn', '教师出画 %s' % _mmss(offscreen),
                        '出画累计超过 1 分钟，相关分项按可评价时长折算'))
    else:
        gates.append(_g('frame_usability', 'pass',
                        '教师出画 %s' % (_mmss(offscreen) if offscreen is not None else '未统计'),
                        '机位 %d 路覆盖，抽帧 %d 张' % (len(videos), frames)))

    # 9 元数据完整性 ----------------------------------------------------
    goals = session.get('goals') or []
    if not goals:
        gates.append(_g('metadata_completeness', 'reject', '目标 0 条',
                        '缺课程目标，A2／A3 的分母不成立，目标匹配域记为空值'))
    elif not session.get('scenario') or not session.get('students'):
        gates.append(_g('metadata_completeness', 'warn', '目标 %d 条' % len(goals),
                        '缺课型或班额，部分口径无法确定'))
    else:
        gates.append(_g('metadata_completeness', 'pass', '目标 %d 条' % len(goals),
                        '课型、班额齐备'))

    worst = 'pass'
    if any(g['status'] == 'reject' for g in gates):
        worst = 'reject'
    elif any(g['status'] == 'warn' for g in gates):
        worst = 'warn'
    return worst, gates


def _mmss(sec):
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return '—'
    m = int(sec // 60)
    s = int(round(sec - m * 60))
    return '%d:%02d' % (m, s)


def blocked_codes(gates):
    """哪些指标的计分被门禁阻断。被阻断的项在 M5 里记空值并写原因，而不是记 0。"""
    status = {g['key']: g['status'] for g in gates}
    blocked = {}
    if status.get('transcript_quality') == 'reject' or status.get('speech_intelligibility') == 'reject':
        blocked.update({c: '转写质量未过关门禁，音频分项不予输出' for c in
                        ('A1', 'A2', 'A3', 'B1', 'B2', 'B4', 'B5', 'B6')})
    if status.get('role_separation') == 'reject':
        blocked['B6'] = '说话人未分离，互动类指标不予输出'
    if status.get('detection_sensitivity') == 'reject':
        blocked.update({c: '后排检测率过低，学生状态分项不予输出' for c in ('VB1', 'VB2', 'VB3')})
    if status.get('frame_usability') == 'reject':
        blocked.update({c: '画面不可用，视频分项不予输出' for c in
                        ('VA1', 'VA2', 'VA3', 'VA4', 'VA5')})
    if status.get('metadata_completeness') == 'reject':
        blocked.update({c: '缺课程目标，目标匹配域不予输出' for c in ('A1', 'A2', 'A3')})
    return blocked
