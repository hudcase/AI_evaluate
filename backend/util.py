"""util.py — 小工具

时间、ID、哈希、JSON 读写、分页。所有时间统一带时区偏移的 ISO 8601 字符串，
因此字符串排序即时间序（同一部署内偏移固定）。
"""
import datetime
import hashlib
import json
import os
import random
import re

TZ = datetime.datetime.now().astimezone().tzinfo


def now():
    return datetime.datetime.now(TZ)


def iso(dt=None):
    return (dt or now()).isoformat(timespec='seconds')


def today():
    return now().strftime('%Y%m%d')


_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789'   # 去掉易混的 I O


def new_id(prefix):
    """短 ID：前缀 + 6 位。原型期够用，接真实序列时换成库内自增即可"""
    body = ''.join(random.choice(_ALPHABET) for _ in range(6))
    return '%s-%s' % (prefix, body)


def seq_id(prefix, n):
    return '%s-%04d' % (prefix, n)


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def loads(text, default=None):
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def sha256_file(path, chunk=1024 * 256):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def round1(x):
    """保留一位小数，与前端 mock 的 Math.round(x*10)/10 对齐"""
    return round(float(x) * 10) / 10


def round3(x):
    return round(float(x) * 1000) / 1000


def mmss(sec):
    sec = float(sec or 0)
    m = int(sec // 60)
    s = int(round(sec - m * 60))
    return '%02d:%02d' % (m, s)


PII_PATTERNS = [
    re.compile(r'1[3-9]\d{9}'),                      # 手机号
    re.compile(r'\d{17}[\dXx]'),                     # 身份证
    re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+'),          # 邮箱
]


def has_pii(text):
    if not text:
        return False
    return any(p.search(text) for p in PII_PATTERNS)


def paginate(items, page, size):
    """契约：{"items":[],"total":0,"page":1,"size":20}"""
    page = max(1, int(page or 1))
    size = max(1, min(200, int(size or 20)))
    total = len(items)
    start = (page - 1) * size
    return {'items': items[start:start + size], 'total': total, 'page': page, 'size': size}


def human_bytes(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return ('%.0f %s' % (n, unit)) if unit == 'B' else ('%.1f %s' % (n, unit))
        n /= 1024.0


def free_gb(path):
    try:
        st = os.statvfs(path) if hasattr(os, 'statvfs') else None
        if st:
            return int(st.f_bavail * st.f_frsize / (1024 ** 3))
    except OSError:
        pass
    try:
        import shutil
        return int(shutil.disk_usage(path).free / (1024 ** 3))
    except OSError:
        return 0
