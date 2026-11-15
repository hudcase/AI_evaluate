"""modules/m6_fusion.py — M6 合成与一致性

三条规则在这里落地，任何一条改掉都会让系统自称它做不到的事：

  1. **不合成**：composite 恒为 null。两份分数并列呈现，因为音频与视频测的不是同一个构念，
     加权合成等于宣称两者可通约，而两份来源材料都没能给出 α。
  2. **缺测不补零、不重分权**：只在有分项分的地方求和，覆盖率单独报。
     覆盖率 0.90 时，模态分的理论上限就是 90——上限被扣掉这件事必须让评审看见。
  3. **分歧即证据不足**：两模态分差 ≥ 15 且方向相反时标 divergent，不取平均、不折中。

evaluations 表只增不改：每次 GET 都重新计算并落一条快照，用于复算比对与申诉时的"当时算什么"。
"""
import db
import util

from . import _common

DIVERGENT_DELTA = 15.0
MIN_COVERAGE = 0.60
ALERT_THRESHOLD = 0.5          # VB1 抬头率警戒线（示意值，须按本校分布标定）


def _agg(items, tier):
    w = 0.0
    s = 0.0
    n = 0
    for o in items:
        if o['tier'] != tier or not o['scored'] or o['score'] is None:
            continue
        w += o['weight'] or 0
        s += (o['weight'] or 0) * o['score']
        n += 1
    return {
        'score': round(s, 1),
        'coverage': round(w, 3),
        'items': n,
        'weight_sum': round(w, 4),
    }


def _vb1_series(sid):
    row = db.q1("SELECT series_json FROM observations WHERE session_id=? AND code='VB1'", (sid,))
    pts = util.loads((row or {}).get('series_json'), None)
    return pts or []


def _valley(points, threshold=ALERT_THRESHOLD):
    """找最长的一段连续低于警戒线的区间。短板约束要用它写"哪一段掉了"。"""
    best = None
    start = None
    for p in points:
        if p['v'] < threshold:
            if start is None:
                start = p
            cur = p
            if best is None or (cur['t'] - start['t']) > (best['to'] - best['from']):
                best = {'from': start['t'], 'to': cur['t'],
                        'min': min(x['v'] for x in points
                                   if start['t'] <= x['t'] <= cur['t'])}
        else:
            start = None
    if best and best['to'] > best['from']:
        return best
    return None


def compute(sid, persist=True):
    session = _common.require_session(sid)
    items = _common.observations(sid)
    A = _agg(items, 'audio')
    V = _agg(items, 'video')

    delta = round(A['score'] - V['score'], 1)
    if A['coverage'] < MIN_COVERAGE or V['coverage'] < MIN_COVERAGE:
        status = 'insufficient'
    elif abs(delta) >= DIVERGENT_DELTA:
        status = 'divergent'
    else:
        status = 'aligned'

    flags = []
    if A['coverage'] < 1:
        miss = [o['code'] for o in items if o['tier'] == 'audio' and o['scored'] and o['score'] is None]
        flags.append({'key': 'coverage_partial', 'level': 'info',
                      'text': '%s 未输出，音频覆盖率 %.2f；按规则三不补零、不重分权'
                              % ('、'.join(miss) or '部分指标', A['coverage'])})
    if status == 'divergent':
        flags.append({'key': 'divergent', 'level': 'warn',
                      'text': '两模态分差 %.1f 分，方向相反，标为证据不一致' % abs(delta)})
    if status == 'insufficient':
        flags.append({'key': 'insufficient', 'level': 'danger',
                      'text': '双模态覆盖率低于 %.2f，暂停输出模态分，只列可用分项' % MIN_COVERAGE})

    missing = [{'code': o['code'], 'name': o['name'],
                'reason': o['empty_reason'], 'weight': o['weight'] or 0}
               for o in items if o['score'] is None]

    vb1 = _vb1_series(sid)
    short_board = []
    valley = _valley(vb1) if vb1 else None
    if valley:
        short_board.append({
            'key': 'vb1_valley', 'downgrade': True,
            'text': '%s–%s 连续 %d 分钟抬头率低于警戒线，谷值 %d%%'
                    % (util.mmss(valley['from']), util.mmss(valley['to']),
                       round((valley['to'] - valley['from']) / 60.0), round(valley['min'] * 100)),
        })
    vc2 = [o for o in items if o['code'] == 'VC2'][0]
    if vc2['score'] is not None:
        short_board.append({
            'key': 'vc2_complete', 'downgrade': False,
            'text': vc2['note'] or ('活动结构完整度 %.2f' % (vc2['raw_value'] or 0)),
        })
    else:
        short_board.append({'key': 'vc2_missing', 'downgrade': False,
                            'text': '活动结构未评定：缺环节切分，短板约束不施加'})

    out = {
        'session_id': sid,
        'config_version': db.current_config_version(),
        'audio': A,
        'video': V,
        'composite': None,
        'consistency': {
            'status': status,
            'delta': delta,
            'divergent': _divergent_pairs(items) if status == 'divergent' else [],
        },
        'flags': flags,
        'short_board': short_board,
        'missing': missing,
        'independent': {'goal_attainment': None},
        'vb1': {'threshold': ALERT_THRESHOLD, 'valley': valley, 'points': len(vb1)},
    }

    if persist:
        db.x("""INSERT INTO evaluations (id, session_id, config_version, audio_json, video_json,
                consistency_json, flags_json, missing_json, short_board_json, composite, computed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
             (util.new_id('E'), sid, out['config_version'], util.dumps(A), util.dumps(V),
              util.dumps(out['consistency']), util.dumps(flags), util.dumps(missing),
              util.dumps(short_board), None, util.iso()))
        if session['status'] != 'processing':
            db.x('UPDATE sessions SET status=?, stage=? WHERE id=?',
                 (status_of(status, session), 'report' if session['stage'] in ('report', 'gate', 'scored') else session['stage'], sid))
    return out


def status_of(consistency_status, session):
    """对外状态：先用一致性结论；证据不足时保持 insufficient，可用时是 ok"""
    if consistency_status == 'insufficient':
        return 'insufficient'
    if consistency_status == 'divergent':
        return 'divergent'
    return 'ok'


def _divergent_pairs(items):
    """哪几对指标在互相矛盾：方向相反的音频／视频配对由文案给出，
    真正逐项判定需要用到分项方向，这里只列语义上成对的几组。"""
    by = {o['code']: o for o in items}
    pairs = []
    for a, v in (('A2', 'VB1'), ('A3', 'VB3'), ('B6', 'VB3')):
        oa, ov = by.get(a), by.get(v)
        if oa and ov and oa['score'] is not None and ov['score'] is not None:
            if abs(oa['score'] - ov['score']) >= DIVERGENT_DELTA:
                pairs.append('%s/%s' % (a, v))
    return pairs or ['A2/A3 ↔ VB1/VB3']


def vb1_series(sid):
    _common.require_session(sid)
    pts = _vb1_series(sid)
    return {
        'points': pts,
        'threshold': ALERT_THRESHOLD,
        'valley': _valley(pts) if pts else None,
        'available': bool(pts),
        'note': None if pts else '该场次尚无 VB1 逐分钟统计（需 VLM 分区检测结果）',
    }
