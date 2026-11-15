# desktop/ — 桌面外壳

`backend/` 是内容，这一层只负责"把它装进一个看起来像软件的窗口"。
设计取舍与踩坑记录见 `../docs/桌面版说明.md`。

| 文件 | 职责 | 关键点 |
|---|---|---|
| `main.py` | 入口：起服务 → 开窗口 → 等退出 → 收尾 | 端口先试 8000 再让系统挑；日志写 `data/logs/desktop.log` |
| `shell.py` | 窗口形态 | `pywebview` → `msedge --app` → 默认浏览器，三级降级；`focus_window` 拉前台；`close_windows_by_title` 收尾 |
| `instance.py` | 单实例 | `data/runtime.json` + 真探活（不信文件，信 `/api/health`） |

## 跑法

```bash
python desktop/main.py                  # 起窗口
python desktop/main.py --no-window      # 只起服务，排障／自测
python desktop/main.py --port 8000      # 指定端口
python desktop/main.py --shell browser  # 强制用默认浏览器
python desktop/main.py --reset-db --seed-demo
```

## 生命周期（改这里的代码前先看这段）

窗口存活**不看浏览器进程**：Edge 的 `--app` 启动器常把窗口交给已有浏览器进程后立刻返回，
盯 `Popen` 会让后端先于窗口退出。判据是页面的一手事实：

```
GET  /api/desktop/ping   每 20 秒一次，页面还在
POST /api/desktop/bye    页面关闭/刷新时发；只挂 3 秒倒计时，重载即抵消
```

看门狗收到关闭信号后还要复核"窗口是否仍存在"，最多 8 次（16 秒）；
窗口一直在就撤销退出（刷新、页面休眠都会造成误报）。5 分钟无 ping 则兜底退出。

退出顺序：停 HTTP 服务 → `WM_CLOSE` 关窗口 → 删 `runtime.json` → 退出码 0。
