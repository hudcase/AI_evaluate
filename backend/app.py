"""app.py — 后端入口

一条命令同时提供两件事：
  /api/*   REST 接口（契约见 docs/接口约定.md）
  其余     托管 frontend/ 静态文件（这样评审现场只跑一个进程）

用法：
  python backend/app.py                 # 8000 端口，同时托管前端
  python backend/app.py --port 8100
  python backend/app.py --seed-demo     # 首次启动灌一份演示数据
  python backend/app.py --reset-db      # 清库重建（演示用，会删掉 data/eval.db）

设计上刻意不用框架：一个路由表、一个 handler 类、九个模块，读代码就能看完，
不依赖 pip 也就不会有"评审机器上装不上"的问题。
"""
import argparse
import json
import os
import re
import sys
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import config          # noqa: E402
import db              # noqa: E402
import errors          # noqa: E402
import http_kit        # noqa: E402
import util            # noqa: E402

from modules import m1_courses, m2_media, m3_governance, m4_gateway   # noqa: E402
from modules import m5_indicators, m6_fusion, m7_report, m8_import, m9_desktop, system  # noqa: E402


# ---------------------------------------------------------------- 路由表

ROUTES = []


def route(method, pattern, handler, status=200):
    ROUTES.append((method, re.compile('^' + pattern + '$'), handler, status))


def _p(name):
    return r'(?P<%s>[^/]+)' % name


# 系统
route('GET', r'/api/health', lambda req: system.health())
route('GET', r'/api/overview', lambda req: system.overview())

# M1 建档
route('GET', r'/api/courses', lambda req: m1_courses.list_courses(
    req.q_int('page', 1), req.q_int('size', 20), req.q('q')))
route('POST', r'/api/courses', lambda req: m1_courses.create_course(req.json()), status=201)
route('GET', r'/api/courses/' + _p('cid'), lambda req, cid: m1_courses.get_course(cid))
route('DELETE', r'/api/courses/' + _p('cid'), lambda req, cid: m1_courses.delete_course(
    cid, req.q('confirm')))

# 批量入库（前端入口，与 tools/import.py 的 manifest 同构）
route('POST', r'/api/import', lambda req: m8_import.import_batch(req.json()), status=201)
route('GET', r'/api/sessions', lambda req: m1_courses.list_sessions(
    req.q('course_id'), req.q_int('page', 1), req.q_int('size', 20)))
route('POST', r'/api/sessions', lambda req: m1_courses.create_session(req.json()), status=201)
route('GET', r'/api/sessions/' + _p('sid'), lambda req, sid: m1_courses.get_session(sid))

# M2 数据接入
route('GET', r'/api/sessions/' + _p('sid') + r'/media', lambda req, sid: m2_media.list_media(sid))
route('DELETE', r'/api/sessions/' + _p('sid') + r'/media', lambda req, sid: m2_media.delete_media(
    sid, req.q('scope', 'raw'), req.q('confirm')))
# 逐条删除（删完该 slot 可立即重新登记）；purge=true 才连外部就地登记的原文件一起删
route('DELETE', r'/api/sessions/' + _p('sid') + r'/media/' + _p('aid'),
      lambda req, sid, aid: m2_media.delete_asset(sid, aid, req.q('confirm'), req.q('purge')))

# M3 数据治理
route('POST', r'/api/sessions/' + _p('sid') + r'/preprocess',
      lambda req, sid: m3_governance.preprocess(sid, req.json()), status=202)
route('GET', r'/api/sessions/' + _p('sid') + r'/tasks', lambda req, sid: m3_governance.list_tasks(
    sid, req.q('kind', 'preprocess'), req.q_int('limit', 20)))
route('GET', r'/api/tasks/' + _p('tid'), lambda req, tid: m3_governance.get_task(tid))
route('GET', r'/api/sessions/' + _p('sid') + r'/qc', lambda req, sid: m3_governance.get_qc(sid))
route('GET', r'/api/sessions/' + _p('sid') + r'/assets', lambda req, sid: m3_governance.get_assets(sid))

