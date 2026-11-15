"""http_kit.py — HTTP 基础设施

只用标准库。三件事：
  1. 把请求解析成 (method, path, query, json_body)
  2. 把响应写成 JSON／文件／二进制，统一 CORS 与错误体
  3. multipart 流式解析——4K 原片可能有几个 GB，绝不能整个读进内存

错误一律走 errors.ApiError，由 app.py 的 dispatch 兜住转成 JSON，
因此业务模块里可以直接 raise，不必关心 HTTP 细节。
"""
import io
import json
import os
import posixpath
import re
import urllib.parse

import errors
import config

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.md': 'text/markdown; charset=utf-8',
}


class Request(object):
    __slots__ = ('method', 'path', 'query', 'headers', 'body', 'rfile', 'client')

    def __init__(self, method, path, query, headers, body, rfile=None, client=None):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body
        self.rfile = rfile
        self.client = client

    # ---- 便捷取值 ----
    def q(self, key, default=None):
        v = self.query.get(key)
        return v[0] if isinstance(v, list) and v else (v if v is not None else default)

    def q_int(self, key, default):
        try:
            return int(self.q(key, default))
        except (TypeError, ValueError):
            return default

    def json(self):
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise errors.ApiError('VALIDATION_FAILED', '请求体不是合法 JSON')
        if not isinstance(data, dict):
            raise errors.ApiError('VALIDATION_FAILED', '请求体需为 JSON 对象')
        return data

    def header(self, key, default=None):
        for k, v in self.headers.items():
            if k.lower() == key.lower():
                return v
        return default


def parse_path(raw):
    parsed = urllib.parse.urlsplit(raw)
    path = urllib.parse.unquote(parsed.path)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    return path, query


# ---------------------------------------------------------------- 响应

def send_json(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    _cors(handler)
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    if handler.command != 'HEAD':
        handler.wfile.write(body)


def send_error(handler, exc, trace_id=None):
    send_json(handler, exc.status, exc.payload(trace_id))


def send_bytes(handler, status, body, content_type, filename=None, cache='no-store'):
    handler.send_response(status)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(body)))
    if filename:
        from urllib.parse import quote
        handler.send_header('Content-Disposition',
                            "attachment; filename*=UTF-8''%s" % quote(filename))
    handler.send_header('Cache-Control', cache)
    _cors(handler)
    handler.end_headers()
    if handler.command != 'HEAD':
        handler.wfile.write(body)


def _cors(handler):
    """CORS 只在"局域网演示"时放开成 *；单机/桌面模式下只回显本机来源，
    否则任意网页都能借浏览器写本机库（表单 POST 连预检都不发）。"""
    headers = getattr(handler, 'headers', None)
    if config.ALLOW_ANY_ORIGIN:
        handler.send_header('Access-Control-Allow-Origin', '*')
    else:
        origin = (headers.get('Origin') if headers else None) or ''
        if origin and origin in config.ALLOWED_ORIGINS:
            handler.send_header('Access-Control-Allow-Origin', origin)
            handler.send_header('Vary', 'Origin')
    handler.send_header('Access-Control-Allow-Headers',
                        'Content-Type, Authorization, X-Api-Version, Idempotency-Key')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    handler.send_header('Access-Control-Max-Age', '600')


# ---------------------------------------------------------------- 静态文件

def serve_static(handler, root, path):
    if path in ('/', ''):
        path = '/index.html'
    clean = posixpath.normpath(path).lstrip('/')
    if clean.startswith('..'):
        raise errors.ApiError('FORBIDDEN', '非法路径')
    full = os.path.join(root, *clean.split('/'))
    if os.path.isdir(full):
        full = os.path.join(full, 'index.html')
    if not os.path.isfile(full):
        raise errors.ApiError('NOT_FOUND', '资源不存在：%s' % path)
    ext = os.path.splitext(full)[1].lower()
    with open(full, 'rb') as f:
        body = f.read()
    mime = MIME.get(ext, 'application/octet-stream')
    # html/js/css 不缓存，避免改了代码刷不出来；其余允许短缓存
    cache = 'no-store' if ext in ('.html', '.js', '.css') else 'max-age=60'
    send_bytes(handler, 200, body, mime, cache=cache)


def serve_file(handler, path, content_type, filename=None):
    if not os.path.exists(path):
        raise errors.ApiError('NOT_FOUND', '文件不存在')
    with open(path, 'rb') as f:
        body = f.read()
    send_bytes(handler, 200, body, content_type, filename=filename)


# ---------------------------------------------------------------- multipart

