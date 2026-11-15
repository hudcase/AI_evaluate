"""desktop/shell.py — 把页面装进一个窗口

三级降级，按"能给到多像桌面软件"排序：

  1. pywebview（若环境里有）：真原生窗口，可在 JS 里直接调 Python 回调。
     本机没装、也装不上（离线），保留这条是为了将来有人 pip install 后自动受益。
  2. Edge / Chrome 的 --app 模式：无地址栏、无标签页、独立任务栏图标、
     独立 user-data-dir（不污染用户日常浏览器的书签与登录态）。Win10/11 必有 Edge。
  3. 系统默认浏览器：最后兜底，至少能用。

降级是显式的——main.py 会把实际用的方式写进日志与 /api/desktop/info，
用户能看到"我是以哪种形态跑起来的"，而不是黑箱。
"""
import os
import subprocess
import sys
import webbrowser

# 常见安装位置，按 64 位优先
_EDGE_PATHS = [
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
]
_CHROME_PATHS = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
]


def _find_browser():
    for p in _EDGE_PATHS + _CHROME_PATHS:
        if p and os.path.isfile(p):
            return p
    return None


def _find_edge():
    for p in _EDGE_PATHS:
        if os.path.isfile(p):
            return p
    return None


APP_FLAGS = [
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-features=Translate,MediaRouter,msEdgeIdentityFeature',
    '--disable-background-networking',
    '--disable-component-update',
    '--disable-sync',
    '--no-service-autorun',
    '--disable-extensions',
]


def _launch_app_mode(url, profile_dir, size=(1440, 900)):
    exe = _find_browser()
    if not exe:
        return None, None
    os.makedirs(profile_dir, exist_ok=True)
    args = [exe, '--app=%s' % url, '--user-data-dir=%s' % profile_dir] + APP_FLAGS
    if size:
        args.append('--window-size=%d,%d' % size)
    # 独立进程组：主进程被 Ctrl+C 打断时窗口跟着退，不留孤儿浏览器
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = 0x00000200           # CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(args, **kwargs)
    return ('edge-app' if 'msedge' in os.path.basename(exe).lower() else 'chrome-app'), proc


def _launch_webview(url, title):
    """返回 (name, window, runner)；不可用时 (None, None, None)"""
    try:
        import webview
    except Exception:
        return None, None, None
    window = webview.create_window(title, url, width=1440, height=900,
                                   min_size=(1100, 700), text_select=True)

    def _run():
        webview.start()                                    # 阻塞至窗口关闭

    return 'webview', window, _run


def launch(url, title, profile_dir, mode='auto'):
    """返回 (shell_name, handle, runner)。

    handle：Popen / webview window / None（浏览器兜底）
    runner：webview 需要占主线程跑消息循环时返回可调用对象，其余为 None
    """
    if mode in ('auto', 'webview'):
        name, handle, runner = _launch_webview(url, title)
        if name:
            return name, handle, runner

    if mode in ('auto', 'edge'):
        name, proc = _launch_app_mode(url, profile_dir)
        if name:
            return name, proc, None

    # 兜底：交给系统浏览器
    webbrowser.open(url)
    return 'browser', None, None


def _enum_titled(title_part):
    """列出标题包含 title_part 的可见顶层窗口：(面积, hwnd, 标题)"""
    hits = []
    if sys.platform != 'win32':
        return hits
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _enum(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_part in buf.value:
                r = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
                hits.append((area, hwnd, buf.value))
        return True

    try:
        user32.EnumWindows(_enum, 0)
    except Exception:
        return []
    return hits


def window_exists(title_part):
    """应用窗口还在不在。用"窗口是否存在"而不是"进程是否活着"，
    因为 Edge 的启动器进程会提前退出，而窗口还在。"""
    return bool(_enum_titled(title_part))


def focus_window(title_part, timeout=15.0):
    """把窗口拉到前台并确保不是最小化状态。

    两次踩坑都收在这里：
      * 浏览器（尤其是新 profile 首启）偶尔把 --app 窗口开在后面或最小化，
        用户以为"双击没反应"——本地应用最不能接受的一种失败；
      * 最小化窗口的 GetWindowRect 返回 -32000 附近，截图和取尺寸都会失真。
    """
    if sys.platform != 'win32':
        return False
    import ctypes
    import time

    user32 = ctypes.windll.user32
    SW_RESTORE = 9

    deadline = time.time() + timeout
    while time.time() < deadline:
        hits = _enum_titled(title_part)
        if hits:
            hits.sort(reverse=True)
            hwnd = hits[0][1]
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            try:
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
            except Exception:
                pass
            return True
        time.sleep(0.4)
    return False


def terminate(proc):
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except Exception:
                proc.kill()
    except Exception:
        pass


def close_windows_by_title(title_part, timeout=3.0):
    """向标题包含 title_part 的顶层窗口发 WM_CLOSE。

    为什么需要：Edge 的 --app 启动器经常把窗口交给已有浏览器进程后自己先退出，
    我们手里那个 Popen 已经结束了，只能按窗口标题把它请走——否则主进程退了，
    窗口还挂在桌面上，用户会以为程序没关掉。
    """
    if sys.platform != 'win32':
        return 0
    import ctypes
    import time

    user32 = ctypes.windll.user32
    WM_CLOSE = 0x0010

    hits = _enum_titled(title_part)
    titles = [t for _a, _h, t in hits]
    for _a, hwnd, _t in hits:
        try:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass

    deadline = time.time() + timeout
    while titles and time.time() < deadline:
        still = [t for _a, _h, t in _enum_titled(title_part)]
        if not any(t in still for t in titles):
            break
        time.sleep(0.2)
    return len(titles)
