"""modules/m5_indicators.py — M5 指标计算

这里是"客户端不得自行给分"的落点：POST /observations 只收 raw_value 与证据字段，
分项分由服务端按 indicator_config 的量尺算出。空值同样是合法输入——空值代表"没测到"，
它会进 missing 列表并压低覆盖率，而不是变成 0 分。

补录受门禁约束：门禁 reject 的指标不允许直接补录（409 GATE_NOT_PASSED），
否则等于绕开"数据不够格"这件事给分。
"""
import db
import errors
import util

from core import gates as gates_mod
from core import membership

from . import _common

TRACKS = ('audio', 'video', 'slides', 'goals')
MULTI_TRACK = ('VA5', 'VC1', 'VB3')


def get_indicators():
    return _common.indicators_public()


def put_indicators(body):
    version = (body.get('config_version') or '').strip()
    if not version or len(version) > 32:
        errors.fail('VALIDATION_FAILED', 'config_version 必填且不超过 32 字符', 'config_version')
    items = body.get('items')
    if not isinstance(items, list) or not items:
        errors.fail('VALIDATION_FAILED', 'items 需为非空数组', 'items')

    cur = db.config_items()
    if version == cur['config_version']:
        errors.fail('VALIDATION_FAILED', '新版本号不能与当前版本相同（配置不覆盖，只追加）', 'config_version')

    base = {r['code']: r for r in cur['items']}
    patch = {}
    for i, it in enumerate(items):
        code = it.get('code')
        if code not in base:
            errors.fail('VALIDATION_FAILED', '未知指标 %s' % code, 'items[%d].code' % i)
        patch[code] = it

    changed = 0
    now = util.iso()
    rows = []
    for code, r in base.items():
        p = patch.get(code, {})
        fields = {
            'name': p.get('name', r['name']),
            'tier': r['tier'], 'domain': r['domain'],
            'domain_name': r['domain_name'], 'domain_weight': r['domain_weight'],
            'weight': p.get('weight', r['weight']),
            'direction': p.get('direction', r['direction']),
            'a': p.get('a', r['a']), 'b': p.get('b', r['b']),
            'c': p.get('c', r['c']), 'd': p.get('d', r['d']),
            'unit': p.get('unit', r['unit']),
            'denominator_rule': p.get('denominator_rule', r['denominator_rule']),
            'scored': 1 if p.get('scored', r['scored']) else 0,
        }
        if fields['direction'] == 'interval' and None in (fields['a'], fields['b'], fields['c'], fields['d']):
            errors.fail('VALIDATION_FAILED', '%s 为区间型，a／b／c／d 四个参数都必填' % code,
                        'items[%s]' % code)
        if code in patch:
            changed += 1
        rows.append((version, code, fields['name'], fields['tier'], fields['domain'],
                     fields['domain_name'], fields['domain_weight'], fields['weight'],
                     fields['direction'], fields['a'], fields['b'], fields['c'], fields['d'],
                     fields['unit'], fields['denominator_rule'], fields['scored'], now))

    with db.tx():
        db.xmany("""INSERT OR REPLACE INTO indicator_config
                    (config_version, code, name, tier, domain, domain_name, domain_weight,
                     weight, direction, a, b, c, d, unit, denominator_rule, scored, published_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        db.x("UPDATE indicator_config SET published_at=? WHERE config_version=?", (now, version))
    db.audit('config.publish', version, 'admin', {'changed': changed})
    return {'config_version': version, 'changed': changed,
            'note': '新版本已发布；已出评价不会自动重算，需对场次调用 POST /score 复算'}


def get_observations(sid):
    _common.require_session(sid)
    return {'items': _common.observations(sid), 'config_version': db.current_config_version()}


def _bounds(ind):
    """量纲合理区间。只用于挡住明显输错的量级（如把 0.68 填成 68 或 178 填成 1.78），
    不做业务判断——业务判断交给量尺本身。"""
    unit = ind['unit'] or ''
    direction = ind['direction']
    if unit in ('ratio', '0–1', '得分率'):
        return 0.0, 1.0
    if direction == 'interval' and ind['d']:
        return 0.0, float(ind['d']) * 2
    if direction in ('inc', 'reverse'):
        b = ind['b'] or 1
        return 0.0, max(1.0, float(b) * 4)
    return 0.0, 1e6


def _coverage(sid, tier, config_version=None):
    items = [o for o in _common.observations(sid, config_version) if o['tier'] == tier and o['scored']]
    w = sum(o['weight'] for o in items if o['score'] is not None)
    return round(w, 3)


def post_observation(sid, body):
    session = _common.require_session(sid)
    code = body.get('code')
    ind = db.find_indicator(code) if code else None
    if not ind:
        errors.fail('VALIDATION_FAILED', '未知指标 %s' % code, 'code')
    if not ind['scored']:
        errors.fail('VALIDATION_FAILED', '%s 不计分（门禁／列示项），不需要观测值' % code, 'code')

    # 门禁阻断检查
    res, _ = _common.task_result(sid)
    blocked = gates_mod.blocked_codes(res.get('gates') or [])
    if code in blocked:
        raise errors.ApiError('GATE_NOT_PASSED', blocked[code], code)

    note = (body.get('evidence_note') or '').strip()
    if len(note) > 120:
        errors.fail('VALIDATION_FAILED', 'evidence_note 不得超过 120 字符', 'evidence_note')
    if util.has_pii(note):
        errors.fail('PII_DETECTED', 'evidence_note 含手机号／身份证／邮箱等直接标识', 'evidence_note')

    raw = body.get('raw_value', None)
    if raw is not None:
        try:
            raw = float(raw)
        except (TypeError, ValueError):
            errors.fail('VALIDATION_FAILED', 'raw_value 需为数值或 null', 'raw_value')
        lo, hi = _bounds(ind)
        if not (lo <= raw <= hi):
            errors.fail('VALIDATION_FAILED',
                        '%s 的 raw_value 应在 %.4g–%.4g 之间（单位 %s）' % (code, lo, hi, ind['unit']),
                        'raw_value')

    conf = body.get('confidence')
    if conf is not None:
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            errors.fail('VALIDATION_FAILED', 'confidence 需为 0–1', 'confidence')
        if not (0 <= conf <= 1):
            errors.fail('VALIDATION_FAILED', 'confidence 需为 0–1', 'confidence')

    tracks = body.get('source_track') or []
    if not isinstance(tracks, list):
        errors.fail('VALIDATION_FAILED', 'source_track 需为数组', 'source_track')
    bad = [t for t in tracks if t not in TRACKS]
    if bad:
        errors.fail('VALIDATION_FAILED', 'source_track 取值需在 %s 内' % '／'.join(TRACKS), 'source_track')
    if code in MULTI_TRACK and raw is not None and len(set(tracks)) < 2:
        errors.fail('VALIDATION_FAILED', '%s 必须由 ≥2 路证据支撑（如 audio＋slides）' % code,
                    'source_track')

    score = membership.score(ind, raw) if raw is not None else None
    empty = body.get('empty_reason')
    if raw is None and not empty:
        empty = '补录时标记为空值：未取得可用观测'

    oid = util.new_id('O')
    now = util.iso()
    with db.tx():
        row = db.q1('SELECT * FROM observations WHERE session_id=? AND code=?', (sid, code))
        if row:
            db.x("""UPDATE observations SET raw_value=?, denominator=?, unit=?, confidence=?, evidence_t=?,
                    source_track_json=?, note=?, empty_reason=?, model_version=?, score=?, updated_at=?
                    WHERE id=?""",
                 (raw, body.get('denominator'), ind['unit'] or body.get('unit'), conf,
                  body.get('evidence_t'), util.dumps(tracks), note, empty if raw is None else None,
                  body.get('model_version'), score, now, row['id']))
            oid = row['id']
        else:
            db.x("""INSERT INTO observations (id, session_id, code, raw_value, denominator, unit, confidence,
                    evidence_t, source_track_json, note, empty_reason, model_version, score, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (oid, sid, code, raw, body.get('denominator'), ind['unit'] or body.get('unit'), conf,
                  body.get('evidence_t'), util.dumps(tracks), note, empty if raw is None else None,
                  body.get('model_version'), score, now, now))
    db.audit('observation.write', sid, 'admin', {'code': code, 'raw': raw, 'score': score})

    return {
        'id': oid, 'code': code, 'score': score, 'confidence': conf,
        'coverage_after': _coverage(sid, ind['tier']),
        'band': membership.band(ind, raw),
    }


def rescore(sid, body=None):
    body = body or {}
    session = _common.require_session(sid)
    cfg = db.config_items(body.get('config_version'))
    ind_of = {r['code']: r for r in cfg['items']}

    rows = db.q('SELECT * FROM observations WHERE session_id = ?', (sid,))
    if not rows:
        errors.fail('STATE_CONFLICT', '该场次尚无观测值，无法复算', 'observations')

    scored = empty = 0
    now = util.iso()
    with db.tx():
        for r in rows:
            ind = ind_of.get(r['code'])
            if not ind:
                continue
            s = membership.score(ind, r['raw_value']) if r['raw_value'] is not None else None
            db.x('UPDATE observations SET score=?, unit=?, updated_at=? WHERE id=?',
                 (s, r['unit'] or ind['unit'], now, r['id']))
            if s is None:
                empty += 1
            else:
                scored += 1
    db.audit('evaluation.rescore', sid, 'admin',
             {'config_version': cfg['config_version'], 'scored': scored, 'empty': empty})
    return {
        'scored': scored, 'empty': empty,
        'audio_coverage': _coverage(sid, 'audio', cfg['config_version']),
        'video_coverage': _coverage(sid, 'video', cfg['config_version']),
        'config_version': cfg['config_version'],
    }
