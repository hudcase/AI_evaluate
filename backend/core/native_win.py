"""core/native_win.py — Windows 原生对话框（纯 ctypes，无第三方依赖）

为什么需要它：浏览器给不了"真实路径"。`<input type=file>` 拿到的是 File 对象，
Chrome 会把路径伪装成 `C:\\fakepath\\...`；而本系统的入库策略是**就地登记**——
几十 GB 的 4K 原片只记路径、不搬字节，路径必须是真路径。所以桌面版把选择文件这件事
交给后端进程（它就在本机，有完整文件系统权限），前端只负责发个请求。

实现用 comdlg32 / shell32 的老接口（GetOpenFileNameW / SHBrowseForFolderW）：
它们从 Win2000 起就没变过，比用 ctypes 手搓 IFileDialog 的 COM vtable 稳得多，
代价是文件夹选择框是经典样式（带 BIF_EDITBOX，可以直接粘路径）。
"""
import ctypes
import os
import sys

IS_WIN = sys.platform == 'win32'

# ---- 常量 ----
BIF_RETURNONLYFSDIRS = 0x0001
BIF_EDITBOX = 0x0010
BIF_NEWDIALOGSTYLE = 0x0040
BIF_USENEWUI = BIF_NEWDIALOGSTYLE | BIF_EDITBOX

BFFM_INITIALIZED = 1
BFFM_SETSELECTIONW = 0x0467          # WM_USER + 103

OFN_READONLY = 0x0001
OFN_OVERWRITEPROMPT = 0x0002
OFN_HIDEREADONLY = 0x0004
OFN_NOCHANGEDIR = 0x0008
OFN_PATHMUSTEXIST = 0x0800
OFN_FILEMUSTEXIST = 0x1000
OFN_ALLOWMULTISELECT = 0x0200
OFN_EXPLORER = 0x080000

MAX_PATH_LONG = 65536

FILE_FILTER_ALL = '所有文件|*.*'


class _BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ('hwndOwner', ctypes.c_void_p),
        ('pidlRoot', ctypes.c_void_p),
        ('pszDisplayName', ctypes.c_wchar_p),
        ('lpszTitle', ctypes.c_wchar_p),
        ('ulFlags', ctypes.c_uint),
        ('lpfn', ctypes.c_void_p),
        ('lParam', ctypes.c_void_p),
        ('iImage', ctypes.c_int),
    ]


class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ('lStructSize', ctypes.c_uint32),
        ('hwndOwner', ctypes.c_void_p),
        ('hInstance', ctypes.c_void_p),
        ('lpstrFilter', ctypes.c_wchar_p),
        ('lpstrCustomFilter', ctypes.c_wchar_p),
        ('nMaxCustFilter', ctypes.c_uint32),
        ('nFilterIndex', ctypes.c_uint32),
        ('lpstrFile', ctypes.c_void_p),
        ('nMaxFile', ctypes.c_uint32),
        ('lpstrFileTitle', ctypes.c_void_p),
        ('nMaxFileTitle', ctypes.c_uint32),
        ('lpstrInitialDir', ctypes.c_wchar_p),
        ('lpstrTitle', ctypes.c_wchar_p),
        ('Flags', ctypes.c_uint32),
        ('nFileOffset', ctypes.c_uint16),
        ('nFileExtension', ctypes.c_uint16),
        ('lpstrDefExt', ctypes.c_wchar_p),
        ('lCustData', ctypes.c_void_p),
        ('lpfnHook', ctypes.c_void_p),
        ('lpTemplateName', ctypes.c_wchar_p),
        ('pvReserved', ctypes.c_void_p),
        ('dwReserved', ctypes.c_uint32),
        ('FlagsEx', ctypes.c_uint32),
    ]


def available():
    return IS_WIN


def _owner_hwnd():
    """把前台窗口当作对话框的 owner，否则对话框可能弹在应用窗口后面。
    拿不到就传 NULL——顶多不置顶，不会崩。"""
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def _filter_string(filters):
    """['视频|*.mp4;*.mov', ...] → OPENFILENAME 需要的 \\0 分隔双结尾串"""
    parts = list(filters or []) + [FILE_FILTER_ALL]
    s = ''
    for f in parts:
        name, _, pat = f.partition('|')
        if not pat:
            name, pat = '所有文件', '*.*'
        s += name + '\x00' + pat + '\x00'
    return s + '\x00'


# ---------------------------------------------------------------- 选文件夹

