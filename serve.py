#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serve.py — 本地静态服务

用法：
    python serve.py                 # 默认 http://127.0.0.1:5500
    python serve.py --port 8080     # 换端口
    python serve.py --host 0.0.0.0  # 允许局域网访问（评审投屏可多机查看）

只做三件事：托管 frontend/ 静态文件、禁用缓存（改代码后刷新即生效）、
把根路径重定向到 frontend/index.html。不需要任何第三方库。
"""

import argparse
import http.server
import os
import socketserver
import sys
import webbrowser

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        # 开发期禁用缓存，避免改了 css/js 还看到旧版
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, fmt, *args):
        # 只打错误，避免刷屏
        if args and str(args[0]).startswith(("4", "5")):
            sys.stderr.write("  %s\n" % (fmt % args))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser(description="培训教学质量评估系统 · 本地静态服务")
    ap.add_argument("--port", type=int, default=5500, help="端口，默认 5500")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    ap.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    args = ap.parse_args()

    if not os.path.isdir(ROOT):
        sys.exit("找不到 frontend/ 目录：%s" % ROOT)

    url = "http://%s:%d/" % ("127.0.0.1" if args.host == "0.0.0.0" else args.host, args.port)

    with Server((args.host, args.port), Handler) as httpd:
        print("培训教学质量评估系统 · 控制台")
        print("  目录  %s" % ROOT)
        print("  地址  %s" % url)
        print("  退出  Ctrl+C")
        if not args.no_open:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")


if __name__ == "__main__":
    main()
