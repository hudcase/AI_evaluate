/**
 * config.js — 运行配置
 *
 * 两种跑法，只差这一处：
 *
 *   A. 前后端一起跑（推荐）
 *      双击 software/start.bat，或 python backend/app.py
 *      后端同时托管前端页面与 /api，同源，不需要 CORS。
 *      此时 useMock = false、apiBase = ''（同源相对路径）。
 *
 *   B. 只跑前端（没有 Python 环境时）
 *      双击 software/frontend/index.html，或 python serve.py
 *      此时把 useMock 改成 true，数据来自 mock.js。
 *
 *   若前后端分端口（前端 5500、后端 8000），把 apiBase 写成 'http://127.0.0.1:8000'；
 *   本后端默认 Access-Control-Allow-Origin: *，不需额外配置。
 */
window.APP_CONFIG = {
  // 后端地址。'' = 与页面同源；分端口部署时写完整地址
  apiBase: '',

  // true = 使用 mock.js 中的演示数据；false = 走真实 HTTP 请求
  useMock: false,

  // 请求超时（毫秒）
  timeout: 15000,

  // 任务轮询间隔（毫秒）；连续无进展时前端会自动降频
  pollInterval: 2000,

  // 界面版本，显示在顶栏徽标与页脚
  version: 'v0.3.0',

  // 默认选中的场次；留空 = 自动挑一场有分的（id 写死会在换库／清库后指向不存在的场次）
  // 2026-11-05：默认指向真实课例「AI相关产业及华为转型分享」（S-20261105-05，有真实 m4a），
  // 让打开前端第一眼就能看到真实数据的入库／处理／门禁结果；不存在时 buildSessions 会自动回落到有分场次。
  defaultSessionId: 'S-20261105-05'
};
