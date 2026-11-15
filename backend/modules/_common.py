"""modules/_common.py — 序列化与共用查询

表行 → 对外 JSON 的**唯一**转换处。所有模块都从这里取，避免同一字段在不同接口里
出现两种形状（前端是按形状写死的，形状一变页面就空）。
"""
import db
import util


# ---------------------------------------------------------------- 课程／场次

def course_public(row, sessions=None):
    out = {
        'id': row['id'],
        'title': row['title'],
        'expected_students': row['expected_students'],
        'created_at': row['created_at'],
        'goals': util.loads(row.get('goals_json'), []),
    }
    if sessions is not None:
        out['sessions'] = sessions
    return out


def session_public(row, course=None):
    return {
        'id': row['id'],
        'course_id': row['course_id'],
        'course': (course or {}).get('title'),
        'title': row['title'],
        'scenario': row['scenario'],
        'consent_confirmed': bool(row['consent_confirmed']),
        'teacher': row['teacher'],
        'room': row['room'],
        'date': row['date'],
        'start': row['start'],
        'duration_min': row['duration_min'],
        'students': row['students'],
        'status': row['status'],
        'stage': row['stage'],
        'created_at': row['created_at'],
        'goals': util.loads((course or {}).get('goals_json'), []),
    }


def session_row(session_id):
    row = db.q1('SELECT * FROM sessions WHERE id = ?', (session_id,))
    return row


def load_session(session_id):
    """取场次 + 所属课程（门禁与计分都要用课程目标）"""
    s = db.q1('SELECT * FROM sessions WHERE id = ?', (session_id,))
    if not s:
        return None
    c = db.q1('SELECT * FROM courses WHERE id = ?', (s['course_id'],))
    s['goals'] = util.loads((c or {}).get('goals_json'), [])
    s['course_title'] = (c or {}).get('title')
    s['course_row'] = c
    return s


def require_session(session_id):
    s = load_session(session_id)
    if not s:
        import errors
        errors.not_found('场次', session_id)
    return s


# ---------------------------------------------------------------- 媒资

def media_public(row):
    return {
        'id': row['id'],
        'type': row['type'],
        'slot': row['slot'],
        'name': row['name'],
        'bytes': row['bytes'],
        'sha256': row['sha256'],
        'duration_s': row['duration_s'],
        'probe': util.loads(row.get('probe_json'), {}),
        'retention_days': row['retention_days'],
        'status': row['status'],
        'created_at': row['created_at'],
        'stored': bool(row.get('path')),
    }


def media_rows(session_id):
    return db.q('SELECT * FROM media_assets WHERE session_id = ? AND deleted_at IS NULL ORDER BY created_at',
                (session_id,))


# ---------------------------------------------------------------- 观测

DEFAULT_EMPTY = {
    'gate': '未检出候选事件，门禁通过',
    'listed': '列示项：本项目不设当堂测验，无数据来源',
}


def observations(session_id, config_version=None):
    """21 条指标的完整记录：配置左连接观测，缺行不是"没这条"，而是"没测到"。"""
    cfg = db.config_items(config_version)
    rows = {r['code']: r for r in db.q('SELECT * FROM observations WHERE session_id = ?', (session_id,))}
    out = []
    for ind in cfg['items']:
        o = rows.get(ind['code']) or {}
        raw = o.get('raw_value')
        empty = o.get('empty_reason')
        if raw is None and not empty:
            if ind['direction'] == 'gate':
                empty = DEFAULT_EMPTY['gate']
            elif ind['direction'] == 'listed':
                empty = DEFAULT_EMPTY['listed']
            else:
                empty = '未采集：该指标尚无模型观测值'
        out.append({
            'code': ind['code'],
            'name': ind['name'],
            'tier': ind['tier'],
            'domain': ind['domain'],
            'weight': ind['weight'],
            'raw_value': raw,
            'denominator': (o.get('denominator') if o else None) or _denominator_hint(ind),
            'unit': o.get('unit') or ind['unit'],
            'score': o.get('score'),
            'confidence': o.get('confidence'),
            'evidence_t': o.get('evidence_t'),
            'source_track': util.loads(o.get('source_track_json'), []),
            'note': o.get('note'),
            'empty_reason': empty if raw is None else None,
            'scored': ind['scored'],
            'direction': ind['direction'],
            'a': ind['a'], 'b': ind['b'], 'c': ind['c'], 'd': ind['d'],
        })
    return out


def _denominator_hint(ind):
    """分母口径是文字规则（如"核心目标权重和"），不是数值。
    观测里没填就取指标配置中的规则——否则这一列会整列为空。"""
    return ind['denominator_rule'] or None


def obs_map(session_id, config_version=None):
    return {o['code']: o for o in observations(session_id, config_version)}


# ---------------------------------------------------------------- 任务

def task_result(session_id, kind='preprocess'):
    """最近一次成功任务的产物：门禁、派生资产、模型质量指标都在里面"""
    import core.tasks as tasks
    row = tasks.latest_succeeded(session_id, kind)
    return (row or {}).get('result') or {}, row


def gates_of(session_id):
    res, row = task_result(session_id)
    return res.get('gates') or [], res


def assets_of(session_id):
    res, _row = task_result(session_id)
    return res.get('assets') or {'items': [], 'total_bytes': 0}


# ---------------------------------------------------------------- 指标配置

def indicators_public():
    cfg = db.config_items()
    items = []
    for r in cfg['items']:
        items.append({
            'code': r['code'], 'name': r['name'], 'tier': r['tier'],
            'domain': r['domain'], 'domain_name': r['domain_name'],
            'domain_weight': r['domain_weight'], 'weight': r['weight'],
            'direction': r['direction'], 'a': r['a'], 'b': r['b'], 'c': r['c'], 'd': r['d'],
            'unit': r['unit'], 'denominator_rule': r['denominator_rule'],
            'scored': r['scored'],
        })
    published = db.scalar('SELECT published_at FROM indicator_config WHERE config_version = ? LIMIT 1',
                          (cfg['config_version'],))
    return {'config_version': cfg['config_version'], 'published_at': published, 'items': items}
