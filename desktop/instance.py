"""desktop/instance.py — 单实例与运行时状态

双击第二次不该起第二套后端（两个进程写同一个 sqlite，用户看到两个窗口各说各话）。
做法很朴素：第一个进程把自己的端口写进 data/runtime.json，第二个进程读到后先探活，
活着就把已有地址交给窗口，自己不建库、不占端口。
"""
import json
import os
import urllib.error
import urllib.request

import config


def read_runtime():
    try:
        with open(config.RUNTIME_FILE, 'r', encoding='utf-8') as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and doc.get('port'):
            return doc
    except (OSError, ValueError):
        pass
    return None


def probe(url, timeout=1.5):
    """真探一次，不信文件：进程被强杀时 runtime.json 会留在盘上。"""
    try:
        with urllib.request.urlopen(url + '/api/health', timeout=timeout) as resp:
            raw = resp.read(4096)
        doc = json.loads(raw.decode('utf-8'))
        return doc.get('status') == 'ok'
    except (urllib.error.URLError, OSError, ValueError):
        return False


def write_runtime(port, shell):
    doc = {
        'pid': os.getpid(),
        'port': port,
        'url': 'http://127.0.0.1:%d/' % port,
        'shell': shell,
        'started_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
    }
    try:
        os.makedirs(os.path.dirname(config.RUNTIME_FILE), exist_ok=True)
        with open(config.RUNTIME_FILE, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return doc


def clear_runtime():
    try:
        os.remove(config.RUNTIME_FILE)
    except OSError:
        pass
