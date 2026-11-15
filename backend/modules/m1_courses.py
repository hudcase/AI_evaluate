"""modules/m1_courses.py — M1 建档

两条硬规则，写在代码里而不是只写在文档里：
  1. 课程至少要有一条**核心**目标。A2 加权目标覆盖的分母就是核心目标权重和，
     没有核心目标，这个指标在数学上不成立，所以建档时就拒绝。
  2. 场次必须确认知情同意。未确认直接 400 CONSENT_REQUIRED，不入库——
     这是流程约束，不是选项。
"""
import os
import shutil

import config
import db
import errors
import util

from . import _common

TIERS = ('core', 'support', 'extend')
SCENARIOS = ('theory', 'seminar', 'practical')


def _next_id(prefix, table, day):
    """按当日已有编号的最大值 +1，而不是按行数——行数在删过一条之后会重号。"""
    like = '%s-%s-%%' % (prefix, day)
    rows = db.q('SELECT id FROM %s WHERE id LIKE ?' % table, (like,))
    mx = 0
    for r in rows:
        try:
            mx = max(mx, int(str(r['id']).rsplit('-', 1)[1]))
        except (ValueError, IndexError):
            continue
    return '%s-%s-%02d' % (prefix, day, mx + 1)


def _clean_goals(goals):
    if not isinstance(goals, list) or not goals:
        errors.fail('VALIDATION_FAILED', '至少填写 1 条课程目标', 'goals')
    if len(goals) > 30:
        errors.fail('VALIDATION_FAILED', '课程目标不得超过 30 条', 'goals')
    out = []
    for i, g in enumerate(goals):
        if not isinstance(g, dict):
            errors.fail('VALIDATION_FAILED', '目标必须是对象', 'goals[%d]' % i)
        text = (g.get('text') or '').strip()
        tier = g.get('tier') or 'core'
        if not text:
            errors.fail('VALIDATION_FAILED', '目标文本不能为空', 'goals[%d].text' % i)
        if len(text) > 200:
            errors.fail('VALIDATION_FAILED', '目标文本不得超过 200 字符', 'goals[%d].text' % i)
        if tier not in TIERS:
            errors.fail('VALIDATION_FAILED', 'tier 需为 core／support／extend', 'goals[%d].tier' % i)
        out.append({'text': text, 'tier': tier})
    if not any(g['tier'] == 'core' for g in out):
        errors.fail('VALIDATION_FAILED', '至少标记 1 条核心目标，A2 覆盖率以其权重和为分母', 'goals')
    return out


def list_courses(page=1, size=20, q=None):
    rows = db.q('SELECT * FROM courses ORDER BY created_at DESC')
    items = [_common.course_public(r) for r in rows]
    if q:
        kw = str(q).strip()
        items = [c for c in items if kw in c['title'] or kw in c['id']]
    return util.paginate(items, page, size)


def get_course(cid):
    row = db.q1('SELECT * FROM courses WHERE id = ?', (cid,))
    if not row:
        errors.not_found('课程', cid)
    sessions = db.q('SELECT * FROM sessions WHERE course_id = ? ORDER BY date DESC, start DESC', (cid,))
    briefs = [{
        'id': s['id'], 'title': s['title'], 'scenario': s['scenario'],
        'date': s['date'], 'start': s['start'], 'status': s['status'],
        'stage': s['stage'], 'created_at': s['created_at'],
        'consent_confirmed': bool(s['consent_confirmed']),
    } for s in sessions]
    return _common.course_public(row, briefs)


def create_course(body):
    title = (body.get('title') or '').strip()
    if not title or len(title) > 100:
        errors.fail('VALIDATION_FAILED', '课程标题需为 1–100 字符', 'title')
    goals = _clean_goals(body.get('goals'))

    students = body.get('expected_students', 0)
    try:
        students = int(students or 0)
    except (TypeError, ValueError):
        errors.fail('VALIDATION_FAILED', 'expected_students 需为整数', 'expected_students')
    if students and not (1 <= students <= 10000):
        errors.fail('VALIDATION_FAILED', 'expected_students 需在 1–10000', 'expected_students')

    cid = _next_id('C', 'courses', util.today())
    db.x('INSERT INTO courses (id, title, expected_students, goals_json, created_at) VALUES (?,?,?,?,?)',
         (cid, title, students, util.dumps(goals), util.iso()))
    db.audit('course.create', cid, 'admin', {'title': title, 'goals': len(goals)})
    return {'id': cid}


