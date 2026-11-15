/**
 * router.js — hash 路由
 *
 * 用 hash（#/indicators）而非 History API：静态托管时无需服务端 rewrite，
 * 双击 index.html 也能正常工作。
 */
(function (global) {
  'use strict';

  function Router(routes, onRender) {
    this.routes = routes;
    this.onRender = onRender;
    this.current = null;
  }

  Router.prototype.parse = function () {
    var raw = (location.hash || '').replace(/^#\/?/, '');
    var path = raw.split('?')[0] || 'overview';
    for (var i = 0; i < this.routes.length; i++) {
      if (this.routes[i].path === path) return this.routes[i];
    }
    return this.routes[0];
  };

  Router.prototype.start = function () {
    var self = this;
    window.addEventListener('hashchange', function () { self.render(); });
    this.render();
  };

  Router.prototype.go = function (path) {
    if (location.hash === '#/' + path) { this.render(); return; }
    location.hash = '#/' + path;
  };

  Router.prototype.render = function () {
    var route = this.parse();
    this.current = route;
    this.onRender(route);
  };

  global.Router = Router;
})(window);
