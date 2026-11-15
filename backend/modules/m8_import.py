"""modules/m8_import.py — 批量入库

前端「批量入库」入口走这里：一次提交一份清单，后端按「课程 → 场次 → 媒资 → 观测」
顺序逐项落库，逐项回报结果（哪一门成了、哪一条媒资重复、哪个文件缺失）。

与 tools/import.py 的 manifest 是同一套结构，只是从命令行搬到了 HTTP：
  {
    "courses": [{
      "title": "...", "expected_students": 32,
      "goals": [{"text": "...", "tier": "core"}],
      "sessions": [{
        "title": "...", "date": "2026-11-05", "start": "09:00",
        "duration_min": 90, "scenario": "theory", "teacher": "...", "room": "...",
        "consent_confirmed": true,
        "media": [{"path": "D:/.../cam1.mp4", "type": "video", "slot": "cam1"}],
        "observations": [{"code": "A2", "raw_value": 0.82, "confidence": 0.9}]
      }]
    }]
  }

复用判据与命令行一致：课程按标题、场次按日期+开始时间+标题。重跑不重复建课。
媒资走"就地登记"（path 已在盘上），不搬字节——几十 GB 原片不做二次拷贝。
"""
import os

import db
import errors
import util

from . import m1_courses, m2_media, m5_indicators

SCENARIOS = ('theory', 'seminar', 'practical')


def _clean_goals(goals):
    """复用 m1_courses 的校验，但失败时抛出结构化错误供前端逐条展示"""
    return m1_courses._clean_goals(goals)


def _find_course(title):
    rows = db.q('SELECT * FROM courses WHERE title = ?', (title.strip(),))
    return rows[0] if rows else None


def _find_session(cid, title, date, start):
    rows = db.q("""SELECT * FROM sessions WHERE course_id = ? AND title = ?
                   AND date = ? AND start = ?""",
                (cid, title.strip(), date, start))
    return rows[0] if rows else None


def import_batch(body):
    """body = manifest 清单；返回逐项结果汇总。全部成功仍返回 200，有失败也返回 200
    但带 failed 计数——批量导入的本质是"能进的进，进不去的单独报"，不应因一条坏数据
    整批回滚（媒资在盘上，回滚无意义）。"""
    courses = body.get('courses')
    if not isinstance(courses, list) or not courses:
        errors.fail('VALIDATION_FAILED', '清单需包含 courses 数组', 'courses')

    summary = {'courses': 0, 'sessions': 0, 'assets': 0, 'observations': 0,
               'duplicate': 0, 'failed': 0}
    results = []

    for c in courses:
        c_result = _import_course(c, summary)
        results.append(c_result)

    summary['items'] = results
    return summary


def _import_course(c, summary):
    title = (c.get('title') or '').strip()
    out = {'title': title or '(无标题)', 'ok': False, 'error': None,
           'reused': False, 'sessions': []}

    if not title:
        out['error'] = '缺 title'
        summary['failed'] += 1
        return out

    goals = c.get('goals') or []
    if not goals:
        out['error'] = '缺 goals（至少 1 条 core）'
        summary['failed'] += 1
        return out

    try:
        goals_clean = _clean_goals(goals)
    except errors.ApiError as exc:
        out['error'] = exc.message
        summary['failed'] += 1
        return out

    course = _find_course(title)
    if course:
        cid = course['id']
        out['reused'] = True
    else:
        try:
            students = int(c.get('expected_students') or 0)
        except (TypeError, ValueError):
            students = 0
        try:
            cid = m1_courses.create_course({
                'title': title, 'expected_students': students, 'goals': goals_clean})
            cid = cid['id']
        except errors.ApiError as exc:
            out['error'] = exc.message
            summary['failed'] += 1
            return out
        summary['courses'] += 1

    out['course_id'] = cid
    out['ok'] = True

    for s in c.get('sessions') or []:
        out['sessions'].append(_import_session(cid, s, summary))

    return out