# M4 模型网关
route('GET', r'/api/sessions/' + _p('sid') + r'/ai-calls', lambda req, sid: m4_gateway.list_calls(sid))
route('POST', r'/ai/' + _p('cap'), lambda req, cap: m4_gateway.ai_call(cap, req.json()))

# M5 指标计算
route('GET', r'/api/indicators', lambda req: m5_indicators.get_indicators())
route('PUT', r'/api/indicators', lambda req: m5_indicators.put_indicators(req.json()))
route('GET', r'/api/sessions/' + _p('sid') + r'/observations',
      lambda req, sid: m5_indicators.get_observations(sid))
route('POST', r'/api/sessions/' + _p('sid') + r'/observations',
      lambda req, sid: m5_indicators.post_observation(sid, req.json()), status=201)
route('POST', r'/api/sessions/' + _p('sid') + r'/score',
      lambda req, sid: m5_indicators.rescore(sid, req.json()))

# M6 合成与一致性
route('GET', r'/api/sessions/' + _p('sid') + r'/evaluation',
      lambda req, sid: m6_fusion.compute(sid, persist=True))
route('GET', r'/api/sessions/' + _p('sid') + r'/vb1-series',
      lambda req, sid: m6_fusion.vb1_series(sid))

# M7 报告与审计
route('GET', r'/api/audit', lambda req: m7_report.list_audit(
    req.q_int('page', 1), req.q_int('size', 50)))

# 桌面端能力（原生对话框、目录扫描、退出）。Web 模式下这些接口回 enabled=false，
# 前端据此隐藏原生按钮，不会出现"点了没反应"。
route('GET', r'/api/desktop/info', lambda req: m9_desktop.info())
route('GET', r'/api/desktop/ping', lambda req: m9_desktop.ping())
route('POST', r'/api/desktop/bye', lambda req: m9_desktop.bye(req.json()))
route('POST', r'/api/desktop/dialog/folder', lambda req: m9_desktop.pick_folder(req.json()))
route('POST', r'/api/desktop/dialog/files', lambda req: m9_desktop.pick_files(req.json()))
route('POST', r'/api/desktop/dialog/save', lambda req: m9_desktop.pick_save(req.json()))
route('POST', r'/api/desktop/reveal', lambda req: m9_desktop.reveal(req.json()))
route('POST', r'/api/desktop/scan', lambda req: m9_desktop.scan(req.json()))
route('POST', r'/api/desktop/save-report', lambda req: m9_desktop.save_report(req.json()))
route('POST', r'/api/desktop/quit', lambda req: m9_desktop.quit_app(req.json()))


# ---------------------------------------------------------------- Handler

