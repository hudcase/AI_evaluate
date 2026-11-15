/**
 * ui.js — 轻量组件层
 *
 * 只做三件事：建 DOM、套样式、把数据变成可读的展示。不含任何业务判断。
 * 全部返回原生节点，视图负责挂载。
 */
(function (global) {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';

  /* -------------------------------------------------------------- DOM */

  function h(tag, attrs) {
    var el = document.createElement(tag);
    var children = Array.prototype.slice.call(arguments, 2);
    apply(el, attrs);
    append(el, children);
    return el;
  }

  function svg(tag, attrs) {
    var el = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (attrs[k] === null || attrs[k] === undefined) return;
        if (k === 'text') { el.textContent = attrs[k]; return; }
        el.setAttribute(k, attrs[k]);
      });
    }
    return el;
  }

  function apply(el, attrs) {
    if (!attrs) return;
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class' || k === 'className') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected') el[k] = v;
      else el.setAttribute(k, v);
    });
  }

  function append(el, children) {
    children.forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      if (Array.isArray(c)) append(el, c);
      else if (typeof c === 'string' || typeof c === 'number') el.appendChild(document.createTextNode(String(c)));
      else el.appendChild(c);
    });
  }

  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* -------------------------------------------------------------- 格式化 */

  var fmt = {
    num: function (v, d) {
      if (v === null || v === undefined || isNaN(v)) return '—';
      return Number(v).toFixed(d === undefined ? 1 : d);
    },
    pct: function (v, d) {
      if (v === null || v === undefined || isNaN(v)) return '—';
      return (Number(v) * 100).toFixed(d === undefined ? 0 : d) + '%';
    },
    signed: function (v, d) {
      if (v === null || v === undefined) return '—';
      return (v > 0 ? '+' : '') + Number(v).toFixed(d === undefined ? 1 : d);
    },
    bytes: function (b) {
      if (b === null || b === undefined) return '—';
      var u = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0, v = Number(b);
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
      return v.toFixed(v >= 100 || i === 0 ? 0 : 1) + ' ' + u[i];
    },
    /** 秒 → mm:ss */
    time: function (sec) {
      if (sec === null || sec === undefined) return '—';
      var m = Math.floor(sec / 60), s = Math.round(sec % 60);
      return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    },
    datetime: function (iso) {
      if (!iso) return '—';
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      var p = function (n) { return n < 10 ? '0' + n : n; };
      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
        ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    },
    /** 原始量 + 单位，按量纲不同保留不同小数位 */
    raw: function (v, unit) {
      if (v === null || v === undefined) return '—';
      if (unit === 'ratio' || unit === '0–1' || unit === '得分率') return Number(v).toFixed(2);
      if (unit === '字/分' || unit === '次/分' || unit === '次/课时') return Number(v).toFixed(0);
      return String(v);
    }
  };

  /* -------------------------------------------------------------- 徽标 */

  var TONE_TEXT = {
    ok: '通过', warn: '注意', danger: '阻断', info: '提示', mute: '—',
    aligned: '一致', divergent: '证据不一致', insufficient: '证据不足',
    processing: '处理中', created: '待接入', pass: 'pass', reject: 'reject'
  };

  function badge(text, tone) {
    return h('span', { class: 'badge badge-' + (tone || 'mute'), text: text });
  }

  function statusBadge(status) {
    var map = {
      ok: ['可用', 'ok'], divergent: ['证据不一致', 'warn'], insufficient: ['证据不足', 'danger'],
      processing: ['处理中', 'info'], created: ['待接入', 'mute'],
      pass: ['pass', 'ok'], warn: ['warn', 'warn'], reject: ['reject', 'danger'],
      succeeded: ['已完成', 'ok'], running: ['运行中', 'info'], queued: ['排队', 'mute'],
      failed: ['失败', 'danger'], aligned: ['一致', 'ok']
    };
    var m = map[status] || [status, 'mute'];
    return badge(m[0], m[1]);
  }

  /* -------------------------------------------------------------- 容器 */

  function card(opts) {
    opts = opts || {};
    var el = h('section', { class: 'card' + (opts.className ? ' ' + opts.className : '') });
    if (opts.title || opts.sub || opts.actions) {
      el.appendChild(h('header', { class: 'card-head' },
        h('div', {},
          opts.title ? h('h2', { class: 'card-title', text: opts.title }) : null,
          opts.sub ? h('p', { class: 'card-sub', text: opts.sub }) : null
        ),
        opts.actions ? h('div', { class: 'card-actions' }, opts.actions) : null
      ));
    }
    if (opts.body) el.appendChild(h('div', { class: 'card-body' }, opts.body));
    list(opts.children || []).forEach(function (c) { el.appendChild(c); });
    return el;
  }

  function list(v) { return Array.isArray(v) ? v : (v ? [v] : []); }

  function sectionHead(title, sub, actions) {
    return h('div', { class: 'section-head' },
      h('div', {},
        h('h2', { class: 'section-title', text: title }),
        sub ? h('p', { class: 'section-sub', text: sub }) : null),
      actions || null);
  }

  function grid(cols, children, gap) {
    return h('div', { class: 'grid grid-' + cols, style: gap ? { gap: gap } : null }, children);
  }

  /* -------------------------------------------------------------- 指标卡 */

  function stat(opts) {
    return h('div', { class: 'stat' + (opts.tone ? ' stat-' + opts.tone : '') },
      h('div', { class: 'stat-label', text: opts.label }),
      h('div', { class: 'stat-value' },
        h('span', { text: opts.value }),
        opts.unit ? h('em', { text: opts.unit }) : null),
      opts.note ? h('div', { class: 'stat-note', text: opts.note }) : null
    );
  }

  /* -------------------------------------------------------------- 表格 */

  function table(opts) {
    var cols = opts.columns;
    var wrap = h('div', { class: 'table-wrap' });
    var t = h('table', { class: 'table' + (opts.compact ? ' table-compact' : '') });

    var thead = h('thead', {}, h('tr', {}, cols.map(function (c) {
      return h('th', {
        class: (c.align === 'right' ? 'ta-r' : c.align === 'center' ? 'ta-c' : ''),
        style: c.width ? { width: c.width } : null,
        text: c.label
      });
    })));
    t.appendChild(thead);

    var tbody = h('tbody');
    if (!opts.rows || !opts.rows.length) {
      tbody.appendChild(h('tr', {}, h('td', {
        class: 'table-empty', colspan: cols.length,
        text: opts.empty || '暂无数据'
      })));
    } else {
      opts.rows.forEach(function (row, i) {
        var tr = h('tr', {
          class: (opts.rowClass ? opts.rowClass(row) : '') + (opts.onRowClick ? ' row-click' : ''),
          onclick: opts.onRowClick ? function () { opts.onRowClick(row); } : null
        });
        cols.forEach(function (c) {
          var v = c.render ? c.render(row, i) : row[c.key];
          var td = h('td', {
            class: (c.align === 'right' ? 'ta-r' : c.align === 'center' ? 'ta-c' : '') +
              (c.className ? ' ' + c.className : '')
          });
          if (v instanceof Node) td.appendChild(v);
          else td.textContent = (v === null || v === undefined || v === '') ? '—' : String(v);
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }
    t.appendChild(tbody);
    wrap.appendChild(t);
    if (opts.foot) wrap.appendChild(h('div', { class: 'table-foot', text: opts.foot }));
    return wrap;
  }

  /* -------------------------------------------------------------- 进度与分数 */

  /**
   * 按 indicator_config 的量尺把原始量折成 0–100 分项分。
   * 与服务端 core/membership.py 同构，只用于"补录时的即时预览"；
   * 落库的分数一律以服务端返回为准，界面不得自行给分。
   */
  function scale(ind, raw) {
    if (raw === null || raw === undefined || isNaN(raw)) return null;
    if (ind.scored === false) return null;
    var dir = ind.direction || ind.dir;
    var a = ind.a, b = ind.b, c = ind.c, d = ind.d;
    var mu;
    if (dir === 'level' || dir === 'combo') {
      mu = Math.max(0, Math.min(1, raw));
    } else if (dir === 'inc') {
      if (b === a) return null;
      mu = Math.max(0, Math.min(1, (raw - a) / (b - a)));
    } else if (dir === 'reverse') {
      if (b === a) return null;
      mu = 1 - Math.max(0, Math.min(1, (raw - a) / (b - a)));
    } else if (dir === 'interval') {
      if (raw < a || raw > d) mu = 0;
      else if (raw < b) mu = (raw - a) / (b - a);
      else if (raw <= c) mu = 1;
      else mu = (d - raw) / (d - c);
    } else {
      return null;
    }
    return Math.round(mu * 1000) / 10;
  }

  function bar(value, opts) {
    opts = opts || {};
    var has = value !== null && value !== undefined && !isNaN(value);
    var v = has ? Math.max(0, Math.min(100, value)) : 0;
    var tone = opts.tone || (v >= 75 ? 'high' : v >= 60 ? 'mid' : 'low');
    return h('div', { class: 'bar' + (opts.slim ? ' bar-slim' : '') },
      h('div', { class: 'bar-track' },
        h('div', { class: 'bar-fill bar-' + tone, style: { width: v + '%' } })),
      opts.label === false ? null : h('span', { class: 'bar-label', text: has ? v.toFixed(1) : '—' })
    );
  }

  function scoreChip(v) {
    if (v === null || v === undefined) return h('span', { class: 'chip-empty', text: '未输出' });
    var tone = v >= 75 ? 'high' : v >= 60 ? 'mid' : 'low';
    return h('span', { class: 'chip chip-' + tone, text: Number(v).toFixed(1) });
  }

  /* -------------------------------------------------------------- 折线图 */

  /**
   * 抬头率时序。points: [{t:秒, v:0-1}]
   * opts: { valley:{from,to}, threshold }
   */
  function lineChart(points, opts) {
    opts = opts || {};
    var W = 720, H = 200, P = { l: 38, r: 12, t: 14, b: 26 };
    var iw = W - P.l - P.r, ih = H - P.t - P.b;
    var s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'chart', preserveAspectRatio: 'none' });

    function x(t) { return P.l + (t / points[points.length - 1].t) * iw; }
    function y(v) { return P.t + (1 - v) * ih; }

    // 网格
    [0, 0.25, 0.5, 0.75, 1].forEach(function (g) {
      s.appendChild(svg('line', { x1: P.l, x2: W - P.r, y1: y(g), y2: y(g), class: 'chart-grid' }));
      var lb = svg('text', { x: P.l - 6, y: y(g) + 4, class: 'chart-axis', 'text-anchor': 'end', text: (g * 100) + '%' });
      s.appendChild(lb);
    });

    // 谷值区间
    if (opts.valley) {
      s.appendChild(svg('rect', {
        x: x(opts.valley.from), y: P.t,
        width: Math.max(2, x(opts.valley.to) - x(opts.valley.from)), height: ih,
        class: 'chart-valley'
      }));
      s.appendChild(svg('text', {
        x: x(opts.valley.from) + 6, y: P.t + 13, class: 'chart-flag',
        text: '谷值区间 ' + fmt.time(opts.valley.from) + '–' + fmt.time(opts.valley.to)
      }));
    }

    // 警戒线
    if (opts.threshold) {
      s.appendChild(svg('line', {
        x1: P.l, x2: W - P.r, y1: y(opts.threshold), y2: y(opts.threshold), class: 'chart-threshold'
      }));
    }

    // 面积 + 折线
    var d = '', da = '';
    points.forEach(function (p, i) {
      var cmd = (i === 0 ? 'M' : 'L') + x(p.t).toFixed(1) + ' ' + y(p.v).toFixed(1);
      d += cmd;
      da += cmd;
    });
    da += 'L' + x(points[points.length - 1].t).toFixed(1) + ' ' + y(0) + ' L' + x(0) + ' ' + y(0) + ' Z';
    s.appendChild(svg('path', { d: da, class: 'chart-area' }));
    s.appendChild(svg('path', { d: d, class: 'chart-line' }));

    // x 轴刻度
    var step = Math.max(600, Math.round(points[points.length - 1].t / 6 / 600) * 600);
    for (var t = 0; t <= points[points.length - 1].t; t += step) {
      s.appendChild(svg('text', { x: x(t), y: H - 8, class: 'chart-axis', 'text-anchor': 'middle', text: fmt.time(t) }));
    }
    return s;
  }

  /* -------------------------------------------------------------- 骨架屏 */

  function skeleton(rows) {
    var box = h('div', { class: 'skeleton' });
    for (var i = 0; i < (rows || 4); i++) box.appendChild(h('div', { class: 'sk-line' }));
    return box;
  }

  /* -------------------------------------------------------------- 提示与浮层 */

  function toast(message, tone) {
    var host = document.getElementById('toast-host');
    var el = h('div', { class: 'toast toast-' + (tone || 'info') }, h('span', { text: message }));
    host.appendChild(el);
    setTimeout(function () { el.classList.add('toast-out'); }, 2600);
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 3100);
  }

  function errorBox(err, onRetry) {
    return h('div', { class: 'error-box' },
      h('div', {},
        h('strong', { text: '请求失败' }),
        h('code', { text: err.code || 'ERROR' }),
        h('span', { text: err.message || String(err) })),
      onRetry ? h('button', { class: 'btn btn-ghost btn-sm', text: '重试', onclick: onRetry }) : null);
  }

  /** 二次确认浮层，返回 Promise<boolean> */
  function confirmDialog(opts) {
    return new Promise(function (resolve) {
      var host = document.getElementById('modal-host');
      var close = function (v) {
        if (host.firstChild) host.removeChild(host.firstChild);
        document.body.classList.remove('modal-open');
        resolve(v);
      };
      var panel = h('div', { class: 'modal' },
        h('h3', { text: opts.title || '请确认' }),
        h('p', { class: 'modal-text', text: opts.text || '' }),
        opts.detail ? h('div', { class: 'modal-detail' }, opts.detail) : null,
        h('div', { class: 'modal-actions' },
          h('button', { class: 'btn btn-ghost', text: opts.cancelText || '取消', onclick: function () { close(false); } }),
          h('button', {
            class: 'btn ' + (opts.danger ? 'btn-danger' : 'btn-primary'),
            text: opts.okText || '确定',
            onclick: function () { close(true); }
          })
        )
      );
      var mask = h('div', { class: 'modal-mask', onclick: function (e) { if (e.target === mask) close(false); } }, panel);
      host.appendChild(mask);
      document.body.classList.add('modal-open');
    });
  }

  /* -------------------------------------------------------------- 表单 */

  function field(label, control, hint) {
    return h('label', { class: 'field' },
      h('span', { class: 'field-label', text: label }),
      control,
      hint ? h('span', { class: 'field-hint', text: hint }) : null);
  }

  function input(attrs) {
    return h('input', Object.assign({ class: 'input' }, attrs));
  }

  function select(options, value, attrs) {
    var el = h('select', Object.assign({ class: 'input' }, attrs));
    options.forEach(function (o) {
      el.appendChild(h('option', { value: o.value, text: o.label, selected: o.value === value }));
    });
    return el;
  }

  function emptyState(title, desc, action) {
    return h('div', { class: 'empty' },
      h('div', { class: 'empty-icon', text: '—' }),
      h('h3', { text: title }),
      h('p', { text: desc || '' }),
      action || null);
  }

  function kv(pairs) {
    return h('dl', { class: 'kv' }, pairs.map(function (p) {
      return h('div', { class: 'kv-row' },
        h('dt', { text: p[0] }),
        h('dd', { class: p[2] ? 'kv-' + p[2] : '' }, p[1] instanceof Node ? p[1] : String(p[1] === null || p[1] === undefined ? '—' : p[1])));
    }));
  }

  global.UI = {
    h: h, svg: svg, clear: clear, esc: esc, fmt: fmt,
    badge: badge, statusBadge: statusBadge,
    card: card, sectionHead: sectionHead, grid: grid, stat: stat,
    table: table, bar: bar, scoreChip: scoreChip, lineChart: lineChart, scale: scale,
    skeleton: skeleton, toast: toast, errorBox: errorBox, confirmDialog: confirmDialog,
    field: field, input: input, select: select, emptyState: emptyState, kv: kv
  };
})(window);