def _import_session(cid, s, summary):
    title = (s.get('title') or '').strip()
    date = (s.get('date') or util.now().strftime('%Y-%m-%d')).strip()
    start = (s.get('start') or '09:00').strip()
    scenario = s.get('scenario') or 'theory'
    out = {'title': title or '(无标题)', 'ok': False, 'error': None,
           'reused': False, 'assets': [], 'observations': []}

    if scenario not in SCENARIOS:
        out['error'] = 'scenario 需为 theory／seminar／practical'
        summary['failed'] += 1
        return out

    consent = s.get('consent_confirmed')
    if consent is not True:
        out['error'] = 'consent_confirmed 必须为 true（知情同意是流程约束）'
        summary['failed'] += 1
        return out

    existing = _find_session(cid, title, date, start)
    if existing:
        sid = existing['id']
        out['reused'] = True
    else:
        try:
            r = m1_courses.create_session({
                'course_id': cid, 'title': title, 'consent_confirmed': True,
                'scenario': scenario, 'date': date, 'start': start,
                'duration_min': s.get('duration_min') or 90,
                'teacher': s.get('teacher'), 'room': s.get('room'),
                'expected_students': s.get('expected_students')})
            sid = r['id']
        except errors.ApiError as exc:
            out['error'] = exc.message
            summary['failed'] += 1
            return out
        summary['sessions'] += 1

    out['session_id'] = sid
    out['ok'] = True

    for m in s.get('media') or []:
        out['assets'].append(_import_asset(sid, m, summary))

    for o in s.get('observations') or []:
        out['observations'].append(_import_obs(sid, o, summary))

    return out


def _import_asset(sid, m, summary):
    typ = m.get('type')
    name = (m.get('path') or m.get('file') or '').strip()
    out = {'file': name or '(无路径)', 'ok': False, 'error': None, 'duplicate': False}

    if typ not in ('video', 'audio', 'slides', 'goals'):
        out['error'] = '未知 type=%s' % typ
        summary['failed'] += 1
        return out
    if not name:
        out['error'] = '缺 path'
        summary['failed'] += 1
        return out

    path = name if os.path.isabs(name) else name
    if typ == 'goals':
        # goals 类型只是标记目标文本，不落文件；跳过（目标已随课程写入）
        out['ok'] = True
        out['note'] = '目标随课程写入，无需单独入库'
        return out

    try:
        body = {'path': path, 'name': os.path.basename(path), 'type': typ,
                'slot': m.get('slot')}
        if m.get('replace'):
            body['replace'] = True
        r = m2_media.register(sid, body)
        out['asset_id'] = r.get('asset_id') or r.get('id')
        out['duplicate'] = bool(r.get('duplicate'))
        out['ok'] = True
        if out['duplicate']:
            summary['duplicate'] += 1
        else:
            summary['assets'] += 1
    except errors.ApiError as exc:
        out['error'] = exc.message
        summary['failed'] += 1
    return out


def _import_obs(sid, o, summary):
    code = (o.get('code') or '').strip()
    out = {'code': code or '(无编码)', 'ok': False, 'error': None}
    if not code:
        out['error'] = '缺 code'
        summary['failed'] += 1
        return out
    try:
        body = {'code': code}
        for k in ('raw_value', 'denominator', 'confidence'):
            if o.get(k) is not None and o.get(k) != '':
                try:
                    body[k] = float(o[k])
                except (TypeError, ValueError):
                    pass
        for k in ('evidence_t', 'evidence_note', 'empty_reason', 'model_version'):
            if o.get(k) not in (None, ''):
                body[k] = str(o[k]).strip()
        if o.get('source_track'):
            t = o['source_track']
            body['source_track'] = list(t) if isinstance(t, (list, tuple)) else [t]
        r = m5_indicators.post_observation(sid, body)
        out['ok'] = True
        out['score'] = r.get('score')
        summary['observations'] += 1
    except errors.ApiError as exc:
        out['error'] = exc.message
        summary['failed'] += 1
    return out
