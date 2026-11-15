"""modules/m4_gateway.py — M4 模型网关

前端只读日志（GET /api/sessions/{id}/ai-calls）；真正发请求的是内部接口 POST /ai/{capability}，
它只允许服务端模块调用，不对外暴露给浏览器（原型期未开鉴权，靠部署边界隔离）。

汇总口径与页面一致：calls 是全部调用数，cached 是其中命中缓存的次数，cost 是计费总额（不含命中缓存的 0 元调用）。
p95 用最近 200 次延迟真算，不写死。
"""
import db
import errors
import util

from core import providers

from . import _common

CAPS = ('asr', 'ocr', 'embed', 'llm', 'vlm')


def ai_call(capability, body, session_id=None):
    if capability not in CAPS:
        errors.fail('VALIDATION_FAILED', 'capability 需为 %s 之一' % '／'.join(CAPS), 'capability')
    payload = dict(body or {})
    session_id = session_id or payload.pop('session_id', None)
    mv = payload.pop('model_version', None)
    pv = payload.pop('prompt_version', None)
    res = providers.call(capability, payload, session_id=session_id,
                         model_version=mv, prompt_version=pv,
                         use_cache=bool(payload.pop('use_cache', True)))
    out = dict(res['data'])
    out.update({'call_id': res['call_id'], 'cached': res['cached'],
                'cost': res['cost'], 'simulated': res['simulated']})
    return out


def list_calls(sid):
    _common.require_session(sid)
    rows = db.q('SELECT * FROM ai_calls WHERE session_id = ? ORDER BY at DESC', (sid,))
    items = [{
        'id': r['id'], 'capability': r['capability'], 'provider': r['provider'],
        'model': r['provider'], 'model_version': r['model_version'],
        'prompt_version': r['prompt_version'], 'tokens_in': r['tokens_in'],
        'tokens_out': r['tokens_out'], 'latency_ms': r['latency_ms'],
        'cost': round(r['cost'], 4), 'cached': bool(r['cached']),
        'simulated': bool(r['simulated']), 'at': r['at'],
    } for r in rows]

    by_cap = {}
    for r in rows:
        b = by_cap.setdefault(r['capability'], {'capability': r['capability'], 'calls': 0, 'cost': 0.0})
        b['calls'] += 1
        b['cost'] = round(b['cost'] + (0 if r['cached'] else r['cost']), 4)
    for b in by_cap.values():
        b['cost'] = round(b['cost'], 2)

    lats = sorted(r['latency_ms'] for r in rows[:200])
    p95 = lats[int(len(lats) * 0.95) - 1] if len(lats) >= 2 else (lats[0] if lats else 0)

    return {
        'items': items,
        'summary': {
            'calls': len(rows),
            'cached': len([r for r in rows if r['cached']]),
            'cost': round(sum(0 if r['cached'] else r['cost'] for r in rows), 2),
            'p95_latency_ms': p95,
            'simulated': len([r for r in rows if r['simulated']]),
            'byCapability': sorted(by_cap.values(), key=lambda x: -x['calls']),
        }
    }


def health():
    prov = providers.health()
    stats = db.q1("""SELECT COUNT(1) AS calls, COALESCE(SUM(CASE WHEN cached=1 THEN 1 ELSE 0 END),0) AS cached,
                            COALESCE(SUM(CASE WHEN cached=0 THEN cost ELSE 0 END),0) AS cost
                     FROM ai_calls""") or {}
    simulated = db.scalar('SELECT COUNT(1) FROM ai_calls WHERE simulated = 1', (), 0)
    return {
        'providers': prov,
        'calls': stats.get('calls', 0),
        'cached': stats.get('cached', 0),
        'cost': round(stats.get('cost', 0) or 0, 2),
        'simulated': simulated,
    }