def list_sessions(course_id=None, page=1, size=20):
    if course_id:
        rows = db.q('SELECT * FROM sessions WHERE course_id = ? ORDER BY date DESC', (course_id,))
    else:
        rows = db.q('SELECT * FROM sessions ORDER BY date DESC, start DESC')
    items = []
    for r in rows:
        c = db.q1('SELECT * FROM courses WHERE id = ?', (r['course_id'],)) or {}
        items.append(_common.session_public(r, c))
    return util.paginate(items, page, size)


def get_session(sid):
    s = _common.load_session(sid)
    if not s:
        errors.not_found('场次', sid)
    out = _common.session_public(s, s.get('course_row'))
    out['goals'] = s['goals']
    out['course_title'] = s.get('course_title')
    res, task = _common.task_result(sid)
    out['gate_overall'] = res.get('gate_overall')
    out['gate_task'] = (task or {}).get('id')
    return out


def delete_course(cid, confirm=False):
    """删除课程及其全部派生数据。

    数据库 9 张表都开着 foreign_keys=ON，但 schema 里只有部分表声明了 REFERENCES，
    而且没有 ON DELETE CASCADE——所以这里显式按「子表 → 父表」顺序删，一条都不漏：

      observations → evaluations → ai_calls → ai_tasks → media_assets → sessions → courses

    媒资文件在物理盘上的原档/派生目录一并删；audit 保留（留痕本身就是审计目的，
    删课这个动作也要进审计，所以 audit 表反向留）。课程删除不可逆，必须带 confirm。
    """
    if str(confirm).lower() not in ('true', '1', 'yes'):
        errors.fail('VALIDATION_FAILED', '删除课程需带 confirm=true', 'confirm')

    course = db.q1('SELECT * FROM courses WHERE id = ?', (cid,))
    if not course:
        errors.not_found('课程', cid)

    sessions = db.q('SELECT id FROM sessions WHERE course_id = ?', (cid,))
    sids = [s['id'] for s in sessions]

    with db.tx():
        for sid in sids:
            db.x('DELETE FROM observations WHERE session_id = ?', (sid,))
            db.x('DELETE FROM evaluations WHERE session_id = ?', (sid,))
            db.x('DELETE FROM ai_calls WHERE session_id = ?', (sid,))
            db.x('DELETE FROM ai_tasks WHERE session_id = ?', (sid,))
            # 媒资：先删物理文件，再删表行
            assets = db.q('SELECT * FROM media_assets WHERE session_id = ?', (sid,))
            for a in assets:
                p = a.get('path')
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            db.x('DELETE FROM media_assets WHERE session_id = ?', (sid,))
            db.x('DELETE FROM sessions WHERE id = ?', (sid,))
        db.x('DELETE FROM courses WHERE id = ?', (cid,))

    # 派生目录整块清掉（与媒资软删的 derived 目录同一处）
    for sid in sids:
        d = os.path.join(config.MEDIA_DIR, sid)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    db.audit('course.delete', cid, 'admin',
             {'title': course['title'], 'sessions': len(sids)})
    return {'id': cid, 'deleted_sessions': len(sids)}


def create_session(body):
    course_id = body.get('course_id')
    course = db.q1('SELECT * FROM courses WHERE id = ?', (course_id,))
    if not course:
        errors.not_found('课程', course_id)

    if body.get('consent_confirmed') is not True:
        errors.fail('CONSENT_REQUIRED', '未确认知情同意，场次不得入库', 'consent_confirmed')

    scenario = body.get('scenario')
    if scenario not in SCENARIOS:
        errors.fail('VALIDATION_FAILED', '课型需为 theory／seminar／practical', 'scenario')

    title = (body.get('title') or '').strip()
    if not title or len(title) > 100:
        errors.fail('VALIDATION_FAILED', '场次标题需为 1–100 字符', 'title')

    try:
        duration = int(body.get('duration_min') or 90)
    except (TypeError, ValueError):
        errors.fail('VALIDATION_FAILED', 'duration_min 需为整数', 'duration_min')
    if not (20 <= duration <= 480):
        errors.fail('VALIDATION_FAILED', '时长需在 20–480 分钟', 'duration_min')

    students = body.get('expected_students', course['expected_students']) or course['expected_students']
    try:
        students = int(students)
    except (TypeError, ValueError):
        students = 0

    sid = _next_id('S', 'sessions', util.today())
    db.x("""INSERT INTO sessions (id, course_id, title, scenario, consent_confirmed, teacher, room,
                                  date, start, duration_min, students, status, stage, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (sid, course_id, title, scenario, 1, body.get('teacher'), body.get('room'),
          body.get('date') or util.now().strftime('%Y-%m-%d'),
          body.get('start') or '00:00', duration, students, 'created', 'created', util.iso()))
    db.audit('session.create', sid, 'admin', {'course_id': course_id, 'scenario': scenario})
    return {'id': sid, 'status': 'created'}
