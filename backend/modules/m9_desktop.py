"""modules/m9_desktop.py — 桌面端专用能力

这些接口只在桌面版（desktop/main.py 启动）里真正可用；用浏览器打开时 info() 回
enabled=false，其余接口一律 501，前端据此隐藏原生按钮——不出现"点了没反应"。

存在的理由很具体：
  * 浏览器拿不到真实文件路径（`C:\\fakepath\\`），而本系统的入库是"就地登记"，
    几十 GB 原片只记路径不搬字节，必须是真路径 → 选择对话框放在后端进程里。
  * 报告导出在浏览器里只能落到"下载目录"，桌面软件应当"另存为"→ 前端选路径，
    后端直接把文件写到那个路径（不经浏览器，也就没有大小与编码损耗）。
"""
import json
import os
import threading
import time
import uuid

import config
import db
import errors
import scan_dir
from core import native_win
from modules import m7_report, system

# 由 desktop/main.py 在启动时填
STATE = {
    'enabled': False,
    'port': 0,
    'shell': None,          # 'webview' / 'edge-app' / 'browser'
    'quit_cb': None,
    'last_seen': 0.0,       # 页面最近一次报到（info / ping）
    'seen': False,
    'bye_at': 0.0,          # 页面关闭信号触发的退出时刻
}

_dialog_lock = threading.Lock()
DIALOG_WAIT = 300           # 同时只允许一个对话框，等太久就当没人操作

HEARTBEAT_IDLE = 300        # 5 分钟没有任何报到 = 页面没了（崩了或强杀）
BYE_GRACE = 3.0             # 收到关闭信号后等 3 秒：刷新页面也会发关闭信号，不能被当成退出


def enable(port=None, shell=None, quit_cb=None):
    STATE['enabled'] = True
    STATE['port'] = port or 0
    STATE['shell'] = shell
    STATE['quit_cb'] = quit_cb


def touch():
    """页面还活着。刷新会同时触发 bye 与新的 info，这里把待退出状态抵消掉。"""
    STATE['last_seen'] = time.time()
    STATE['seen'] = True
    STATE['bye_at'] = 0.0


def should_quit():
    """给 desktop/main.py 的看门狗用：返回退出原因或 None。

    为什么不看浏览器进程有没有退出：Edge 的 --app 启动器进程经常在把窗口交给
    已有浏览器进程后立刻返回，按"进程结束"判断会让后端先于窗口退掉。
    页面报到／页面关闭信号才是一手事实。
    """
    now = time.time()
    if STATE['bye_at'] and now >= STATE['bye_at']:
        return 'page-closed'
    if STATE['seen'] and (now - STATE['last_seen']) > HEARTBEAT_IDLE:
        return 'heartbeat-timeout'
    return None


def _require_desktop():
    if not STATE['enabled']:
        raise errors.ApiError('NOT_IMPLEMENTED',
                              '该能力只在桌面版可用；浏览器模式下请手动填写路径')
    if not native_win.available():
        raise errors.ApiError('NOT_IMPLEMENTED', '当前平台不支持原生对话框')


# ---------------------------------------------------------------- 基本信息

def info():
    touch()
    return {
        'desktop': STATE['enabled'],
        'available': native_win.available(),
        'shell': STATE['shell'],
        'version': system.VERSION,
        'data_dir': config.DATA_DIR,
        'log_dir': config.LOG_DIR,
        'export_dir': config.EXPORT_DIR,
        'db_path': config.DB_PATH,
        'frozen': config.FROZEN,
        'python': '%d.%d.%d' % tuple(__import__('sys').version_info[:3]),
        'port': STATE['port'],
    }


# ---------------------------------------------------------------- 存活信号

def ping():
    touch()
    return {'ok': True, 'ts': round(time.time(), 3), 'enabled': STATE['enabled']}


def bye(body=None):
    """页面正在关闭（关窗口／关标签／刷新）。

    不能立刻退：刷新页面同样会触发 pagehide，退了就把用户踢出应用。
    这里只挂一个 3 秒的倒计时，新页面载入立刻 info() 抵消掉。
    """
    if not STATE['enabled']:
        return {'ok': True, 'ignored': True}
    STATE['bye_at'] = time.time() + BYE_GRACE
    return {'ok': True, 'grace': BYE_GRACE}


# ---------------------------------------------------------------- 原生对话框

def _with_dialog(fn, *args, **kwargs):
    if not _dialog_lock.acquire(timeout=DIALOG_WAIT):
        raise errors.ApiError('STATE_CONFLICT', '已有对话框在等待操作')
    try:
        return fn(*args, **kwargs)
    finally:
        _dialog_lock.release()


def pick_folder(body):
    _require_desktop()
    initial = body.get('initial') or ''
    title = body.get('title') or '选择文件夹'
    path = _with_dialog(native_win.pick_folder, title, initial)
    return {'path': path, 'cancelled': path is None}