def _param(header, key):
    m = re.search(r'%s="([^"]*)"' % key, header or '')
    return m.group(1) if m else None


class _StreamReader(object):
    """带缓冲的流读取器：能读行、能读到分隔符，且**不丢已读到的字节**。

    之前的实现找到分隔符后把"分隔符之后"的缓冲直接扔了，于是多段 body 只能解析出第一个字段；
    加上 rfile.read(n) 在 socket 上会阻塞到读满 n 字节，小文件上传会直接卡死。
    两个坑都收在这一个类里，别再在调用方拼缓冲。
    """

    def __init__(self, readfn):
        self.buf = b''
        self.eof = False
        self._read = readfn

    def _fill(self, want=65536):
        if self.eof:
            return False
        chunk = self._read(want)
        if not chunk:
            self.eof = True
            return False
        self.buf += chunk
        return True

    def readline(self, limit=8192):
        while b'\n' not in self.buf and len(self.buf) < limit:
            if not self._fill():
                break
        i = self.buf.find(b'\n')
        if i < 0:
            line, self.buf = self.buf[:limit], self.buf[:0]
            return line
        line, self.buf = self.buf[:i + 1], self.buf[i + 1:]
        return line

    def ensure(self, n):
        while len(self.buf) < n and self._fill():
            pass
        return len(self.buf) >= n

    def skip(self, prefix):
        """缓冲区开头正好是 prefix 就吃掉它，返回是否吃到了"""
        if not self.ensure(len(prefix)):
            return False
        if self.buf.startswith(prefix):
            self.buf = self.buf[len(prefix):]
            return True
        return False

    def read_until(self, delim, sink):
        """读到 delim 为止（delim 本身被吃掉），沿途的字节交给 sink。返回是否找到了"""
        while True:
            i = self.buf.find(delim)
            if i >= 0:
                sink(self.buf[:i])
                self.buf = self.buf[i + len(delim):]
                return True
            keep = len(delim) - 1
            if len(self.buf) > keep:
                sink(self.buf[:-keep])
                self.buf = self.buf[-keep:]
            if not self._fill():
                sink(self.buf)
                self.buf = b''
                return False


def stream_multipart(rfile, boundary, open_part, content_length=None):
    """流式解析 multipart，不把文件读进内存。

    open_part(name, filename, content_type) -> (fileobj, closer)
      fileobj 为 None 表示这个 part 不落盘（但仍会被读完，否则后面的 part 会错位）
    返回 {name: value}（仅普通字段，键名为 __raw_<name>）

    content_length 必传：socket 上的 read(n) 会阻塞到读满 n 字节或 EOF，
    而客户端发完就停在那里等响应——不按长度收敛，小文件必然死锁。
    """
    dbound = ('\r\n--' + boundary).encode('utf-8')
    remaining = int(content_length) if content_length else None

    def _read(n):
        nonlocal remaining
        if remaining is None:
            reader = getattr(rfile, 'read1', None)      # 不知道长度就只读"当前可用"
            return reader(n) if reader else rfile.read(n)
        if remaining <= 0:
            return b''
        chunk = rfile.read(min(n, remaining))
        remaining -= len(chunk)
        return chunk

    br = _StreamReader(_read)
    first = br.readline()
    if boundary.encode('utf-8') not in first:
        raise errors.ApiError('VALIDATION_FAILED', 'multipart 边界不正确')

    fields = {}
    while True:
        headers = {}
        while True:
            line = br.readline()
            if not line:
                return fields
            if not line.strip():
                break
            k, _, v = line.decode('utf-8', 'replace').partition(':')
            headers[k.strip().lower()] = v.strip()
        if not headers:
            return fields

        disp = headers.get('content-disposition', '')
        name = _param(disp, 'name')
        filename = _param(disp, 'filename')
        ctype = headers.get('content-type')

        target, closer = open_part(name, filename, ctype)
        total = [0]

        def sink(data, _t=target, _n=total):
            if _t and data:
                _t.write(data)
                _n[0] += len(data)

        found = br.read_until(dbound, sink)
        if closer:
            closer(total[0])
        if not found:
            return fields
        if br.skip(b'--'):                     # 结尾分隔符
            return fields
        br.skip(b'\r\n')                       # 下一个 part 的头前换行
        if name and target is None:
            fields.setdefault('__raw_%s' % name, None)


    return fields


def empty_response(handler, status=204):
    handler.send_response(status)
    _cors(handler)
    handler.end_headers()


def html_response(handler, html, filename=None):
    send_bytes(handler, 200, html.encode('utf-8'), 'text/html; charset=utf-8', filename=filename)
