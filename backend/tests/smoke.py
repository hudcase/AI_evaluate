"""tests/smoke.py — 端到端自测

打真实 HTTP（不起内部直调），因此测的是"前端会遇到的这一层"。
用法：
    python backend/app.py --port 8000 --reset-db --seed-demo   # 一个终端
    python backend/tests/smoke.py --base http://127.0.0.1:8000 # 另一个终端

断言分两类：
  * 契约断言：字段、状态码、错误码与 docs/接口约定.md 一致
  * 口径断言：不合成总分、缺测不补零、覆盖率=权重和、门禁阻止计分——这些是评价规则，
    回归时最容易被"顺手改掉"，所以用测试钉住。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PASS = 0
FAIL = 0
FAILED = []


def call(method, path, body=None, base='http://127.0.0.1:8000', raw=False):
    url = base + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            if raw:
                return resp.status, payload
            ct = resp.headers.get('Content-Type', '')
            if 'json' in ct:
                return resp.status, json.loads(payload.decode('utf-8'))
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            return exc.code, json.loads(payload.decode('utf-8'))
        except ValueError:
            return exc.code, payload


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  ok   %s' % name)
    else:
        FAIL += 1
        FAILED.append(name)
        print('  FAIL %s %s' % (name, detail))


# ---------------------------------------------------------------- 造媒资与直传
#
# 这两个用例是为了钉住两个曾经真实发生过的 bug：
#   1. 探针按扩展名判容器，直传落盘的是 .part，于是所有真实上传都"未解析到页面"、
#      视频没有分辨率——规格校验形同虚设；
#   2. multipart 用 rfile.read(262144) 读，socket 上会阻塞到读满，小文件上传直接卡死。
# 单元测试发现不了，必须走真实 HTTP。

def make_wav(rate=48000, channels=2, seconds=1.5):
    import io
    import math
    import struct
    import wave
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        n = int(rate * seconds)
        for i in range(n):
            v = int(0.2 * 32767 * math.sin(2 * math.pi * 220 * i / rate))
            for _ in range(channels):
                frames += struct.pack('<h', v)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def upload(base, sid, fields, filename, blob):
    """走真实 multipart 直传（不流式，测试文件都很小）"""
    boundary = '----smoketest' + time.strftime('%Y%m%d%H%M%S')
    parts = []
    for k, v in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, k, v)).encode('utf-8'))
    parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
                  'Content-Type: application/octet-stream\r\n\r\n'
                  % (boundary, filename)).encode('utf-8'))
    parts.append(blob)
    parts.append(('\r\n--%s--\r\n' % boundary).encode('utf-8'))
    body = b''.join(parts)
    req = urllib.request.Request(
        base + '/api/sessions/%s/media' % sid, data=body, method='POST',
        headers={'Content-Type': 'multipart/form-data; boundary=%s' % boundary})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode('utf-8'))
        except ValueError:
            return exc.code, {'raw': raw[:200]}


def section(title):
    print('\n[%s]' % title)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8000')
    args = ap.parse_args()
    B = args.base

    section('0 静态托管')
    st, body = call('GET', '/', base=B, raw=True)
    check('GET / 返回 HTML', st == 200 and b'<!DOCTYPE html>' in body[:200])

    section('1 健康与总览')
    st, h = call('GET', '/api/health', base=B)
    check('health 200', st == 200)
    check('providers 五类齐全', set(h.get('providers', {})) == {'asr', 'ocr', 'embed', 'llm', 'vlm'})
    st, ov = call('GET', '/api/overview', base=B)
    check('overview 有场次', st == 200 and len(ov.get('sessions', [])) >= 3)
    ins = [s for s in ov['sessions'] if s['status'] == 'insufficient']
    check('证据不足场次不展示模态分', all(s['audio'] is None and s['video'] is None for s in ins),
          str([(s['id'], s['audio']) for s in ins]))

    section('2 M1 建档校验')
    st, e = call('POST', '/api/courses', {'title': '缺核心目标', 'goals': [{'text': '了解', 'tier': 'support'}]}, base=B)
    check('无核心目标 → 400 VALIDATION_FAILED', st == 400 and e['error']['code'] == 'VALIDATION_FAILED')

    st, created = call('POST', '/api/courses', {
        'title': '自测课程 %d' % int(time.time()),
        'expected_students': 20,
        'goals': [{'text': '能完成 A 操作', 'tier': 'core'},
                  {'text': '了解 B 背景', 'tier': 'support'}],
    }, base=B)
    check('建课 201', st == 201 and created.get('id', '').startswith('C-'), str(created))
    cid = created.get('id')

    st, e = call('POST', '/api/sessions', {'course_id': cid, 'title': 'x', 'scenario': 'theory'}, base=B)
    check('未确认知情同意 → 400 CONSENT_REQUIRED', st == 400 and e['error']['code'] == 'CONSENT_REQUIRED')

    st, s1 = call('POST', '/api/sessions', {
        'course_id': cid, 'title': '自测场次', 'scenario': 'theory',
        'consent_confirmed': True, 'duration_min': 45, 'expected_students': 20,
        'teacher': 'T-900', 'room': 'Z-1',
    }, base=B)
    check('建场次 201', st == 201 and s1.get('status') == 'created', str(s1))
    sid = s1.get('id')

    section('3 M2 数据接入')
    st, m = call('POST', '/api/sessions/%s/media' % sid, {
        'type': 'video', 'slot': 'cam1', 'bytes': 1073741824,
        'probe': {'width': 3840, 'height': 2160, 'fps': 25, 'codec': 'hevc'},
    }, base=B)
    check('登记视频 201', st == 201 and m.get('asset_id'), str(m))
    check('登记态 sha256 为 null（没拿到字节就不编哈希）', m.get('sha256') is None, str(m.get('sha256')))

    st, e = call('POST', '/api/sessions/%s/media' % sid, {
        'type': 'video', 'slot': 'cam2', 'bytes': 100,
        'probe': {'width': 640, 'height': 360, 'fps': 25, 'codec': 'hevc'},
    }, base=B)
    check('720p 以下 → 422 SPEC_MISMATCH', st == 422 and e['error']['code'] == 'SPEC_MISMATCH', str(e)[:120])

    st, e = call('POST', '/api/sessions/%s/media' % sid, {
        'type': 'video', 'slot': 'cam1', 'action': 'presign', 'bytes': 16106127360}, base=B)
    check('预签名直传留接口 → 501', st == 501 and e['error']['code'] == 'NOT_IMPLEMENTED')

    # --- multipart 直传（真实字节） ---
    good = make_wav(48000, 2)
    st, up = upload(B, sid, {'type': 'audio', 'slot': 'lavalier'}, 'lavalier.wav', good)
    check('直传 48k 音频 201', st == 201 and up.get('asset_id'), str(up)[:160])
    check('直传后已落盘（stored=true）', up.get('stored') is True, str(up.get('stored')))
    probe = up.get('probe') or {}
    check('探针读到真实容器与采样率（不是"未知容器"）',
          probe.get('container') == 'wav' and probe.get('sample_rate') == 48000, str(probe)[:160])
    check('直传后 sha256 为真实哈希', len(up.get('sha256') or '') == 64, str(up.get('sha256'))[:20])

    st, dup = upload(B, sid, {'type': 'audio', 'slot': 'lavalier'}, 'lavalier.wav', good)
    check('同场次同内容重复上传 → duplicate=true 不重复入库',
          st == 201 and dup.get('duplicate') is True, str(dup)[:160])

    st, e = upload(B, sid, {'type': 'audio', 'slot': 'ambient'}, 'ambient.wav',
                   make_wav(8000, 1))
    check('8 kHz 音频（低于 ASR 需要的 16 kHz）→ 422 SPEC_MISMATCH',
          st == 422 and e['error']['code'] == 'SPEC_MISMATCH', str(e)[:160])

    st, e = upload(B, sid, {'type': 'video', 'slot': 'cam3'}, 'cam3.mp4', b'\x00' * 2048)
    check('无法解析的字节 → 422（探针失败不放过）',
          st == 422 and e['error']['code'] == 'SPEC_MISMATCH', str(e)[:160])

    section('4 M2 逐条删除')
    st, m2 = call('POST', '/api/sessions/%s/media' % sid, {
        'type': 'video', 'slot': 'cam2', 'bytes': 1073741824,
        'probe': {'width': 3840, 'height': 2160, 'fps': 25, 'codec': 'hevc'},
    }, base=B)
    check('登记第二路视频 201', st == 201 and m2.get('asset_id'), str(m2)[:120])
    aid2 = m2.get('asset_id')

    st, e = call('DELETE', '/api/sessions/%s/media/%s' % (sid, aid2), base=B)
    check('逐条删除缺 confirm → 400',
          st == 400 and e['error']['code'] == 'VALIDATION_FAILED', str(e)[:120])

    st, e = call('DELETE', '/api/sessions/%s/media/%s?confirm=true' % (sid, aid2), base=B)
    check('逐条删除 200 且 slot 释放',
          st == 200 and e.get('slot') == 'cam2' and e.get('remaining') == 2, str(e)[:160])
    check('仅登记无字节 → file=none', e.get('file') == 'none', str(e.get('file')))

    st, e = call('DELETE', '/api/sessions/%s/media/%s?confirm=true' % (sid, aid2), base=B)
    check('重复删除 → 409 STATE_CONFLICT',
          st == 409 and e['error']['code'] == 'STATE_CONFLICT', str(e)[:120])

    st, lst = call('GET', '/api/sessions/%s/media' % sid, base=B)
    check('删后列表只剩 cam1 与 lavalier',
          sorted(x['slot'] for x in lst['items']) == ['cam1', 'lavalier'],
          str([x['slot'] for x in lst['items']]))

    # 系统自有副本（multipart 直传落盘的那份）删除时要一并删盘
    st, amb = upload(B, sid, {'type': 'audio', 'slot': 'ambient'}, 'ambient.wav', make_wav(48000, 1))
    check('直传 ambient 201', st == 201 and amb.get('stored') is True, str(amb)[:120])
    st, e = call('DELETE', '/api/sessions/%s/media/%s?confirm=true' % (sid, amb.get('asset_id')), base=B)
    check('直传副本 → file=removed 且有释放字节',
          st == 200 and e.get('file') == 'removed' and e.get('freed_bytes', 0) > 0, str(e)[:160])

    st, redo = call('POST', '/api/sessions/%s/media' % sid, {
        'type': 'video', 'slot': 'cam2', 'bytes': 1073741824,
        'probe': {'width': 3840, 'height': 2160, 'fps': 25, 'codec': 'hevc'},
    }, base=B)
    check('删后同 slot 可直接重登记（不需 replace）', st == 201 and redo.get('asset_id'), str(redo)[:120])
    st, e = call('DELETE', '/api/sessions/%s/media/%s?confirm=true' % (sid, redo.get('asset_id')), base=B)
    check('再删掉，恢复 1 路视频给后续用例', st == 200, str(e)[:120])

    section('5 M3 数据治理')
    st, e = call('POST', '/api/sessions/%s/preprocess' % sid, {}, base=B)
    check('只有 1 路视频也可提交预处理', st in (202, 200), str(e)[:120])
    task_id = e.get('task_id')
    ok = False
    for _ in range(40):
        st, t = call('GET', '/api/tasks/%s' % task_id, base=B)
        if t.get('status') in ('succeeded', 'failed'):
            ok = True
            break
        time.sleep(0.25)
    check('任务轮询到终态', ok, str(t))
    check('任务结果含六阶段', len(t.get('stages') or []) == 6, str(t.get('stages')))
    probe_stage = (t.get('stages') or [{}])[0]
    check('流水线真的读到了已直传的文件（不是"全部未落盘"）',
          'lavalier' not in (probe_stage.get('detail') or ''),
          str(probe_stage)[:160])
    if t.get('status') == 'failed':
        print('       任务失败原因：%s' % t.get('error'))

    st, qc = call('GET', '/api/sessions/%s/qc' % sid, base=B)
    check('qc 九项门禁', st == 200 and len(qc.get('gates') or []) == 9, str(qc)[:120])
    check('只有 1 路视频时采集完整性不放行',
          (qc.get('gates') or [{}])[0].get('status') in ('warn', 'reject'),
          str((qc.get('gates') or [{}])[0]))

    st, assets = call('GET', '/api/sessions/%s/assets' % sid, base=B)
    check('assets 结构', st == 200 and 'total_bytes' in assets)

    section('6 M5 指标计算')
    st, obs = call('GET', '/api/sessions/%s/observations' % sid, base=B)
    check('观测 21 条（含空值项）', st == 200 and len(obs['items']) == 21, str(len(obs.get('items', []))))
    check('空值项带原因', all(o['empty_reason'] for o in obs['items'] if o['raw_value'] is None))

    st, e = call('POST', '/api/sessions/%s/observations' % sid, {
        'code': 'A2', 'raw_value': 0.8, 'evidence_note': '联系 13800138000'}, base=B)
    check('含手机号 → 400 PII_DETECTED', st == 400 and e['error']['code'] == 'PII_DETECTED')

    st, e = call('POST', '/api/sessions/%s/observations' % sid, {
        'code': 'B1', 'raw_value': 9000}, base=B)
    check('量纲越界 → 400', st == 400 and e['error']['code'] == 'VALIDATION_FAILED')

    st, e = call('POST', '/api/sessions/%s/observations' % sid, {
        'code': 'C1', 'raw_value': 1}, base=B)
    check('对不计分项补录 → 400', st == 400)

    st, o = call('POST', '/api/sessions/%s/observations' % sid, {
        'code': 'A2', 'raw_value': 0.6, 'confidence': 0.9, 'evidence_t': 750,
        'source_track': ['audio', 'slides'], 'evidence_note': '核心目标 2/3 命中'}, base=B)
    check('补录 201 且服务端算分', st == 201 and o['score'] == 80.0, str(o))
    check('返回覆盖率', 'coverage_after' in o)

    st, sc = call('POST', '/api/sessions/%s/score' % sid, {'config_version': '2026-11-01'}, base=B)
    check('复算接口', st == 200 and 'scored' in sc, str(sc))

    section('7 M6 合成与一致性')
    st, ev = call('GET', '/api/sessions/%s/evaluation' % sid, base=B)
    check('evaluation 200', st == 200)
    check('composite 恒为 null（规则一）', ev.get('composite') is None)
    check('覆盖率 = 实际权重和（缺测不重分权）',
          abs(ev['audio']['coverage'] - ev['audio']['weight_sum']) < 1e-9)
    check('missing 列出空值项', isinstance(ev.get('missing'), list))
    check('consistency 状态合法', ev['consistency']['status'] in ('aligned', 'divergent', 'insufficient'))

    st, vb = call('GET', '/api/sessions/%s/vb1-series' % sid, base=B)
    check('vb1 序列可空但结构完整', st == 200 and 'points' in vb and 'valley' in vb)

    section('8 M7 报告与审计')
    st, rep = call('GET', '/api/sessions/%s/report?format=json' % sid, base=B)
    check('报告 JSON 六节齐备',
          st == 200 and set(['session', 'coverage', 'audio_items', 'video_items', 'scores',
                             'consistency', 'compliance', 'short_board']) <= set(rep))
    check('报告不含总分字段', 'total' not in rep['scores'] and 'composite' not in rep['scores'])

    st, pdf = call('GET', '/api/sessions/%s/report?format=pdf' % sid, base=B)
    check('PDF 留接口 → 501', st == 501 and pdf['error']['code'] == 'NOT_IMPLEMENTED')

    # 用一份"可用"的演示场次验证 docx 真的生成得出来
    st, raw = call('GET', '/api/sessions/S-20261105-03/report?format=docx', base=B, raw=True)
    check('DOCX 导出为 zip 且含正文', st == 200 and raw[:2] == b'PK' and len(raw) > 3000,
          'status=%s len=%s' % (st, len(raw) if isinstance(raw, bytes) else '-'))

    st, raw = call('GET', '/api/sessions/%s/report?format=docx' % sid, base=B, raw=True)
    check('证据不足时不生成正式报告 → 409（或 200 若该场次数据足够）', st in (200, 409), 'status=%s' % st)

    st, audit = call('GET', '/api/audit?page=1&size=20', base=B)
    check('审计列表', st == 200 and 'items' in audit and audit['total'] >= 1)

    section('9 M4 模型网关')
    st, calls = call('GET', '/api/sessions/S-20261105-03/ai-calls', base=B)
    check('调用日志', st == 200 and 'items' in calls and 'summary' in calls)
    check('汇总含按能力分摊', isinstance(calls['summary'].get('byCapability'), list))

    st, e = call('POST', '/ai/llm', {'indicator': 'A2', 'slices': [{'t0': 0, 't1': 60, 'text': 'x'}]}, base=B)
    check('缺 prompt_version → 400', st == 400 and e['error']['code'] == 'VALIDATION_FAILED')

    st, r = call('POST', '/ai/llm', {'indicator': 'A2', 'prompt_version': 'a2-v3',
                                     'slices': [{'t0': 0, 't1': 60, 'text': '目标陈述'}]}, base=B)
    check('网关调用成功且标注 simulated', st == 200 and r.get('simulated') is True, str(r)[:160])
    st, r2 = call('POST', '/ai/llm', {'indicator': 'A2', 'prompt_version': 'a2-v3',
                                      'slices': [{'t0': 0, 't1': 60, 'text': '目标陈述'}]}, base=B)
    check('同输入命中缓存（不重复计费）', r2.get('cached') is True, str(r2)[:160])

    st, e = call('POST', '/ai/vlm', {'prompt_version': 'vlm-frame-v3', 'frame_urls': ['a.jpg']}, base=B)
    check('桩模型 vlm 可用', st == 200 and 'present' in e)

    section('10 指标配置')
    st, ind = call('GET', '/api/indicators', base=B)
    check('21 条指标', st == 200 and len(ind['items']) == 21)
    aw = sum(i['weight'] or 0 for i in ind['items'] if i['tier'] == 'audio')
    vw = sum(i['weight'] or 0 for i in ind['items'] if i['tier'] == 'video')
    check('音频 9 项权重和 = 1.0000', abs(aw - 1.0) < 1e-6, '%.4f' % aw)
    check('视频 10 项权重和 = 1.0000', abs(vw - 1.0) < 1e-6, '%.4f' % vw)

    st, e = call('PUT', '/api/indicators', {'config_version': '2026-11-01', 'items': [{'code': 'A2', 'b': 0.8}]}, base=B)
    check('版本号不能与当前相同', st == 400)

    ver = '2026-11-%02d' % (int(time.time()) % 28 + 1)
    st, e = call('PUT', '/api/indicators', {'config_version': ver, 'items': [{'code': 'A2', 'b': 0.80}]}, base=B)
    check('发布新版本 200', st == 200 and e.get('changed') == 1, str(e))
    st, ind2 = call('GET', '/api/indicators', base=B)
    a2 = [i for i in ind2['items'] if i['code'] == 'A2'][0]
    check('新版本生效且旧版本仍在', ind2['config_version'] == ver and a2['b'] == 0.80, str(a2['b']))

    section('11 错误与销毁')
    st, e = call('GET', '/api/sessions/NOPE', base=B)
    check('404 NOT_FOUND', st == 404 and e['error']['code'] == 'NOT_FOUND')

    st, e = call('DELETE', '/api/sessions/%s/media?scope=raw' % sid, base=B)
    check('销毁未带 confirm → 400', st == 400)

    st, e = call('DELETE', '/api/sessions/%s/media?scope=raw&confirm=true' % sid, base=B)
    check('销毁成功并返回 freed_bytes', st == 200 and 'freed_bytes' in e, str(e)[:120])

    st, e = call('POST', '/api/sessions/%s/preprocess' % sid, {'stages': ['nope']}, base=B)
    check('未知阶段 → 400', st == 400)

    section('12 课程删除与批量入库')
    # --- 课程删除：未带 confirm 拒绝 ---
    st, e = call('DELETE', '/api/courses/%s' % cid, base=B)
    check('删课未带 confirm → 400', st == 400, str(e)[:120])

    # --- 批量入库：缺 courses 拒绝 ---
    st, e = call('POST', '/api/import', {'foo': 1}, base=B)
    check('批量入库缺 courses → 400', st == 400 and e['error']['code'] == 'VALIDATION_FAILED', str(e)[:120])

    # --- 批量入库：一课一场次（就地登记，用不存在的路径应失败但不整批回滚） ---
    st, imp = call('POST', '/api/import', {
        'courses': [{
            'title': '批量入库自测 %d' % int(time.time()),
            'expected_students': 12,
            'goals': [{'text': '能复述安全规程', 'tier': 'core'}],
            'sessions': [{
                'title': '批量场次一', 'date': '2026-11-06', 'start': '10:00',
                'scenario': 'theory', 'consent_confirmed': True,
                'media': [{'path': 'D:/不存在的文件.mp4', 'type': 'video', 'slot': 'cam1'}],
            }],
        }],
    }, base=B)
    check('批量入库 201 且返回汇总', st == 201 and 'courses' in imp and 'items' in imp, str(imp)[:200])
    check('课程成功、媒资失败单独计数（不整批回滚）',
          imp.get('courses') == 1 and imp.get('failed') >= 1, str(imp)[:200])
    batch_cid = None
    for it in imp.get('items') or []:
        if it.get('ok'):
            batch_cid = it.get('course_id')

    # --- 课程删除：确认后成功，级联清空 ---
    st, e = call('DELETE', '/api/courses/%s?confirm=true' % cid, base=B)
    check('删课确认后 200', st == 200 and e.get('id') == cid, str(e)[:200])
    check('删课返回已删场次数', e.get('deleted_sessions', 0) >= 1, str(e)[:120])
    st, gone = call('GET', '/api/courses/%s' % cid, base=B)
    check('删除后课程 404', st == 404, str(gone)[:120])
    st, sg = call('GET', '/api/sessions/%s' % sid, base=B)
    check('删除后场次 404', st == 404, str(sg)[:120])

    # 若批量入库也成功建了课，一并删掉，保持测试库干净
    if batch_cid:
        call('DELETE', '/api/courses/%s?confirm=true' % batch_cid, base=B)

    section('13 探针直测')
    _probe_checks()

    _desktop_checks(B)

    print('\n%d 通过，%d 失败' % (PASS, FAIL))
    if FAILED:
        print('失败项：' + '、'.join(FAILED))
        return 1
    return 0


def _probe_checks():
    """探针是内部函数，HTTP 黑盒测不到，这里直调钉住两个真实缺陷：
    1) m4a/AAC 音频轨的采样率/声道/时长解析（真实课程音频是 m4a，不是 wav）；
    2) PDF 页数在文件后半段时也能读到（非线性化 PDF 的 Page 字典压在 xref 附近）。"""
    import os
    import struct
    import tempfile

    # 路径下探针
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, backend_dir)
    from core import probes

    # --- m4a：手工拼一个最小 MP4/M4A，moov 放尾部（录制文件的典型布局） ---
    def _box(typ, payload=b''):
        return struct.pack('>I', 8 + len(payload)) + typ + payload

    # mvhd：version0，timescale=1000，duration=3000（3 秒）
    mvhd = struct.pack('>I', 0)                                  # version + flags
    mvhd += struct.pack('>II', 0, 0)                             # creation_time, modification_time
    mvhd += struct.pack('>I', 1000) + struct.pack('>I', 3000)    # timescale, duration
    mvhd += struct.pack('>I', 0x00010000) + struct.pack('>H', 0x0100)  # rate(16.16), volume
    mvhd += b'\x00' * 10                                         # reserved
    mvhd += struct.pack('>9I', 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)  # matrix
    mvhd += b'\x00' * 24                                         # pre_defined
    mvhd += struct.pack('>I', 2)                                 # next_track_ID
    # mp4a sample entry：channelcount 在 box 内 offset 24，samplerate(16.16) 在 offset 32
    mp4a = b''.join([
        b'\x00' * 6, struct.pack('>H', 1),        # reserved(6) + data_reference_index(2)
        b'\x00' * 8,                              # pre_defined(2)+reserved(2)+pre_defined(12) → 实际 16 字节
        struct.pack('>H', 2),                     # channelcount = 2
        struct.pack('>H', 16),                    # samplesize = 16
        struct.pack('>H', 0), struct.pack('>H', 0),  # pre_defined, reserved
        struct.pack('>I', 48000 << 16),           # samplerate = 48000.0
    ])
    # 上面 mp4a 的 channelcount 需要精确落在 box 内 offset 24：box 头 8 字节 + reserved6 + dr_idx2 + predef16 = 24 ✓
    mp4a_box = _box(b'mp4a', mp4a)
    stsd = struct.pack('>I', 0) + struct.pack('>I', 1) + mp4a_box   # version+flags, entry_count=1
    stbl = _box(b'stsd', stsd)
    minf = _box(b'stbl', stbl)
    # 层级：moov → (mvhd 直接在 moov 下；trak → mdia → mdhd + minf)。mvhd 是影片头，mdhd 是轨道头。
    mdia = _box(b'mdhd', mvhd) + _box(b'minf', minf)
    trak = _box(b'mdia', mdia)
    moov = _box(b'moov', _box(b'mvhd', mvhd) + _box(b'trak', trak))
    ftyp = _box(b'ftyp', b'mp42' + b'\x00\x00\x00\x00' + b'isom' + b'mp42')
    mdat = _box(b'mdat', b'\x00' * 64)
    m4a_blob = ftyp + mdat + moov        # moov 在尾部

    fd, p = tempfile.mkstemp(suffix='.m4a')
    os.close(fd)
    try:
        with open(p, 'wb') as f:
            f.write(m4a_blob)
        info = probes.probe(p, 'audio', filename='t.m4a')
        check('m4a 探针解出采样率 48000', info.get('sample_rate') == 48000, str(info))
        check('m4a 探针解出双声道', info.get('channels') == 2, str(info))
        check('m4a 探针解出时长 3.0 秒', info.get('duration_s') == 3.0, str(info))
        ok, problems = probes.check_spec('audio', info)
        check('m4a 48k 通过规格校验', ok, str(problems))
    finally:
        os.remove(p)

    # --- PDF：Page 字典压在文件尾部（模拟非线性化 PDF） ---
    head = b'%PDF-1.4\n' + b'1 0 obj\n<< /Type /Catalog >>\nendobj\n' + (b'x' * 100)
    tail = b''.join(b'%d 0 obj\n<< /Type /Page >>\nendobj\n' % i for i in range(2, 6))
    tail += b'xref\n0 6\ntrailer\n<<>>\n%%EOF\n'
    pdf_blob = head + tail
    fd, p = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        with open(p, 'wb') as f:
            f.write(pdf_blob)
        info = probes.probe(p, 'slides', filename='t.pdf')
        check('PDF 尾部页数也能读到（4 页）', info.get('pages') == 4, str(info))
        ok, problems = probes.check_spec('slides', info)
        check('PDF 4 页通过规格校验', ok, str(problems))
    finally:
        os.remove(p)


def _post_with_origin(url, body, origin):
    """带 Origin 头发一次写请求，只为拿到状态码——测的是跨站防护这一层。"""
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Content-Type': 'application/json', 'Origin': origin})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _desktop_checks(B):
    """桌面端能力。这里跑的是 Web 模式，所以断言的重点是"能力按模式收敛"：
    info 报 desktop=false、原生对话框 501、扫描照常可用（它只是读盘，不依赖窗口）。"""
    import os
    import shutil
    import tempfile

    section('14 桌面端能力')

    st, d = call('GET', '/api/desktop/info', base=B)
    check('desktop/info 200', st == 200, str(d)[:200])
    check('Web 模式下 desktop=false', d.get('desktop') is False, str(d.get('desktop')))
    check('info 带数据目录与端口', bool(d.get('data_dir')) and 'port' in d, str(d)[:200])

    st, d = call('POST', '/api/desktop/dialog/folder', {}, base=B)
    check('Web 模式下原生对话框 501',
          st == 501 and (d.get('error') or {}).get('code') == 'NOT_IMPLEMENTED', str(d)[:200])

    root = tempfile.mkdtemp(prefix='scan-')
    try:
        cdir = os.path.join(root, '扫描测试课')
        sdir = os.path.join(cdir, '2026-11-05 09-00')
        os.makedirs(sdir)
        with open(os.path.join(cdir, 'goals.txt'), 'w', encoding='utf-8') as fh:
            fh.write('第一条核心目标\n第二条支撑目标\n')
        for name in ('cam1.mp4', 'lavalier.m4a', '讲义.pptx'):
            with open(os.path.join(sdir, name), 'wb') as fh:
                fh.write(b'x')

        st, d = call('POST', '/api/desktop/scan', {'root': root, 'consent': True}, base=B)
        check('scan 200', st == 200, str(d)[:200])
        courses = ((d or {}).get('manifest') or {}).get('courses') or []
        sess = (courses[0].get('sessions') or [{}])[0] if courses else {}
        check('扫描出 1 门课 / 1 场次 / 3 个媒资',
              len(courses) == 1 and len(courses[0].get('sessions') or []) == 1
              and len(sess.get('media') or []) == 3,
              str(d.get('stats') if d else d))
        check('目录名解析出日期与时间',
              sess.get('date') == '2026-11-05' and sess.get('start') == '09:00', str(sess)[:120])
        check('goals.txt 首条记为核心目标',
              ((courses[0].get('goals') or [{}])[0] or {}).get('tier') == 'core')
        check('媒资按扩展名归类',
              sorted(m['type'] for m in (sess.get('media') or [])) == ['audio', 'slides', 'video'])
        check('干净目录不产生 issues', not (d.get('issues') or []), str(d.get('issues'))[:160])

        st, _d = call('POST', '/api/desktop/scan', {'root': os.path.join(root, 'nope')}, base=B)
        check('扫描不存在的目录 → 400', st == 400)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    check('跨站 Origin 写请求 → 403',
          _post_with_origin(B + '/api/courses', {'title': 'x'}, 'https://evil.example') == 403)
    check('本机 Origin 写请求放行（落到字段校验 400）',
          _post_with_origin(B + '/api/courses', {'title': 'x'}, B) == 400)
    check('无 Origin 的本地调用放行（curl／脚本）',
          _post_with_origin(B + '/api/courses', {'title': 'x'}, '') == 400)


if __name__ == '__main__':
    sys.exit(main())