def pick_files(body):
    _require_desktop()
    paths = _with_dialog(native_win.pick_files,
                         body.get('title') or '选择文件',
                         body.get('initial') or None,
                         body.get('filters') or None,
                         bool(body.get('multiselect', True)))
    return {'paths': paths, 'cancelled': not paths}


def pick_save(body):
    _require_desktop()
    path = _with_dialog(native_win.save_file,
                        body.get('title') or '另存为',
                        body.get('initial') or config.EXPORT_DIR,
                        body.get('filename') or None,
                        body.get('filters') or None,
                        body.get('default_ext') or None)
    return {'path': path, 'cancelled': path is None}


def reveal(body):
    path = (body.get('path') or '').strip()
    if not path:
        errors.fail('VALIDATION_FAILED', '缺 path', 'path')
    ok = native_win.reveal(path)
    return {'ok': ok, 'path': path}


# ---------------------------------------------------------------- 目录扫描

def scan(body):
    root = (body.get('root') or '').strip()
    if not root:
        errors.fail('VALIDATION_FAILED', '缺 root 目录', 'root')
    if not os.path.isdir(root):
        errors.fail('VALIDATION_FAILED', '目录不存在：%s' % root, 'root')

    manifest, issues, stats = scan_dir.scan(
        root,
        scenario=body.get('scenario') or 'theory',
        duration_min=int(body.get('duration_min') or 90),
        consent=bool(body.get('consent', True)))

    # 已入库过的课程/场次提前标出来，省得用户提交后才发现"全是复用"
    for c in manifest['courses']:
        row = db.q1('SELECT id FROM courses WHERE title = ?', (c['title'].strip(),))
        c['exists'] = bool(row)
        if row:
            c['course_id'] = row['id']
        for s in c.get('sessions') or []:
            if not row:
                continue
            hit = db.q1("""SELECT id FROM sessions WHERE course_id = ? AND title = ?
                           AND date = ? AND start = ?""",
                        (row['id'], s['title'], s['date'], s['start']))
            s['exists'] = bool(hit)
            if hit:
                s['session_id'] = hit['id']

    return {'root': root, 'manifest': manifest, 'issues': issues, 'stats': stats}


# ---------------------------------------------------------------- 报告另存

def save_report(body):
    """把报告直接写到用户选的路径，不经浏览器下载。

    浏览器模式下这条路径不可用：一个 GET 就能触发任意路径写入的话，
    别的网页放个 <img src=...> 就够了。这里走 POST，且受 Origin 校验保护。
    """
    _require_desktop()
    sid = (body.get('session_id') or '').strip()
    fmt = (body.get('format') or 'docx').lower()
    target = (body.get('path') or '').strip()
    if not sid or not target:
        errors.fail('VALIDATION_FAILED', '需要 session_id 与 path')

    if os.path.isdir(target):
        errors.fail('VALIDATION_FAILED', '目标是目录，不是文件：%s' % target, 'path')
    parent = os.path.dirname(os.path.abspath(target))
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            errors.fail('VALIDATION_FAILED', '无法创建目录 %s：%s' % (parent, exc), 'path')

    out = m7_report.get_report(sid, fmt)
    if isinstance(out, dict) and 'path' in out:
        with open(out['path'], 'rb') as src:
            data = src.read()
        content_type = out.get('content_type')
        suggested = out.get('filename')
    elif isinstance(out, dict) and 'html' in out:
        data = out['html'].encode('utf-8')
        content_type = 'text/html; charset=utf-8'
        suggested = out.get('filename')
    elif isinstance(out, dict):
        # format=json 时 get_report 直接回报告结构体，没有文件产物
        data = json.dumps(out, ensure_ascii=False, indent=2).encode('utf-8')
        content_type = 'application/json; charset=utf-8'
        suggested = '%s.json' % sid
    else:
        raise errors.ApiError('INTERNAL', '报告生成返回了无法识别的结果')

    try:
        with open(target, 'wb') as dst:
            dst.write(data)
    except OSError as exc:
        errors.fail('VALIDATION_FAILED', '写文件失败：%s' % exc, 'path')

    db.audit('report.save', sid, detail={'format': fmt, 'path': target,
                                         'bytes': len(data), 'id': uuid.uuid4().hex[:8]})
    return {'saved': target, 'bytes': len(data), 'content_type': content_type,
            'suggested': suggested}


# ---------------------------------------------------------------- 退出

def quit_app(body=None):
    if not STATE['enabled']:
        raise errors.ApiError('NOT_IMPLEMENTED', '浏览器模式下请直接关闭页面')
    body = body or {}
    if body.get('confirm') is False:
        errors.fail('VALIDATION_FAILED', '退出需确认')
    cb = STATE['quit_cb']
    if not cb:
        raise errors.ApiError('INTERNAL', '未注册退出回调')
    # 先回包再退：不然前端拿到的是 connection reset，看起来像崩溃
    threading.Timer(0.4, cb).start()
    return {'ok': True, 'message': '正在退出'}
