/**
 * app.js — 壳层：导航、场次选择、路由装配
 *
 * 路由表在 ROUTES 中定义，新增页面只需在此加一行并在 views/ 下实现，
 * router 与导航会自动生成。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h, CFG = global.APP_CONFIG;

  /* 页面只保留标题：标题下面不再挂副标题（页面用途由卡片与表头自解释）。 */
  var ROUTES = [
    { path: 'overview', title: '总览', view: 'overview', group: null },
    { path: 'courses', title: 'M1 建档', view: 'courses', group: '处理流程' },
    { path: 'media', title: 'M2 数据接入', view: 'media', group: '处理流程' },
    { path: 'governance', title: 'M3 数据治理', view: 'governance', group: '处理流程' },
    { path: 'gateway', title: 'M4 模型', view: 'gateway', group: '处理流程', cloud: true },
    { path: 'indicators', title: 'M5 指标计算', view: 'indicators', group: '处理流程' },
    { path: 'evaluation', title: 'M6 合成与一致性', view: 'evaluation', group: '处理流程' },
    { path: 'report', title: 'M7 报告与审计', view: 'report', group: '处理流程' },
    { path: 'config', title: '指标配置', view: 'config', group: '配置' }
  ];

  var App = {
    state: { sessionId: CFG.defaultSessionId, sessions: [] },
    routes: ROUTES,
    setSession: function (id) {
      if (id === App.state.sessionId) return;
      App.state.sessionId = id;
      var sel = document.getElementById('session-select');
      if (sel) sel.value = id;
      renderCurrent();
    },
    go: function (path) { router.go(path); }
  };

  var router = new global.Router(ROUTES, function (route) {
    applyRoute(route);
  });

  function applyRoute(route) {
    document.getElementById('page-title').textContent = route.title;

    // 导航高亮
    Array.prototype.forEach.call(document.querySelectorAll('.nav-item'), function (a) {
      a.classList.toggle('is-active', a.dataset.path === route.path);
    });

    var host = document.getElementById('view');
    var view = global.Views[route.view];
    if (!view) {
      UI.clear(host).appendChild(UI.card({ body: UI.emptyState('页面未实现', route.view) }));
      return;
    }
    try {
      view(host, { sessionId: App.state.sessionId, setSession: App.setSession, go: App.go });
    } catch (err) {
      console.error('[view error]', route.path, err);
      UI.clear(host).appendChild(UI.errorBox({
        code: 'RENDER_ERROR', message: err.message
      }, function () { applyRoute(route); }));
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function renderCurrent() {
    applyRoute(router.current || ROUTES[0]);
  }

  /* -------------------------------------------------------------- 导航 */

  function buildNav() {
    var nav = document.getElementById('nav');
    var lastGroup = null;
    ROUTES.forEach(function (r) {
      if (r.group && r.group !== lastGroup) {
        nav.appendChild(h('div', { class: 'nav-group', text: r.group }));
        lastGroup = r.group;
      }
      nav.appendChild(h('a', {
        class: 'nav-item' + (r.cloud ? ' nav-cloud' : ''),
        href: '#/' + r.path,
        dataset: { path: r.path }
      },
        h('span', { class: 'nav-dot' }),
        h('span', { class: 'nav-label', text: r.title }),
        r.cloud ? h('span', { class: 'nav-badge', text: '云' }) : null
      ));
    });
  }

  /* -------------------------------------------------------------- 场次 */

  function buildSessions() {
    var sel = document.getElementById('session-select');
    global.Api.getOverview().then(function (d) {
      App.state.sessions = d.sessions;
      UI.clear(sel);
      d.sessions.forEach(function (s) {
        sel.appendChild(h('option', {
          value: s.id,
          // 完整编号：之前用 id.slice(-9)，把年份头部吃掉两位，显示成 "261105-04"
          text: s.id.replace(/^S-/, '') + ' · ' + s.title,
          selected: s.id === App.state.sessionId
        }));
      });
      if (!d.sessions.some(function (s) { return s.id === App.state.sessionId; }) && d.sessions.length) {
        /* 默认落在一场"有分可看"的场次：接口按日期倒序，最新的那场往往还在处理中，
           一进来就是 0 分／证据不足，容易被读成系统坏了。 */
        var pick = d.sessions.filter(function (s) { return s.audio !== null; })[0] || d.sessions[0];
        App.state.sessionId = pick.id;
        sel.value = App.state.sessionId;
        /* 场次列表是异步到的，当前视图可能已经用空 ID 渲染过一遍（报"请求失败"）。
           这里把视图再渲染一次，别让首屏错误停留到用户手动切换。 */
        renderCurrent();
      }
    }).catch(function () {
      sel.appendChild(h('option', { text: '（场次加载失败）' }));
    });

    sel.addEventListener('change', function () { App.setSession(sel.value); });
  }

  /* -------------------------------------------------------------- 启动 */

  function boot() {
    buildNav();
    buildSessions();

    var badge = document.getElementById('env-badge');
    badge.textContent = CFG.useMock ? '演示数据' : '已连接后端';
    badge.className = 'env-badge ' + (CFG.useMock ? 'env-mock' : 'env-live');
    badge.title = CFG.useMock
      ? '使用 mock.js 演示数据；改 config.js 的 useMock=false 接入真实后端'
      : '数据来自 ' + CFG.apiBase;

    document.getElementById('footer-time').textContent = '加载于 ' + UI.fmt.datetime(new Date().toISOString());

    /* 桌面能力探测：拿到 desktop=true 才显示"选文件夹／另存为"这类原生按钮。
       探测失败按浏览器模式处理，界面不会因此打不开。 */
    if (global.Desktop) {
      global.Desktop.init().then(function (info) {
        if (info && info.desktop) markDesktop(info);
      });
    }

    router.start();
  }

  /* 桌面版标识与退出入口。浏览器模式没有"退出应用"这回事，所以按钮只在桌面版出现。 */
  function markDesktop(info) {
    document.body.classList.add('is-desktop');
    startLifecycle();

    var badge = document.getElementById('env-badge');
    if (badge) {
      badge.textContent = '桌面版';
      badge.className = 'env-badge env-live';
      badge.title = '数据目录 ' + (info.data_dir || '—') + '\n端口 ' + (info.port || '—')
        + '\n窗口 ' + (info.shell || '—');
    }

    var right = document.querySelector('.topbar-right');
    if (!right) return;
    right.appendChild(h('button', {
      class: 'btn btn-ghost btn-sm topbar-quit', text: '退出',
      title: '退出应用（服务与窗口一起关闭）',
      onclick: function () {
        UI.confirmDialog({
          title: '退出应用',
          text: '将关闭窗口并停止本机服务。已入库的数据与报告都在数据目录里，不会丢失。',
          okText: '退出'
        }).then(function (ok) {
          if (!ok) return;
          global.Desktop.quit().catch(function () { /* 服务已停，请求会断，属正常 */ });
          document.body.classList.add('is-quitting');
        });
      }
    }));
  }

  /* 页面生命周期：后端靠这两条信号判断"窗口还在不在"。
     为什么不盯浏览器进程——Edge 的 --app 启动器会把窗口交给已有浏览器进程后立刻返回，
     盯进程会让后端先于窗口退出。 */
  function startLifecycle() {
    setInterval(function () {
      fetch('/api/desktop/ping', { cache: 'no-store' }).catch(function () { /* 后端已停就算了 */ });
    }, 20000);

    window.addEventListener('pagehide', function () {
      try { navigator.sendBeacon('/api/desktop/bye', '{}'); } catch (e) { /* 老浏览器没有 sendBeacon */ }
    });
  }

  global.App = App;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})(window);
