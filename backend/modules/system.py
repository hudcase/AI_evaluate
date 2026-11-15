"""modules/system.py — 总览与健康

总览是聚合视图，不引入新的口径：一行场次的两份分数与覆盖率，直接取该场次的 evaluation。
KPIs 里 avg_coverage 与课次表同源同算法，避免"卡片说 82%、表里三行平均 78%"这种自相矛盾。
"""
import db
import util

import config

from core import providers

from . import _common
from . import m6_fusion

VERSION = '0.3.0'


def _consistency():
    """跨模态一致性率：只统计有证据的场次。

    不读 evaluations 快照——快照只是"看过就存一份"的缓存，指标本身必须与页面同源。
    证据不足（insufficient）的场次不进分母，否则会把它读成"一致性差"。
    """
    aligned = total = 0
    for row in db.q("SELECT id FROM sessions WHERE status != 'processing'"):
        try:
            st = m6_fusion.compute(row['id'], persist=False)['consistency']['status']
        except Exception:
            continue
        if st == 'insufficient':
            continue
        total += 1
        if st == 'aligned':
            aligned += 1
    return aligned, total


def health(consistency=None):
    if consistency is None:
        consistency = _consistency()
    aligned, total_eval = consistency

    prov = providers.health()
    stats = db.q1("""SELECT COUNT(1) AS calls,
                            COALESCE(SUM(CASE WHEN cached=1 THEN 1 ELSE 0 END),0) AS cached,
                            COALESCE(SUM(CASE WHEN cached=0 THEN cost ELSE 0 END),0) AS cost
                     FROM ai_calls""") or {}

    tasks = db.q("SELECT result_json FROM ai_tasks WHERE status='succeeded'")
    blocked = 0
    cer_sum, der_sum, n_cer, n_der = 0.0, 0.0, 0, 0
    for t in tasks:
        res = util.loads(t['result_json'], {})
        if res.get('gate_overall') == 'reject':
            blocked += 1
        m = res.get('model_metrics') or {}
        if 'cer' in m:
            cer_sum += float(m['cer'])
            n_cer += 1
        if 'der' in m:
            der_sum += float(m['der'])
            n_der += 1

    obs_total = db.scalar('SELECT COUNT(1) FROM observations', (), 0)
    low_conf = db.scalar("""SELECT COUNT(1) FROM observations
                            WHERE confidence IS NOT NULL AND confidence < 0.7""", (), 0)

    simulated = db.scalar('SELECT COUNT(1) FROM ai_calls WHERE simulated=1', (), 0)
    return {
        'status': 'ok',
        'db': 'sqlite',
        'db_path': config.DB_PATH,
        'storage_free_gb': util.free_gb(config.DATA_DIR),
        'providers': prov,
        'version': VERSION,
        'pipeline': {
            'consistency_rate': round(aligned / total_eval, 3) if total_eval else None,
            'cer': round(cer_sum / n_cer, 3) if n_cer else None,
            'der': round(der_sum / n_der, 3) if n_der else None,
            'gate_block_rate': round(blocked / len(tasks), 3) if tasks else None,
            'low_conf_rate': round(low_conf / obs_total, 3) if obs_total else None,
        },
        'money': {
            'calls': stats.get('calls', 0),
            'cached': stats.get('cached', 0),
            'cost': round(stats.get('cost', 0) or 0, 2),
            'simulated_calls': simulated,
        },
        'provider_mode': config.MODEL_PROVIDER,
        'ffmpeg': bool(config.FFMPEG),
        'desktop': config.DESKTOP,
    }


def overview():
    rows = db.q('SELECT * FROM sessions ORDER BY date DESC, start DESC')
    out = []
    n_cons = n_aligned = 0
    for s in rows:
        course = db.q1('SELECT title FROM courses WHERE id = ?', (s['course_id'],)) or {}
        if s['status'] == 'processing':
            audio = video = cov = None
        else:
            ev = m6_fusion.compute(s['id'], persist=False)
            audio = ev['audio']['score'] if ev['audio']['coverage'] > 0 else None
            video = ev['video']['score'] if ev['video']['coverage'] > 0 else None
            cov = min(ev['audio']['coverage'], ev['video']['coverage'])
            cst = ev['consistency']['status']
            if cst != 'insufficient':
                n_cons += 1
                if cst == 'aligned':
                    n_aligned += 1
            if cst == 'insufficient':
                audio = video = None
        out.append({
            'id': s['id'], 'title': s['title'], 'course': course.get('title'),
            'date': s['date'], 'start': s['start'], 'scenario': s['scenario'],
            'teacher': s['teacher'], 'students': s['students'],
            'status': s['status'], 'stage': s['stage'],
            'audio': audio, 'video': video, 'coverage': cov,
        })

    with_cov = [r for r in out if r['coverage'] is not None]
    avg_cov = (sum(r['coverage'] for r in with_cov) / len(with_cov)) if with_cov else 0
    month = util.now().strftime('%Y-%m')
    cost = db.scalar("SELECT COALESCE(SUM(CASE WHEN cached=0 THEN cost ELSE 0 END),0) FROM ai_calls WHERE at LIKE ?",
                     (month + '%',), 0)
    calls = db.scalar('SELECT COUNT(1) FROM ai_calls WHERE at LIKE ?', (month + '%',), 0)
    cached = db.scalar('SELECT COUNT(1) FROM ai_calls WHERE cached=1 AND at LIKE ?', (month + '%',), 0)

    return {
        'sessions': out,
        'kpis': {
            'total': len(out),
            'reported': len([r for r in out if r['stage'] == 'report']),
            'avg_coverage': round(avg_cov, 4),
            'monthly_cost': round(cost or 0, 2),
            'monthly_calls': calls,
            'monthly_cached': cached,
        },
        'health': health((n_aligned, n_cons)),
    }