class Handler(BaseHTTPRequestHandler):
    server_version = 'EvalBackend/' + system.VERSION
    protocol_version = 'HTTP/1.1'

    # 让父类的日志只打一行，且不带颜色
    def log_message(self, fmt, *args):
        if os.environ.get('EVAL_QUIET') == '1':
            return
        sys.stderr.write('  %s %s\n' % (self.address_string(), fmt % args))

    # ---- 分发 ----
    def do_OPTIONS(self):
        self.send_response(204)
        http_kit._cors(self)
        self.end_headers()

    def do_GET(self):
        self._dispatch('GET')

    def do_HEAD(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def do_PUT(self):
        self._dispatch('PUT')

    def do_DELETE(self):
        self._dispatch('DELETE')

    def do_PATCH(self):
        self._dispatch('PATCH')

    def _dispatch(self, method):
        trace_id = uuid.uuid4().hex[:8]
        try:
            self._guard_origin(method)
            path, query = http_kit.parse_path(self.path)
            body = b''
            if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                body = self._read_body()

            req = http_kit.Request(method, path, query, dict(self.headers), body,
                                   rfile=self.rfile, client=self.client_address)

            if path.startswith('/api/') or path.startswith('/ai/'):
                self._api(method, req, path)
            else:
                http_kit.serve_static(self, config.FRONTEND_DIR, path)
        except errors.ApiError as exc:
            http_kit.send_error(self, exc, trace_id)
        except BrokenPipeError:
            pass
        except Exception as exc:                       # 兜底：任何未预料的异常都要有结构
            traceback.print_exc()
            http_kit.send_json(self, 500, {
                'error': {'code': 'INTERNAL', 'message': '%s: %s' % (type(exc).__name__, exc),
                          'trace_id': trace_id}})

    # ---- 跨站写操作防护 ----
    #
    # 单机部署时后端监听 127.0.0.1，浏览器里任何一个网页都能向它发"简单请求"
    # （表单 POST 不触发预检），读不到响应也足以改数据。这里在入口处拦掉：
    # 带 Origin 且不是本机来源，或浏览器标注 Sec-Fetch-Site 为跨站，一律 403。
    def _guard_origin(self, method):
        if method in ('GET', 'HEAD', 'OPTIONS') or config.ALLOW_ANY_ORIGIN:
            return
        origin = self.headers.get('Origin')
        if origin and origin not in config.ALLOWED_ORIGINS:
            raise errors.ApiError('FORBIDDEN', '拒绝跨站写请求（Origin=%s）' % origin)
        site = self.headers.get('Sec-Fetch-Site')
        if site and site not in ('same-origin', 'none'):
            raise errors.ApiError('FORBIDDEN', '拒绝跨站写请求（Sec-Fetch-Site=%s）' % site)

    def _read_body(self):
        ctype = (self.headers.get('Content-Type') or '').lower()
        if ctype.startswith('multipart/form-data'):
            return b''                                  # 由路由自己流式解析
        length = int(self.headers.get('Content-Length') or 0)
        if length > config.MAX_JSON_BYTES:
            raise errors.ApiError('VALIDATION_FAILED',
                                  'JSON 请求体超过 64 KiB；大文件请走 multipart 直传')
        return self.rfile.read(length) if length else b''

    def _api(self, method, req, path):
        # 报告导出：带 format= 的分支，单独处理二进制
        m = re.match(r'^/api/sessions/([^/]+)/report$', path)
        if m and method == 'GET':
            return self._report(m.group(1), req)

        # 媒资上传：multipart 与 JSON 两条路
        m = re.match(r'^/api/sessions/([^/]+)/media$', path)
        if m and method == 'POST':
            return self._media_upload(m.group(1), req)

        allowed_methods = []
        for rmethod, regex, handler, status in ROUTES:
            match = regex.match(path)
            if not match:
                continue
            if rmethod != method:
                allowed_methods.append(rmethod)
                continue
            kwargs = match.groupdict()
            result = handler(req, **kwargs) if kwargs else handler(req)
            return self._send_result(result, status)

        if allowed_methods:
            raise errors.ApiError('METHOD_NOT_ALLOWED',
                                  '%s 不支持 %s，可用：%s' % (path, method, '/'.join(sorted(set(allowed_methods)))))
        raise errors.ApiError('NOT_FOUND', '接口不存在：%s %s' % (method, path))

    def _send_result(self, result, status):
        if result is None:
            return http_kit.empty_response(self, 204)
        if isinstance(result, dict) and '__file__' in result:
            return http_kit.serve_file(self, result['__file__'], result['content_type'],
                                       result.get('filename'))
        if isinstance(result, dict) and '__html__' in result:
            return http_kit.html_response(self, result['__html__'], result.get('filename'))
        http_kit.send_json(self, status, result)

    # ---- 报告导出 ----
    def _report(self, sid, req):
        fmt = (req.q('format') or 'json').lower()
        out = m7_report.get_report(sid, fmt)
        if isinstance(out, dict) and 'path' in out:
            return http_kit.serve_file(self, out['path'], out['content_type'], out['filename'])
        if isinstance(out, dict) and 'html' in out:
            return http_kit.html_response(self, out['html'], out.get('filename'))
        http_kit.send_json(self, 200, out)

    # ---- 媒资上传 ----
    def _media_upload(self, sid, req):
        ctype = (self.headers.get('Content-Type') or '').lower()
        if not ctype.startswith('multipart/form-data'):
            return self._send_result(m2_media.register(sid, req.json()), 201)

        boundary = None
        for part in ctype.split(';'):
            part = part.strip()
            if part.startswith('boundary='):
                boundary = part[len('boundary='):].strip('"')
        if not boundary:
            raise errors.ApiError('VALIDATION_FAILED', '缺少 multipart boundary')

        saved = {}

        def open_part(name, filename, ptype):
            if filename:
                import tempfile
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.part',
                                                  dir=config.MEDIA_DIR)
                saved['file'] = {'name': filename, 'path': tmp.name, 'ctype': ptype}

                def closer(_total):
                    tmp.close()

                return tmp, closer

            class _Buf(object):
                def __init__(self):
                    self.buf = b''

                def write(self, data):
                    self.buf += data

            buf = _Buf()
            saved.setdefault('fields', {})
            saved['fields'][name] = buf
            return buf, None

        http_kit.stream_multipart(self.rfile, boundary, open_part,
                                  content_length=int(self.headers.get('Content-Length') or 0))
        fields = {k: v.buf.decode('utf-8', 'replace') for k, v in saved.get('fields', {}).items()}
        f = saved.get('file')
        if not f:
            raise errors.ApiError('VALIDATION_FAILED', 'multipart 中未找到 file 字段')

        try:
            with open(f['path'], 'rb') as fh:
                out = m2_media.upload_multipart(sid, fields, f['name'], fh)
        finally:
            try:
                os.remove(f['path'])
            except OSError:
                pass
        return self._send_result(out, 201)


