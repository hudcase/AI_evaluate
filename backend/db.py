"""db.py — SQLite 访问层

设计取舍：
* 单文件库 + WAL。端侧主机是单机部署，9 张表的量级（万级行）用 SQLite 足够，
  且备份就是拷一个文件，比引入 Postgres 更符合"评审现场能自己跑起来"的约束。
* 每线程一条连接（ThreadingHTTPServer 每请求一线程）。SQLite 连接不可跨线程共享，
  用 threading.local 持有；写操作用 IMMEDIATE 事务避免 "database is locked" 抢锁抖动。
* 行 → dict：对外一律 dict，模块层不接触 sqlite3.Row。
"""
import os
import sqlite3
import threading

import config
import util

_local = threading.local()
_write_lock = threading.RLock()

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')
INDICATORS_SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seed', 'indicators.json')


# ---------------------------------------------------------------- 连接

def connect():
    conn = getattr(_local, 'conn', None)
    if conn is None:
        config.ensure_dirs()
        conn = sqlite3.connect(config.DB_PATH, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 15000')
        _local.conn = conn
    return conn


def close():
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        conn.close()
        _local.conn = None


def q(sql, args=()):
    cur = connect().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def scalar(sql, args=(), default=None):
    row = q1(sql, args)
    if not row:
        return default
    return list(row.values())[0]


def x(sql, args=()):
    with _write_lock:
        cur = connect().execute(sql, args)
        cur.close()


def xmany(sql, seq):
    if not seq:
        return
    with _write_lock:
        cur = connect().executemany(sql, seq)
        cur.close()


class tx(object):
    """写事务。嵌套调用复用外层事务（savepoint 语义简化为直接复用）。"""

    def __enter__(self):
        self.conn = connect()
        self.own = not getattr(_local, 'in_tx', False)
        if self.own:
            _write_lock.acquire()
            self.conn.execute('BEGIN IMMEDIATE')
            _local.in_tx = True
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if not self.own:
            return False
        try:
            if exc_type is None:
                self.conn.execute('COMMIT')
            else:
                self.conn.execute('ROLLBACK')
        finally:
            _local.in_tx = False
            _write_lock.release()
        return False


# ---------------------------------------------------------------- 初始化

def init(reset=False):
    config.ensure_dirs()
    if reset and os.path.exists(config.DB_PATH):
        for suffix in ('', '-wal', '-shm'):
            try:
                os.remove(config.DB_PATH + suffix)
            except OSError:
                pass
        close()
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        connect().executescript(f.read())
    seed_indicators()
    return {'db': config.DB_PATH}


def seed_indicators():
    """首次启动写入指标配置。已有任何版本则不覆盖——配置是评价依据，不能被重启改掉。"""
    if scalar('SELECT COUNT(1) FROM indicator_config', (), 0):
        return 0
    data = util.loads(open(INDICATORS_SEED, 'r', encoding='utf-8').read(), {})
    version = data.get('config_version')
    published = data.get('published_at') or util.iso()
    domains = data.get('domains', {})
    rows = []
    for it in data.get('items', []):
        d = domains.get(it['domain'], {'name': it['domain'], 'weight': None})
        rows.append((
            version, it['code'], it['name'], it['tier'], it['domain'],
            d.get('name'), d.get('weight'),
            it.get('weight'), it['direction'],
            it.get('a'), it.get('b'), it.get('c'), it.get('d'),
            it.get('unit'), it.get('denominator_rule'),
            1 if it.get('scored') else 0, published,
        ))
    xmany("""INSERT OR REPLACE INTO indicator_config
             (config_version, code, name, tier, domain, domain_name, domain_weight,
              weight, direction, a, b, c, d, unit, denominator_rule, scored, published_at)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    x('UPDATE indicator_config SET published_at = ? WHERE config_version = ?', (published, version))
    return len(rows)


# ---------------------------------------------------------------- 指标配置读取

def current_config_version():
    v = scalar('SELECT config_version FROM indicator_config ORDER BY published_at DESC, config_version DESC LIMIT 1')
    if not v:
        seed_indicators()
        v = scalar('SELECT config_version FROM indicator_config ORDER BY published_at DESC, config_version DESC LIMIT 1')
    return v


def config_items(version=None):
    v = version or current_config_version()
    rows = q('SELECT * FROM indicator_config WHERE config_version = ? ORDER BY rowid', (v,))
    for r in rows:
        r['scored'] = bool(r['scored'])
    return {'config_version': v, 'items': rows}


def domains_of(version=None):
    """按 domain 聚合出域权重（视频 10 项已配平到 1.0000，域权重与项权重和一致）"""
    v = version or current_config_version()
    rows = q("""SELECT domain, domain_name, domain_weight, tier, SUM(COALESCE(weight,0)) AS sum_w
                FROM indicator_config WHERE config_version = ? GROUP BY domain ORDER BY rowid""", (v,))
    out = {}
    for r in rows:
        out[r['domain']] = {
            'name': r['domain_name'], 'weight': r['domain_weight'],
            'tier': r['tier'], 'weight_sum': round(r['sum_w'] or 0, 4),
        }
    return out


def find_indicator(code, version=None):
    v = version or current_config_version()
    row = q1('SELECT * FROM indicator_config WHERE config_version = ? AND code = ?', (v, code))
    if row:
        row['scored'] = bool(row['scored'])
    return row


# ---------------------------------------------------------------- 审计

def audit(action, object_id=None, actor='admin', detail=None):
    x('INSERT INTO audit (id, action, object_id, actor, detail_json, at) VALUES (?,?,?,?,?,?)',
      (util.new_id('L'), action, object_id, actor, util.dumps(detail or {}), util.iso()))
