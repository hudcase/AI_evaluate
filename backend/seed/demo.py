"""seed/demo.py — 演示数据

三件事必须做到，否则这份数据会把结论带偏：

1. **分数是算出来的**：只写原始量与量尺参数，分项分由 core/membership 现算。
   因此界面上的"原始量 → 分项分 → 模态分"三者可反推，评审时经得起验算。
2. **四种状态各有实物**：可用 / 证据不一致 / 证据不足 / 处理中。
   证据不足那一场是双模态覆盖率都低于 0.60——不是"分数低"，是"没测到"。
3. **门禁结论由指标算出**，不写死状态；模型质量指标（SNR／CER／DER／后排检测率）
   作为"已经跑过的模型产物"写进任务结果，代表这份数据所处的阶段。

这些数字全部是构造的，不代表任何真实课例。B3 口音可懂度在所有场次都是空值——
无人工盲听时该指标实际不可得，这是设计结论，不是数据缺失。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import db
import util

from core import gates as gates_mod
from core import membership
from core import tasks as tasks_mod


COURSES = [
    {
        'id': 'C-20261105-01', 'title': '新员工安全生产培训',
        'expected_students': 42, 'created_at': '2026-11-05T08:10:00+08:00',
        'goals': [
            {'text': '能识别车间三类高危作业场景', 'tier': 'core'},
            {'text': '能正确佩戴与检查个人防护装备', 'tier': 'core'},
            {'text': '能说明事故上报与应急处置流程', 'tier': 'core'},
            {'text': '了解班组安全责任制的基本要求', 'tier': 'support'},
        ],
    },
    {
        'id': 'C-20261104-02', 'title': '骨干教师课堂提问技巧',
        'expected_students': 24, 'created_at': '2026-11-04T09:00:00+08:00',
        'goals': [
            {'text': '能区分封闭式与开放式提问的适用场景', 'tier': 'core'},
            {'text': '能在讲授中设计至少两轮追问', 'tier': 'core'},
            {'text': '能控制候答时长不低于 3 秒', 'tier': 'support'},
        ],
    },
    {
        'id': 'C-20261103-01', 'title': '现场急救处置实训',
        'expected_students': 30, 'created_at': '2026-11-03T13:30:00+08:00',
        'goals': [
            {'text': '能完成成人心肺复苏的标准按压流程', 'tier': 'core'},
            {'text': '能正确使用 AED 并完成电极片粘贴', 'tier': 'core'},
            {'text': '能判断现场环境安全并呼叫支援', 'tier': 'support'},
        ],
    },
]

SESSIONS = [
    {
        'id': 'S-20261105-03', 'course_id': 'C-20261105-01', 'title': '第三讲 高处作业防护',
        'scenario': 'theory', 'teacher': 'T-014', 'room': 'A-302',
        'date': '2026-11-05', 'start': '13:30', 'duration_min': 90, 'students': 42,
        'status': 'ok', 'stage': 'report',
        'nulls': ['B3'], 'overrides': {},
        'valley': {'from': 760, 'to': 1090, 'min': 0.41},
        'metrics': {'snr_db': 21.4, 'low_snr_ratio': 0.032, 'cer': 0.081, 'high_conf_ratio': 0.942,
                    'der': 0.064, 'overlap_miss': 2, 'back_row_error': 0.097,
                    'back_row_detect': 0.63, 'teacher_offscreen_s': 38},
    },
    {
        'id': 'S-20261104-02', 'course_id': 'C-20261104-02', 'title': '第二讲 追问的设计与候答',
        'scenario': 'seminar', 'teacher': 'T-021', 'room': 'B-105',
        'date': '2026-11-04', 'start': '09:00', 'duration_min': 90, 'students': 24,
        'status': 'divergent', 'stage': 'report',
        'nulls': ['B3'],
        'overrides': {'A2': 0.70, 'A3': 0.78, 'B6': 0.62, 'VB1': 0.44,
                      'VB2': 0.22, 'VB3': 0.22, 'VC1': 0.55},
        'valley': {'from': 1200, 'to': 1680, 'min': 0.33},
        'metrics': {'snr_db': 22.8, 'low_snr_ratio': 0.021, 'cer': 0.062, 'high_conf_ratio': 0.963,
                    'der': 0.051, 'overlap_miss': 1, 'back_row_error': 0.061,
                    'back_row_detect': 0.72, 'teacher_offscreen_s': 12},
    },
    {
        'id': 'S-20261103-01', 'course_id': 'C-20261103-01', 'title': '实操单元 心肺复苏与 AED',
        'scenario': 'practical', 'teacher': 'T-008', 'room': '实训楼 C-1',
        'date': '2026-11-03', 'start': '13:30', 'duration_min': 120, 'students': 30,
        'status': 'insufficient', 'stage': 'report',
        'nulls': ['B3', 'B2', 'B4', 'B5', 'B6', 'VA3', 'VA4', 'VA5', 'VB1'],
        'overrides': {}, 'valley': None,
        'metrics': {'snr_db': 17.2, 'low_snr_ratio': 0.118, 'cer': 0.148, 'high_conf_ratio': 0.874,
                    'der': 0.121, 'overlap_miss': 5, 'back_row_error': 0.142,
                    'back_row_detect': 0.51, 'teacher_offscreen_s': 96},
    },
    {
        'id': 'S-20261105-04', 'course_id': 'C-20261105-01', 'title': '第四讲 用电安全与检修挂牌',
        'scenario': 'theory', 'teacher': 'T-014', 'room': 'A-302',
        'date': '2026-11-05', 'start': '15:30', 'duration_min': 90, 'students': 41,
        'status': 'processing', 'stage': 'preprocess',
        'nulls': [], 'overrides': {}, 'valley': None, 'metrics': {},
    },
]

BASE_RAW = {
    'A1': 0.82, 'A2': 0.62, 'A3': 0.68, 'B1': 178, 'B2': 0.74, 'B3': None, 'B4': 0.81,
    'B5': 0.70, 'B6': 0.45,
    'VA1': 9, 'VA2': 0.66, 'VA3': 0.52, 'VA4': 7, 'VA5': 0.32,
    'VB1': 0.68, 'VB2': 0.12, 'VB3': 0.34, 'VC1': 0.48, 'VC2': 0.75,
}

EVIDENCE_T = {
    'A1': 96, 'A2': 750, 'A3': 2410, 'B1': 1820, 'B2': 2380, 'B3': None, 'B4': 2960,
    'B5': 3420, 'B6': 2110,
    'VA1': 1260, 'VA2': 430, 'VA3': 880, 'VA4': 1620, 'VA5': 2760,
    'VB1': 760, 'VB2': 1340, 'VB3': 2110, 'VC1': 1520, 'VC2': 60,
}

NOTE = {
    'A1': '前 5 分钟内陈述 3 条学习结果，未夹带章节标题',
    'A2': '核心目标 3/3 命中；语义相似度与 LLM 判定一致',
    'A3': '离题段落 2 段（设备采购闲聊），共 4 分 10 秒',
    'B1': '净发音速率中位数 178 字/分，P10 142、P90 236',
    'B2': '句末降调占比 0.71，重音落点与术语一致',
    'B3': '无盲听数据；无人工环节下该指标不可得',
    'B4': '犹豫 14 次、重启 5 次，必要修正 7 次未扣分',
    'B5': '结构提示 9 处，术语解释 6 个，案例 2 例',
    'B6': '有效提问 11 次，有回应 5 次，平均候答 2.1 秒',
    'VA1': '手势 9 次/分；内容性占比记空值（需人工编码）',
    'VA2': '开放姿态占 0.66，抱臂累计 1 分 52 秒',
    'VA3': '学生区注视 0.52，扫视 27 次',
    'VA4': '走动 7 次/课时，九宫格覆盖 6 格',
    'VA5': '疑似念读 0.32，主要为条款逐条宣读',
    'VB1': '抬头率均值 0.68，12:40 起连续 5 分 30 秒低于警戒线',
    'VB2': '非教学手机使用 0.12，集中于 22–27 分钟',
    'VB3': '举手 6 人次，应答 14 人次',
    'VC1': '学生话语占比 0.48，提问—回应链 9 组',
    'VC2': '导入／讲授／互动／小结四项齐备',
}

SOURCE_TRACK = {
    'A1': ['audio'], 'A2': ['audio', 'slides'], 'A3': ['audio', 'slides'],
    'B1': ['audio'], 'B2': ['audio'], 'B3': ['audio'], 'B4': ['audio'],
    'B5': ['audio', 'slides'], 'B6': ['audio'],
    'VA1': ['video'], 'VA2': ['video'], 'VA3': ['video'], 'VA4': ['video'],
    'VA5': ['video', 'audio', 'slides'],
    'VB1': ['video'], 'VB2': ['video'], 'VB3': ['video', 'audio'],
    'VC1': ['video', 'audio'], 'VC2': ['video', 'audio'],
}

AI_CALLS = [
    # capability, provider, model_version, prompt_version, tokens_in, tokens_out, latency_ms, cost, cached
    ('asr', 'asr-pro', '2026-09', 'asr-zh-v4', 0, 0, 41200, 1.28, 0),
    ('asr', 'asr-pro', '2026-09', 'asr-zh-v4', 3100, 940, 38600, 1.18, 0),
    ('ocr', 'ocr-doc', '2026-07', 'ocr-page-v2', 220, 60, 1420, 0.09, 0),
    ('ocr', 'ocr-doc', '2026-07', 'ocr-page-v2', 180, 40, 1310, 0.08, 1),
    ('embed', 'embed-l', '2026-05', 'emb-1024', 480, 0, 640, 0.02, 0),
    ('llm', 'llm-chat', '2026-09', 'a2-v3', 1820, 240, 2140, 0.24, 0),
    ('llm', 'llm-chat', '2026-09', 'a3-v2', 1640, 180, 1980, 0.21, 0),
    ('llm', 'llm-chat', '2026-09', 'b5-v2', 2100, 320, 2410, 0.30, 0),
    ('llm', 'llm-chat', '2026-09', 'b6-v1', 1480, 160, 1760, 0.19, 1),
    ('vlm', 'vlm-frame', '2026-08', 'vlm-frame-v3', 9400, 620, 4820, 0.62, 0),
    ('vlm', 'vlm-frame', '2026-08', 'vlm-frame-v3', 8800, 580, 4610, 0.58, 0),
    ('vlm', 'vlm-frame', '2026-08', 'vlm-frame-v3', 9100, 610, 4720, 0.61, 1),
]


def _vb1_series(session):
    """与前端 mock 同一套伪随机，保证切后端前后曲线形状一致"""
    pts = []
    seed = ord(session['id'][-1])
    minutes = session['duration_min']
    valley = session.get('valley')
    import math
    for t in range(0, minutes * 60 + 1, 60):
        seed = (seed * 9301 + 49297) % 233280
        noise = (seed / 233280.0 - 0.5) * 0.09
        base = 0.76 + 0.10 * math.sin(t / 900.0)
        if valley and valley['from'] <= t <= valley['to']:
            base = valley['min'] + 0.04 * math.sin(t / 240.0)
        v = max(0.18, min(0.96, base + noise))
        pts.append({'t': t, 'v': round(v, 3)})
    return pts


def _assets(session):
    frames = int(round(session['duration_min'] * 60 / 10.0)) * 2
    items = [
        {'kind': 'proxy', 'label': '720p 代理', 'count': 2, 'bytes': 4294967296, 'retention_days': 30},
        {'kind': 'frames', 'label': '抽帧（1 帧/10 秒）', 'count': frames,
         'bytes': frames * 200000, 'retention_days': 30},
        {'kind': 'roi', 'label': 'ROI 裁切', 'count': 146, 'bytes': 284000000, 'retention_days': 30},
        {'kind': 'audio16k', 'label': '16k 单声道（送 ASR）', 'count': 2, 'bytes': 350000000,
         'retention_days': 1},
        {'kind': 'slides', 'label': '课件解析 JSON', 'count': 1, 'bytes': 210000, 'retention_days': None},
    ]
    return {'items': items, 'total_bytes': sum(i['bytes'] for i in items)}


STAGES_DONE = [
    {'key': 'probe', 'label': '校验登记', 'status': 'done', 'detail': '5 个资产探针通过（演示数据）'},
    {'key': 'transcode', 'label': '转码派生', 'status': 'done', 'detail': '生成 2 个 720p 代理（演示数据）'},
    {'key': 'extract', 'label': '抽帧 ROI', 'status': 'done', 'detail': '按 1 帧/10 秒抽帧（演示数据）'},
    {'key': 'parse_slides', 'label': '课件解析', 'status': 'done', 'detail': '解析 38 页，3 页无文本需 OCR'},
    {'key': 'mask', 'label': '脱敏', 'status': 'skipped', 'detail': 'ROI 打码留接口：需人脸／人体检测模型'},
    {'key': 'gate', 'label': '门禁判定', 'status': 'done', 'detail': '九项门禁已判定'},
]


def _media_rows(session):
    d = session['duration_min'] * 60
    base = [
        ('video', 'cam1', 'cam1_4k.mp4', 16106127360,
         {'width': 3840, 'height': 2160, 'fps': 25, 'codec': 'hevc', 'bitrate_mbps': 16.2}, 7),
        ('video', 'cam2', 'cam2_4k.mp4', 15032385536,
         {'width': 3840, 'height': 2160, 'fps': 25, 'codec': 'hevc', 'bitrate_mbps': 15.1}, 7),
        ('audio', 'lavalier', 'lav_48k.wav', 518000000,
         {'sample_rate': 48000, 'channels': 1, 'bits': 16, 'clip': False}, 30),
        ('audio', 'ambient', 'amb_48k.wav', 518000000,
         {'sample_rate': 48000, 'channels': 1, 'bits': 16, 'clip': False}, 30),
        ('slides', 'deck', '高处作业防护.pptx', 8912345,
         {'pages': 38, 'images': 12, 'image_only_pages': 3}, None),
    ]
    out = []
    for i, (typ, slot, name, size, probe, ret) in enumerate(base, 1):
        out.append({
            'id': 'M-%s-%d' % (session['id'][-5:], i), 'type': typ, 'slot': slot, 'name': name,
            'bytes': size, 'sha256': ('9f3a%dc1e2b4d7%s' % (i, session['id'][-4:])).lower(),
            'duration_s': d if typ in ('video', 'audio') else None,
            'probe': probe, 'retention_days': ret,
        })
    return out


def seed(force=False):
    if db.scalar('SELECT COUNT(1) FROM sessions', (), 0) and not force:
        return 0

    cfg = db.config_items()
    ind_of = {r['code']: r for r in cfg['items']}

    with db.tx():
        for c in COURSES:
            db.x("""INSERT OR IGNORE INTO courses (id, title, expected_students, goals_json, created_at)
                    VALUES (?,?,?,?,?)""",
                 (c['id'], c['title'], c['expected_students'], util.dumps(c['goals']), c['created_at']))

    for s in SESSIONS:
        with db.tx():
            db.x("""INSERT OR IGNORE INTO sessions (id, course_id, title, scenario, consent_confirmed,
                    teacher, room, date, start, duration_min, students, status, stage, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (s['id'], s['course_id'], s['title'], s['scenario'], 1, s['teacher'], s['room'],
                  s['date'], s['start'], s['duration_min'], s['students'], s['status'], s['stage'],
                  '%sT%s:00+08:00' % (s['date'], s['start'])))
            for m in _media_rows(s):
                db.x("""INSERT OR IGNORE INTO media_assets (id, session_id, type, slot, name, path, bytes,
                        sha256, duration_s, probe_json, retention_days, status, created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (m['id'], s['id'], m['type'], m['slot'], m['name'], None, m['bytes'],
                      m['sha256'], m['duration_s'], util.dumps(m['probe']), m['retention_days'],
                      'registered', '%sT%s:00+08:00' % (s['date'], s['start'])))

        if s['status'] == 'processing':
            _seed_running_task(s)
            continue

        _seed_observations(s, ind_of)
        _seed_task(s)
        _seed_calls(s)

    _seed_audit()
    return len(SESSIONS)


def _seed_observations(s, ind_of):
    series = _vb1_series(s)
    now = '%sT%s:00+08:00' % (s['date'], s['start'])
    with db.tx():
        for code, ind in ind_of.items():
            raw = s['overrides'].get(code, BASE_RAW.get(code))
            if code in s['nulls']:
                raw = None
            score = membership.score(ind, raw) if raw is not None else None
            conf = None
            if raw is not None and ind['scored']:
                conf = membership.default_confidence(score)
            empty = None
            if raw is None:
                if ind['direction'] == 'gate':
                    empty = '未检出候选事件，门禁通过'
                elif ind['direction'] == 'listed':
                    empty = '列示项：本项目不设当堂测验，无数据来源'
                elif code == 'B3':
                    empty = '无盲听数据：无人工环节下该指标不可得'
                else:
                    empty = '门禁未通过或数据缺失，不予输出'
            db.x("""INSERT OR REPLACE INTO observations (id, session_id, code, raw_value, denominator,
                    unit, confidence, evidence_t, source_track_json, note, empty_reason, model_version,
                    score, series_json, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 ('O-%s-%s' % (s['id'][-5:], code), s['id'], code, raw, None, ind['unit'], conf,
                  EVIDENCE_T.get(code) if raw is not None else None,
                  util.dumps(SOURCE_TRACK.get(code, ['audio'])), NOTE.get(code), empty,
                  'asr-2026-09' if ind['tier'] == 'audio' else 'vlm-frame-v3',
                  score, util.dumps(series) if code == 'VB1' else None, now, now))


def _seed_task(s):
    media = [dict(m) for m in _media_rows(s)]
    derived = {'frames': int(round(s['duration_min'] * 60 / 10.0)) * 2}
    course = [c for c in COURSES if c['id'] == s['course_id']][0]
    overall, gl = gates_mod.compute(
        {'duration_min': s['duration_min'], 'goals': course['goals'],
         'scenario': s['scenario'], 'students': s['students']},
        media, s['metrics'], derived)

    stages = [dict(x) for x in STAGES_DONE]
    stages[-1]['detail'] = '九项门禁：%d 项通过，%d 项注意，%d 项阻断' % (
        len([g for g in gl if g['status'] == 'pass']),
        len([g for g in gl if g['status'] == 'warn']),
        len([g for g in gl if g['status'] == 'reject']))

    result = {
        'stages': stages,
        'assets': _assets(s),
        'gates': gl,
        'gate_overall': overall,
        'model_metrics': s['metrics'],
        'frames': derived['frames'],
        'slides_pages': 38,
        'finished_at': '%sT%s:00+08:00' % (s['date'], s['start']),
    }
    tasks_mod.seed_succeeded(s['id'], result,
                             started_at='%sT%s:00+08:00' % (s['date'], s['start']),
                             finished_at='%sT%s:00+08:00' % (s['date'], s['start']))


def _seed_running_task(s):
    task_id = util.new_id('T')
    db.x("""INSERT INTO ai_tasks (id, session_id, kind, status, progress, stage, error,
            result_json, started_at, finished_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
         (task_id, s['id'], 'preprocess', 'running', 0.62, 'extract', None,
          '{"seeded":true}',
          '%sT%s:00+08:00' % (s['date'], s['start']), None,
          '%sT%s:00+08:00' % (s['date'], s['start'])))
    db.x("UPDATE sessions SET stage='preprocess', status='processing' WHERE id=?", (s['id'],))


def _seed_calls(s):
    # simulated=1：演示数据里的调用全部是编造的，成本是"按价目表估算"而非真账单。
    # 若标成 0，前端与总览会把它们当成真实已发生的调用。
    for i, row in enumerate(AI_CALLS):
        cap, prov, mv, pv, tin, tout, lat, cost, cached = row
        db.x("""INSERT INTO ai_calls (id, session_id, capability, provider, model_version,
                prompt_version, input_hash, tokens_in, tokens_out, latency_ms, cost, cached,
                simulated, response_json, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             ('A-%s-%02d' % (s['id'][-4:], i + 1), s['id'], cap, prov, mv, pv,
              util.sha256_text('%s-%d' % (s['id'], i))[:32], tin, tout, lat, cost, cached, 1, None,
              '2026-11-05T%02d:%02d:00+08:00' % (13 + i // 4, (i * 7) % 60)))


def _seed_audit():
    rows = [
        ('report.export', 'S-20261105-03', 'admin', '2026-11-05T19:31:00+08:00'),
        ('evaluation.compute', 'S-20261105-03', 'system', '2026-11-05T19:28:00+08:00'),
        ('observation.write', 'S-20261105-03', 'system', '2026-11-05T19:26:00+08:00'),
        ('preprocess.succeeded', 'S-20261105-03', 'system', '2026-11-05T19:21:00+08:00'),
        ('media.upload', 'S-20261105-03', 'admin', '2026-11-05T19:14:00+08:00'),
        ('session.create', 'S-20261105-03', 'admin', '2026-11-05T19:12:00+08:00'),
    ]
    for action, obj, actor, at in rows:
        db.x('INSERT INTO audit (id, action, object_id, actor, detail_json, at) VALUES (?,?,?,?,?,?)',
             (util.new_id('L'), action, obj, actor, '{}', at))


if __name__ == '__main__':
    import config
    config.ensure_dirs()
    db.init()
    print('seeded sessions:', seed(force=True))