# ---------------------------------------------------------------- 启动

def start_server(host=None, port=None, quiet=False):
    """建好服务器但不阻塞，返回 (srv, 实际端口)。

    port=0 表示让系统挑一个空闲端口——桌面版必须这么起：8000 被别的程序占着时，
    普通用户看到的只是"打不开"，而端口冲突是本地应用最常见的一类启动失败。
    """
    host = host or config.HOST
    port = config.PORT if port is None else port
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    actual = srv.server_address[1]

    # 白名单按"实际端口"算：以 0 起的服务，端口只有起来之后才知道
    if host == '0.0.0.0':
        config.ALLOW_ANY_ORIGIN = True          # 投屏/局域网演示：允许其他机器访问
    else:
        for h in ('127.0.0.1', 'localhost', '[::1]', host):
            config.ALLOWED_ORIGINS.add('http://%s:%d' % (h, actual))
    return srv, actual


def main(argv=None):
    ap = argparse.ArgumentParser(description='培训教学质量评估系统 · 后端')
    ap.add_argument('--host', default=config.HOST)
    ap.add_argument('--port', type=int, default=config.PORT, help='端口，0 = 自动挑空闲端口')
    ap.add_argument('--reset-db', action='store_true', help='清库重建（会删除 data/eval.db）')
    ap.add_argument('--seed-demo', action='store_true', help='灌入演示数据（已有数据则跳过）')
    ap.add_argument('--no-open', action='store_true', help='不自动打开浏览器')
    args = ap.parse_args(argv)

    config.ensure_dirs()
    info = db.init(reset=args.reset_db)
    print('数据库：%s' % info['db'])

    if args.seed_demo:
        from seed import demo
        n = demo.seed()
        print('演示数据：%s' % ('已写入 %d 场次' % n if n else '已存在，跳过'))

    desc = config.describe()
    print('模型网关：provider=%s  ffmpeg=%s  能力状态=%s'
          % (desc['provider'], '有' if desc['ffmpeg'] else '无（转码抽帧将跳过）',
             ', '.join('%s:%s' % (k, v) for k, v in desc['capabilities'].items())))
    print('前端：%s' % config.FRONTEND_DIR)

    srv, port = start_server(args.host, args.port)
    shown = args.host if args.host not in ('0.0.0.0', '') else '127.0.0.1'
    print('接口：http://%s:%d/api/health' % (shown, port))
    print('界面：http://%s:%d/' % (shown, port))
    print('数据：%s' % config.DATA_DIR)

    if not args.no_open:
        try:
            webbrowser.open('http://127.0.0.1:%d/' % port)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
