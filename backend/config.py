"""config.py — 运行配置

所有可调项集中在这里，支持环境变量覆盖（部署时不必改代码）。
刻意保持"零依赖"：只用标准库与 os.environ。
"""
import os
import shutil
import sys

# ---------------------------------------------------------------- 路径
#
# 三种形态共用这一份配置：
#   源码运行      BACKEND_DIR = <项目>/software/backend，数据在 <项目>/software/data
#   打包成 exe    资源随 _MEIPASS 解出（只读），数据落 %LOCALAPPDATA%\\EvalConsole\\data
#   便携模式      exe 同级存在可写 data\\ 目录，优先写在那里（拷 U 盘就能带走）

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
SOFTWARE_DIR = os.path.dirname(BACKEND_DIR)

# PyInstaller 打包后 __file__ 指向 _MEIPASS 下的虚拟路径，静态资源也在那里
FROZEN = bool(getattr(sys, 'frozen', False))
RESOURCE_DIR = getattr(sys, '_MEIPASS', SOFTWARE_DIR)
FRONTEND_DIR = os.path.join(RESOURCE_DIR, 'frontend')

APP_NAME = 'EvalConsole'


def _default_data_dir():
    env = os.environ.get('EVAL_DATA_DIR')
    if env:
        return env
    if not FROZEN:
        return os.path.join(SOFTWARE_DIR, 'data')
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    portable = os.path.join(exe_dir, 'data')
    if os.path.isdir(portable) and os.access(portable, os.W_OK):
        return portable
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, APP_NAME, 'data')


# 数据目录：默认放在 software/data，可用 EVAL_DATA_DIR 指到别处（如大盘）
DATA_DIR = _default_data_dir()
DB_PATH = os.environ.get('EVAL_DB') or os.path.join(DATA_DIR, 'eval.db')
MEDIA_DIR = os.path.join(DATA_DIR, 'media')
EXPORT_DIR = os.path.join(DATA_DIR, 'exports')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
# 运行时状态（实际端口、窗口 URL），第二个实例靠它找到已在跑的窗口
RUNTIME_FILE = os.path.join(DATA_DIR, 'runtime.json')
# 浏览器内核配置（Edge app 模式的 user-data-dir）。刻意放在 data/ 之外：
# 20 MB 的浏览器缓存不该混进业务数据备份里
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(DATA_DIR)), 'ui-profile')

# 桌面模式：由 desktop/main.py 置 1，前端据此显示原生按钮（选目录／另存为）
DESKTOP = os.environ.get('EVAL_DESKTOP') == '1'

# ---------------------------------------------------------------- 服务

HOST = os.environ.get('EVAL_HOST', '127.0.0.1')
PORT = int(os.environ.get('EVAL_PORT', '8000'))

# 原型期不做鉴权：接口已按 Authorization: Bearer 预留，置 1 即校验
AUTH_REQUIRED = os.environ.get('EVAL_AUTH') == '1'
AUTH_TOKEN = os.environ.get('EVAL_TOKEN', 'dev-token')

# ---------------------------------------------------------------- 跨站防护
#
# 桌面模式（或任何 127.0.0.1 单机部署）下，浏览器里的任意网页都能向本机端口发
# "简单请求"——表单 POST 不需要预检，读不到响应也能把数据改掉。因此：
#   ALLOW_ANY_ORIGIN=False 时不发 Access-Control-Allow-Origin: *，
#   并且校验写操作的 Origin / Sec-Fetch-Site，跨站一律 403。
# 局域网演示（--host 0.0.0.0）才放开成 *，否则投屏机上取不到数据。
ALLOW_ANY_ORIGIN = os.environ.get('EVAL_CORS_ANY') == '1'
ALLOWED_ORIGINS = set()          # 由 app.start_server() 按实际端口填入

# ---------------------------------------------------------------- 限制

MAX_JSON_BYTES = 64 * 1024                 # 契约规定 64 KiB
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # multipart 直传上限 2 GiB
CHUNK = 1024 * 256

# 留存天数（与文档一致：4K 原片 7 天、48k 音频 30 天、派生 30 天）
RETENTION = {'video': 7, 'audio': 30, 'slides': None, 'goals': None}

# ---------------------------------------------------------------- 模型网关

# provider：stub（默认，确定性占位，不联网）/ openai（OpenAI 兼容端点）/ none（不可用）
MODEL_PROVIDER = os.environ.get('MODEL_PROVIDER', 'stub').lower()
MODEL_BASE_URL = os.environ.get('MODEL_BASE_URL', '')
MODEL_API_KEY = os.environ.get('MODEL_API_KEY', '')
MODEL_NAMES = {
    'asr': os.environ.get('MODEL_ASR', 'asr-zh-v4'),
    'ocr': os.environ.get('MODEL_OCR', 'ocr-page-v2'),
    'embed': os.environ.get('MODEL_EMBED', 'emb-1024'),
    'llm': os.environ.get('MODEL_LLM', 'llm-chat'),
    'vlm': os.environ.get('MODEL_VLM', 'vlm-frame-v3'),
}
MODEL_TIMEOUT = int(os.environ.get('MODEL_TIMEOUT', '60'))
MODEL_RETRY = int(os.environ.get('MODEL_RETRY', '3'))
CACHE_TTL_DAYS = 7

# 价目（元）。仅为成本可见性服务，真实单价按合同改这里即可
PRICING = {
    'asr':   {'per_minute': 0.012},
    'ocr':   {'per_page': 0.03},
    'embed': {'per_1k_tokens': 0.0005},
    'llm':   {'per_1k_in': 0.008, 'per_1k_out': 0.024},
    'vlm':   {'per_image': 0.004},
}

# ---------------------------------------------------------------- 外部工具

# 转码与抽帧依赖 ffmpeg；没有就跳过该阶段并显式标记 degraded，不假装做过
FFMPEG = os.environ.get('FFMPEG_BIN') or shutil.which('ffmpeg')
FFPROBE = os.environ.get('FFPROBE_BIN') or shutil.which('ffprobe')


def ensure_dirs():
    for d in (DATA_DIR, MEDIA_DIR, EXPORT_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)


def describe():
    """给 /api/health 与启动日志用的一行摘要"""
    caps = {}
    for cap in ('asr', 'ocr', 'embed', 'llm', 'vlm'):
        if MODEL_PROVIDER == 'openai' and MODEL_BASE_URL and MODEL_API_KEY:
            caps[cap] = 'ok'
        elif MODEL_PROVIDER == 'stub':
            caps[cap] = 'degraded'      # 能调通，但产出是占位，不是真推理
        else:
            caps[cap] = 'unavailable'
    return {
        'provider': MODEL_PROVIDER,
        'capabilities': caps,
        'ffmpeg': bool(FFMPEG),
    }