def pick_folder(title='选择文件夹', initial=None):
    """返回绝对路径；用户取消返回 None。"""
    if not IS_WIN:
        return None
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32

    buf = ctypes.create_unicode_buffer(MAX_PATH_LONG)
    bi = _BROWSEINFOW()
    bi.hwndOwner = _owner_hwnd()
    bi.pszDisplayName = ctypes.cast(buf, ctypes.c_wchar_p)
    bi.lpszTitle = title
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_USENEWUI
    bi.lpfn = None
    bi.lParam = None

    _cb = None
    if initial and os.path.isdir(initial):
        # BFFM_INITIALIZED 回调里把初始目录塞进去，否则每次都要从"此电脑"点下去
        _proto = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_void_p, ctypes.c_void_p)

        def _on_msg(hwnd, msg, _lp, _data, _path=initial):
            if msg == BFFM_INITIALIZED:
                shell32.SendMessageW(ctypes.c_void_p(hwnd), BFFM_SETSELECTIONW,
                                    ctypes.c_void_p(1),
                                    ctypes.c_wchar_p(_path))
            return 0

        _cb = _proto(_on_msg)          # 必须保持引用，否则回调被 GC 掉会硬崩
        bi.lpfn = ctypes.cast(_cb, ctypes.c_void_p)
        bi.lParam = None

    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return None
    try:
        out = ctypes.create_unicode_buffer(MAX_PATH_LONG)
        if not shell32.SHGetPathFromIDListW(ctypes.c_void_p(pidl), out):
            return None
        return out.value or None
    finally:
        ole32.CoTaskMemFree(ctypes.c_void_p(pidl))


# ---------------------------------------------------------------- 选文件

def _open_save(title, initial_dir, filename, filters, default_ext, save, multiselect):
    if not IS_WIN:
        return [] if multiselect else None
    comdlg32 = ctypes.windll.comdlg32

    buf = ctypes.create_unicode_buffer(MAX_PATH_LONG)
    if filename:
        buf.value = filename

    ofn = _OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    ofn.hwndOwner = _owner_hwnd()
    ofn.lpstrFilter = _filter_string(filters)
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, ctypes.c_void_p)
    ofn.nMaxFile = MAX_PATH_LONG
    ofn.lpstrInitialDir = initial_dir if (initial_dir and os.path.isdir(initial_dir)) else None
    ofn.lpstrTitle = title
    ofn.lpstrDefExt = default_ext or None
    ofn.Flags = OFN_EXPLORER | OFN_NOCHANGEDIR | OFN_HIDEREADONLY
    if save:
        ofn.Flags |= OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST
        ok = comdlg32.GetSaveFileNameW(ctypes.byref(ofn))
    else:
        ofn.Flags |= OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
        if multiselect:
            ofn.Flags |= OFN_ALLOWMULTISELECT
        ok = comdlg32.GetOpenFileNameW(ctypes.byref(ofn))

    if not ok:
        return [] if multiselect else None

    raw = buf.value
    if not multiselect:
        return raw
    # 多选时返回 "目录\0文件1\0文件2..."；只有一个文件时直接就是完整路径
    parts = [p for p in raw.split('\x00') if p]
    if len(parts) <= 1:
        return [parts[0]] if parts else []
    base = parts[0]
    return [os.path.join(base, p) for p in parts[1:]]


def pick_open(title='选择文件', initial_dir=None, filters=None, multiselect=True):
    return _open_save(title, initial_dir, None, filters, None, False, multiselect)


def pick_files(title='选择文件', initial_dir=None, filters=None, multiselect=True):
    """统一返回列表；取消返回 []。"""
    out = pick_open(title, initial_dir, filters, multiselect)
    if not out:
        return []
    return out if isinstance(out, list) else [out]


def save_file(title='另存为', initial_dir=None, filename=None, filters=None,
              default_ext=None):
    return _open_save(title, initial_dir, filename, filters, default_ext, True, False)


# ---------------------------------------------------------------- 其他

def reveal(path):
    """在资源管理器里定位文件／文件夹。失败返回 False（不抛，调用方只提示）。"""
    if not IS_WIN or not path:
        return False
    target = os.path.normpath(path)
    try:
        if os.path.isdir(target):
            os.startfile(target)                    # noqa: S606  —— 目录直接打开
            return True
        if os.path.exists(target):
            import subprocess
            subprocess.Popen(['explorer', '/select,', target])
            return True
    except Exception:
        return False
    return False


def message_box(text, title='培训教学质量评估系统', style=0x10):
    """0x10 = MB_ICONERROR；打包后没有控制台，致命错误只能靠它露出来。"""
    if not IS_WIN:
        sys.stderr.write('%s: %s\n' % (title, text))
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, style)
    except Exception:
        sys.stderr.write('%s: %s\n' % (title, text))
