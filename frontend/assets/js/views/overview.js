/**
 * views/overview.js — 总览
 *
 * 回答三个问题：有多少课、卡在哪一步、系统健康吗。
 * 状态徽标是这一页的主线：可用／低可信／证据不足／证据不一致。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h, fmt = UI.fmt;
  var Views = global.Views = global.Views || {};

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(6));
    global.Api.getOverview().then(function (d) {
      render(el, ctx, d);
    }).catch(function (err) {
      UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
    });
  }

  function render(el, ctx, d) {
    UI.clear(el);
    var k = d.kpis, hp = d.health.pipeline;

    /* --- KPI --- */
    el.appendChild(UI.grid(4, [
      UI.stat({ label: '在评课次', value: k.total, unit: '节', note: '本月累计' }),
      UI.stat({ label: '已出报告', value: k.reported, unit: '份',
        note: (function () {
          var n = d.sessions.filter(function (x) { return x.status === 'insufficient'; }).length;
          return n ? '含 ' + n + ' 份证据不足' : '均可直接引用';
        })() }),
      UI.stat({ label: '平均覆盖率', value: (k.avg_coverage * 100).toFixed(0), unit: '%', note: '低于 60% 不出模态分' }),
      UI.stat({ label: '本月模型成本', value: '¥' + k.monthly_cost.toFixed(2), unit: '',
        note: (k.monthly_calls || 0) + ' 次调用 · ' + (k.monthly_cached || 0) + ' 次命中缓存' })
    ]));

    /* --- 课次表 --- */
    el.appendChild(UI.sectionHead('近期课次', '点击行进入该场次的指标与报告',
      h('button', { class: 'btn btn-ghost btn-sm', text: '刷新', onclick: function () { load(el, ctx); } })));

    el.appendChild(UI.card({
      body: UI.table({
        columns: [
          { label: '场次', key: 'id', width: '150px', render: function (r) { return h('code', { class: 'code', text: r.id }); } },
          { label: '课程 / 场次', render: function (r) {
            return h('div', { class: 'cell-stack' },
              h('strong', { text: r.title }),
              h('span', { class: 'cell-sub', text: r.course }));
          } },
          { label: '时间', width: '150px', render: function (r) { return r.date + ' ' + r.start; } },
          { label: '音频分', width: '90px', align: 'right', render: function (r) { return UI.scoreChip(r.audio); } },
          { label: '视频分', width: '90px', align: 'right', render: function (r) { return UI.scoreChip(r.video); } },
          { label: '覆盖率', width: '80px', align: 'right', render: function (r) { return r.coverage === null ? '—' : fmt.pct(r.coverage); } },
          { label: '状态', width: '110px', render: function (r) { return UI.statusBadge(r.status); } }
        ],
        rows: d.sessions,
        onRowClick: function (r) {
          ctx.setSession(r.id);
          ctx.go('evaluation');
        }
      })
    }));

    /* --- 健康度 + 边界 --- */
    /* 一致性率来自 evaluations 表：没落过快照、或全部场次都证据不足时后端返回 null，
       这里必须显示"—"而不是 0%，否则会读成"一致性很差"。 */
    var rate = hp.consistency_rate;
    var hasRate = rate !== null && rate !== undefined && !isNaN(rate);
    function lvl(v, limit) {
      if (v === null || v === undefined || isNaN(v)) return ['未测', 'mute'];
      return v < limit ? ['正常', 'ok'] : ['关注', 'warn'];
    }
    var healthRows = [
      ['字错误率 CER', fmt.pct(hp.cer, 1), lvl(hp.cer, 0.10)],
      ['说话人分离错误率', fmt.pct(hp.der, 1), lvl(hp.der, 0.10)],
      ['门禁拦截率', fmt.pct(hp.gate_block_rate, 0), lvl(hp.gate_block_rate, 0.30)],
      ['低置信度比例', fmt.pct(hp.low_conf_rate, 0), lvl(hp.low_conf_rate, 0.20)]
    ];

    var health = UI.card({
      title: '运行健康',
      sub: '一致性率下降通常意味着设备更换、模型升级或课型变化，而非教师水平突变',
      body: h('div', { class: 'health' },
        h('div', { class: 'health-main' },
          h('div', { class: 'health-num' },
            h('strong', { text: hasRate ? (rate * 100).toFixed(0) : '—' }),
            hasRate ? h('span', { text: '%' }) : null),
          h('p', { class: 'health-cap', text: hasRate ? '跨模态一致性率' : '跨模态一致性率（尚无评价快照）' })
        ),
        h('div', { class: 'health-list' }, healthRows.map(function (r) {
          return h('div', { class: 'health-row' },
            h('span', { text: r[0] }),
            h('strong', { text: r[1] }),
            UI.badge(r[2][0], r[2][1]));
        })))
    });

    el.appendChild(health);
  }

  Views.overview = function (el, ctx) { load(el, ctx); };
})(window);
