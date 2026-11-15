"""core/tasks.py — 异步任务

只有一类任务真的会跑起来：preprocess。它被拆成多条线程（每请求一线程的服务里，
后台任务必须是独立线程），状态机写库，前端按 GET /api/tasks/{id} 轮询：

  queued → running → succeeded
                   ↘ failed
  任何阶段可 → canceled

进度落在 ai_tasks.progress（0–1）与 stage（当前阶段键），前端据此画六个方框。
"""
import threading
import traceback

import db
import util

from . import pipeline

_running = set()
_lock = threading.Lock()


def _task_row(task_id):
    row = db.q1('SELECT * FROM ai_tasks WHERE id = ?', (task_id,))
    if not row:
        return None
    row['result'] = util.loads(row.get('result_json'), {})
    row.pop('result_json', None)
    return row


def as_dict(task_id):
    row = _task_row(task_id)
    if not row:
        return None
    res = row.get('result') or {}
    return {
        'id': row['id'],
        'session_id': row['session_id'],
        'kind': row['kind'],
        'status': row['status'],
        'progress': round(row['progress'] or 0, 2),
        'stage': row['stage'],
        'error': row['error'],
        'started_at': row['started_at'],
        'finished_at': row['finished_at'],
        'stages': res.get('stages', []),
        # 与 list_tasks 保持同形：前端只写一套渲染逻辑
        'gate_overall': res.get('gate_overall'),
        'assets': res.get('assets') or {'items': [], 'total_bytes': 0},
    }


def active_task(session_id, kind='preprocess'):
    row = db.q1("""SELECT * FROM ai_tasks WHERE session_id = ? AND kind = ?
                   AND status IN ('queued','running')
                   AND result_json NOT LIKE '%"seeded":true%'
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, kind))
    return row


def start_preprocess(session_id, session, media, stages=None, model_metrics=None):
    """建任务 + 起线程。并发冲突由调用方（M3）先查 active_task 抛 TASK_CONFLICT。"""
    task_id = util.new_id('T')
    now = util.iso()
    db.x("""INSERT INTO ai_tasks (id, session_id, kind, status, progress, stage, error,
                                 result_json, started_at, finished_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
         (task_id, session_id, 'preprocess', 'queued', 0, 'queued', None, '{}', None, None, now))
    db.x("UPDATE sessions SET status = 'processing', stage = 'preprocess' WHERE id = ?", (session_id,))

    def worker():
        with _lock:
            _running.add(task_id)
        db.x("UPDATE ai_tasks SET status='running', started_at=?, stage='probe' WHERE id=?",
             (util.iso(), task_id))

        def on_progress(frac, stage):
            db.x('UPDATE ai_tasks SET progress=?, stage=? WHERE id=?',
                 (max(0.02, min(0.99, frac)), stage, task_id))

        try:
            result = pipeline.run(session_id, session, media, stages, on_progress,
                                  model_metrics=model_metrics)
            result['finished_at'] = util.iso()
            db.x("""UPDATE ai_tasks SET status='succeeded', progress=1, stage='gate',
                    result_json=?, finished_at=? WHERE id=?""",
                 (util.dumps(result), result['finished_at'], task_id))
            db.x("UPDATE sessions SET stage='gate' WHERE id=?", (session_id,))
            db.audit('preprocess.succeeded', session_id, 'system',
                     {'task_id': task_id, 'gate': result.get('gate_overall')})
        except Exception as exc:
            err = '%s: %s' % (type(exc).__name__, exc)
            db.x("UPDATE ai_tasks SET status='failed', error=?, finished_at=? WHERE id=?",
                 (err, util.iso(), task_id))
            db.x("UPDATE sessions SET status='created', stage='created' WHERE id=?", (session_id,))
            db.audit('preprocess.failed', session_id, 'system', {'task_id': task_id, 'error': err})
            traceback.print_exc()
        finally:
            with _lock:
                _running.discard(task_id)

    t = threading.Thread(target=worker, name='preprocess-%s' % task_id, daemon=True)
    t.start()
    return task_id


def latest_succeeded(session_id, kind='preprocess'):
    row = db.q1("""SELECT * FROM ai_tasks WHERE session_id = ? AND kind = ? AND status='succeeded'
                   ORDER BY finished_at DESC LIMIT 1""", (session_id, kind))
    if not row:
        return None
    row['result'] = util.loads(row.get('result_json'), {})
    return row


def seed_succeeded(session_id, result, started_at=None, finished_at=None):
    """演示数据用：把一条"已经跑完的流水线"写进库，让界面不必等真实任务。"""
    task_id = util.new_id('T')
    db.x("""INSERT INTO ai_tasks (id, session_id, kind, status, progress, stage, error,
                                 result_json, started_at, finished_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
         (task_id, session_id, 'preprocess', 'succeeded', 1, 'gate', None,
          util.dumps(result), started_at or util.iso(), finished_at or util.iso(),
          started_at or util.iso()))
    return task_id
