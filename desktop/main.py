"""desktop/main.py — 桌面版入口

跑法：
    python desktop/main.py                  # 起窗口（Edge --app 模式）
    python desktop/main.py --no-window      # 只起服务，不开窗口（排障／自测用）
    python desktop/main.py --port 8000      # 指定端口（默认自己找空闲的）
    python desktop/main.py --reset-db --seed-demo
    python desktop/main.py --shell browser  # 强制用默认浏览器打开（演示兜底）

它做的事就三件：把后端起在 127.0.0.1 的一个空闲端口上、把页面装进一个无地址栏的窗口、
窗口关上就把后端一起收干净。数据落 %LOCALAPPDATA%\\EvalConsole\\data（便携模式见 config.py）。
"""
import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time

DESKTOP_DIR = os.path.dirname(os.path.abspath(__file__))
SOFTWARE_DIR = os.path.dirname(DESKTOP_DIR)
BACKEND_DIR = os.path.join(SOFTWARE_DIR, 'backend')
for _p in (BACKEND_DIR, SOFTWARE_DIR, DESKTOP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TITLE = '培训教学质量评估系统'

log = logging.getLogger('desktop')


# ---------------------------------------------------------------- 生命周期

class App(object):
    def __init__(self, args):
        self.args = args
        self.stop = threading.Event()
        self.srv = None
        self.port = 0
        self.proc = None
        self.shell = None

    # ---- 退出 ----
    def request_quit(self, *_a):
        """m9_desktop.quit_app 与信号处理都调这里；只置事件，清理交给主线程。"""
        self.stop.set()

    # ---- 起服务 ----
    def start_backend(self):
        import app as backend          # 延迟导入：先把 EVAL_* 环境变量设好
        import config
        import db

        config.ensure_dirs()
        info = db.init(reset=self.args.reset_db)
        log.info('数据库 %s', info['db'])

        if self.args.seed_demo:
            try:
                from seed import demo
                n = demo.seed()
                log.info('演示数据 %s', '写入 %d 场次' % n if n else '已存在，跳过')
            except Exception:
                log.exception('灌演示数据失败')

        candidates = []
        if self.args.port:
            candidates = [self.args.port]
        else:
            candidates = [8000, 8080, 8888] + [0]     # 都占用了就让系统挑

        last = None
        for p in candidates:
            try:
                self.srv, self.port = backend.start_server(self.args.host, p)
                break
            except OSError as exc:
                last = exc
                log.warning('端口 %s 不可用：%s', p, exc)
        if not self.srv:
            raise RuntimeError('没有可用端口：%s' % last)

        t = threading.Thread(target=self.srv.serve_forever, name='http', daemon=True)
        t.start()

        # 桌面能力必须在服务起来之后就登记：--no-window 排查问题时前端也要能拿到 info
        from modules import m9_desktop
        m9_desktop.enable(self.port, None, self.request_quit)

        shown = '127.0.0.1' if self.args.host in ('0.0.0.0', '') else self.args.host
        log.info('后端 http://%s:%d/  data=%s', shown, self.port, config.DATA_DIR)
        return 'http://%s:%d/' % (shown, self.port)

    # ---- 起窗口 ----
    def open_window(self, url):
        import config
        import shell as sh
        from modules import m9_desktop

        profile = config.UI_DIR
        name, handle, runner = sh.launch(url, TITLE, profile, mode=self.args.shell)
        self.shell = name
        m9_desktop.STATE['shell'] = name
        log.info('窗口形态 %s', name)

        threading.Thread(target=self._watch_page, name='page-watch', daemon=True).start()

        if name in ('edge-app', 'chrome-app'):
            # 新 profile 首启时窗口可能开在后面／最小化，拉一次前台
            threading.Thread(target=sh.focus_window, args=(TITLE,),
                             name='focus', daemon=True).start()

        if name == 'edge-app' or name == 'chrome-app':
            self.proc = handle
            return None
        if name == 'webview':
            return runner                     # 交给主线程跑消息循环
        return None

    def _watch_page(self):
        """看门狗：窗口真没了才退。

        判断口径要经得起两种现实：
          * 关窗口时页面发的关闭信号可能早于窗口消失（有动画、有进程收尾），
            所以先按信号起疑，再用"窗口还在不在"确认，最多复核 8 次（16 秒）；
          * 页面可能因休眠/刷新短暂卸载并发出关闭信号，但窗口一直在——
            这种情况必须撤销退出，否则用户开着一小时不看就被踢出应用。
        """
        import shell as sh
        from modules import m9_desktop

        started = time.time()
        retries = 0
        while not self.stop.is_set():
            reason = m9_desktop.should_quit()

            if reason == 'page-closed':
                if sh.window_exists(TITLE):
                    retries += 1
                    if retries <= 8:
                        m9_desktop.STATE['bye_at'] = time.time() + 2.0
                        time.sleep(2.0)
                        continue
                    m9_desktop.touch()
                    log.info('收到关闭信号但窗口仍在（刷新或页面休眠），撤销退出')
                    retries = 0
                else:
                    log.info('窗口已关闭，退出')
                    self.stop.set()
                    return

            elif reason:
                log.info('页面生命周期结束（%s），准备退出', reason)
                self.stop.set()
                return

            if not m9_desktop.STATE['seen'] and (time.time() - started) > 90:
                log.warning('窗口 90 秒内没有载入页面，退出以免留下孤儿进程')
                self.stop.set()
                return
            time.sleep(1.0)

    # ---- 收尾 ----
    def shutdown(self):
        import shell as sh
        try:
            if self.proc is not None:
                sh.terminate(self.proc)
            if self.shell in ('edge-app', 'chrome-app'):
                n = sh.close_windows_by_title(TITLE)
                if n:
                    log.info('已关闭 %d 个窗口', n)
            if self.srv is not None:
                self.srv.shutdown()
                self.srv.server_close()
        except Exception:
            log.exception('退出清理异常')
        try:
            import instance
            instance.clear_runtime()
        except Exception:
            pass
        log.info('已退出')


# ---------------------------------------------------------------- 日志

def setup_logging(verbose=False):
    import config
    config.ensure_dirs()
    path = os.path.join(config.LOG_DIR, 'desktop.log')
    fmt = logging.Formatter('%(asctime)s %(levelname)-5s %(name)s | %(message)s',
                            '%Y-%m-%d %H:%M:%S')
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers[:] = [handler]
    if verbose:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        root.addHandler(console)
    return path


def redirect_std_streams(log_path):
    """打包成 windowed exe 后没有控制台，print 会写进 None 直接抛异常。
    统一重定向进日志文件，出了事才有东西可查。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        fh = open(log_path, 'a', encoding='utf-8', buffering=1)
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = fh
    if sys.stderr is None:
        sys.stderr = fh


# ---------------------------------------------------------------- 入口

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description='培训教学质量评估系统 · 桌面版')
    ap.add_argument('--port', type=int, default=0, help='监听端口，0＝自动（先试 8000）')
    ap.add_argument('--host', default='127.0.0.1', help='一般不用改；0.0.0.0 供局域网演示')
    ap.add_argument('--data-dir', default='', help='数据目录，默认 %%LOCALAPPDATA%%\\EvalConsole\\data')
    ap.add_argument('--shell', default='auto', choices=['auto', 'webview', 'edge', 'browser'],
                    help='窗口形态，默认 auto：webview→Edge app→浏览器')
    ap.add_argument('--no-window', action='store_true', help='只起服务不开窗口')
    ap.add_argument('--reset-db', action='store_true')
    ap.add_argument('--seed-demo', action='store_true')
    ap.add_argument('--verbose', '-v', action='store_true')
    return ap.parse_args(argv)


def _url_port(url):
    try:
        return int(url.rstrip('/').rsplit(':', 1)[1])
    except Exception:
        return 0


def main(argv=None):
    args = parse_args(argv)

    # 环境变量必须在 import config 之前设好
    os.environ['EVAL_DESKTOP'] = '1'
    if args.data_dir:
        os.environ['EVAL_DATA_DIR'] = args.data_dir
    if args.host != '127.0.0.1':
        os.environ['EVAL_HOST'] = args.host

    log_path = setup_logging(args.verbose)
    redirect_std_streams(log_path)

    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                'EvalConsole.Desktop.1')           # 任务栏按本应用分组，不与 python.exe 混在一起
        except Exception:
            pass

    import config
    import instance
    import shell as sh
    from core import native_win

    log.info('启动 pid=%s frozen=%s data=%s', os.getpid(), config.FROZEN, config.DATA_DIR)

    # ---- 单实例 ----
    if not args.no_window:
        rt = instance.read_runtime()
        if rt and instance.probe(rt.get('url', 'http://127.0.0.1:%d/' % rt['port'])):
            log.info('已有实例在跑（pid=%s port=%s），只开窗口', rt.get('pid'), rt.get('port'))
            sh.launch(rt['url'], TITLE, config.UI_DIR,
                      mode=args.shell)
            return 0

    app = App(args)

    def _on_signal(signum, _frame):
        log.info('收到信号 %s，退出', signum)
        app.request_quit()

    for sig in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        try:
            signal.signal(getattr(signal, sig), _on_signal)
        except (AttributeError, ValueError):
            pass

    try:
        url = app.start_backend()
        instance.write_runtime(app.port, 'pending')

        if args.no_window:
            log.info('--no-window：只提供 http://127.0.0.1:%d/ ，Ctrl+C 退出', app.port)
            while not app.stop.is_set():
                time.sleep(0.5)
        else:
            runner = app.open_window(url)
            instance.write_runtime(app.port, app.shell or 'none')
            if runner is not None:
                # webview 要独占主线程跑消息循环，退出时它自己返回
                runner()
                app.request_quit()
            while not app.stop.is_set():
                time.sleep(0.3)
    except Exception as exc:
        log.exception('启动失败')
        native_win.message_box(
            '启动失败：%s\n\n日志：%s\n\n常见原因：端口被占用、数据目录无写权限、'
            '上一份数据库被其他程序锁定。' % (exc, log_path),
            TITLE + ' · 启动失败')
        return 2
    finally:
        app.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
