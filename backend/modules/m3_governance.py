"""modules/m3_governance.py — M3 数据治理

流水线是异步的：POST /preprocess 建任务立刻返回 202，前端轮询 GET /api/tasks/{id}。
同一场次同时只允许一个 preprocessing 任务（TASK_CONFLICT），否则两次转码会互相覆盖派生资产。

门禁（qc）**不依赖**流水线是否跑过：没跑过时按现有证据现算一遍，缺证据的项显示"未测"，
这样"能不能计分"这个判断在接入阶段就能回答，而不是等到算完分才发现数据不够。
"""
import db
import errors
import util

from core import gates as gates_mod
from core import pipeline
from core import tasks

from . import _common

VALID_STAGES = [k for k, _ in pipeline.STAGE_ORDER]


def preprocess(sid, body):
    session = _common.require_session(sid)
    # 流水线要读文件，必须给原始行（含 path）；media_public 是给前端的脱敏视图，没有 path，
    # 拿它跑流水线会让每一阶段都判"未落盘"——转码抽帧永远不发生。
    media = _common.media_rows(sid)
    if not media:
        errors.fail('VALIDATION_FAILED', '该场次尚无媒资，先接入再预处理', 'media')

    running = tasks.active_task(sid, 'preprocess')
    if running:
        raise errors.ApiError('TASK_CONFLICT',
                              '该场次已有运行中的预处理任务 %s（%s）' % (running['id'], running['status']))

    stages = body.get('stages')
    if stages is not None:
        if not isinstance(stages, list) or not stages:
            errors.fail('VALIDATION_FAILED', 'stages 需为非空数组', 'stages')
        bad = [s for s in stages if s not in VALID_STAGES]
        if bad:
            errors.fail('VALIDATION_FAILED', '未知阶段 %s，可用：%s' % ('、'.join(bad), '、'.join(VALID_STAGES)),
                        'stages')

    task_id = tasks.start_preprocess(sid, session, media, stages,
                                     model_metrics=body.get('model_metrics'))
    return {'task_id': task_id, 'status': 'queued', 'stages': stages or 'all'}


def get_task(task_id):
    t = tasks.as_dict(task_id)
    if not t:
        errors.not_found('任务', task_id)
    return t


def list_tasks(sid, kind='preprocess', limit=20):
    _common.require_session(sid)
    rows = db.q("""SELECT * FROM ai_tasks WHERE session_id = ? AND kind = ?
                   ORDER BY created_at DESC LIMIT ?""", (sid, kind, int(limit)))
    items = []
    for r in rows:
        res = util.loads(r.get('result_json'), {})
        items.append({
            'id': r['id'], 'session_id': r['session_id'], 'kind': r['kind'], 'status': r['status'],
            'progress': round(r['progress'] or 0, 2), 'stage': r['stage'], 'error': r['error'],
            'started_at': r['started_at'], 'finished_at': r['finished_at'],
            # 阶段明细带上：前端据此区分"真做了"与"本机做不了"
            'stages': res.get('stages', []),
            'gate_overall': res.get('gate_overall'),
        })
    return {'items': items}


def get_qc(sid):
    session = _common.require_session(sid)
    media = _common.media_rows(sid)
    res, _task = _common.task_result(sid)

    if res.get('gates'):
        gates = res['gates']
    else:
        derived = {'frames': res.get('frames') or 0}
        _overall, gates = gates_mod.compute(session, media, res.get('model_metrics') or {}, derived)

    overall = 'pass'
    if any(g['status'] == 'reject' for g in gates):
        overall = 'reject'
    elif any(g['status'] == 'warn' for g in gates):
        overall = 'warn'
    return {'overall': overall, 'gates': gates,
            'task_id': (res.get('task_id') or None),
            'computed_from': 'pipeline' if res.get('gates') else 'live'}


def get_assets(sid):
    _common.require_session(sid)
    res, _task = _common.task_result(sid)
    assets = res.get('assets')
    if not assets:
        assets = pipeline.collect_assets(sid)
    total = assets.get('total_bytes') or 0
    return {
        'items': assets.get('items', []),
        'total_bytes': total,
        'stages': res.get('stages', []),
    }
