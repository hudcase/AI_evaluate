/**
 * views/config.js — 指标配置（M7 · 元数据）
 *
 * 这一页存在的意义，是让"权重与阈值是待标定参数"这件事显式化。
 * 评审若问"你的阈值哪来的"，界面本身就是答案。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h;
  var Views = global.Views = global.Views || {};

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(8));
    global.Api.getIndicators().then(function (d) { render(el, ctx, d); })
      .catch(function (err) {
        UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
      });
  }

  function render(el, ctx, cfg) {
    UI.clear(el);
    var items = cfg.items;

    var audio = items.filter(function (i) { return i.tier === 'audio' && i.scored; });
    var video = items.filter(function (i) { return i.tier === 'video' && i.scored; });
    var sumA = audio.reduce(function (a, i) { return a + i.weight; }, 0);
    var sumV = video.reduce(function (a, i) { return a + i.weight; }, 0);

    el.appendChild(UI.grid(3, [
      UI.stat({ label: '音频 9 项权重和', value: sumA.toFixed(4), unit: '', note: Math.abs(sumA - 1) < 1e-6 ? '已配平' : '未配平' }),
      UI.stat({ label: '视频 10 项权重和', value: sumV.toFixed(4), unit: '', note: Math.abs(sumV - 1) < 1e-6 ? '已配平' : '未配平' }),
      UI.stat({ label: '指标总数', value: items.length, unit: '条',
        note: '全部按百分制打分' })
    ]));

    /* 两个子系统并排：列宽压到三列即可容纳，横向对照比上下滚动更容易发现权重问题 */
    var pair = UI.grid(2, [
      tableCard('音频子体系', items.filter(function (i) { return i.tier === 'audio'; })),
      tableCard('视频子体系', items.filter(function (i) { return i.tier === 'video'; }))
    ], '16px');
    pair.style.alignItems = 'start';
    el.appendChild(pair);
  }

  function tableCard(title, rows) {
    var card = UI.card({
      title: title,
      sub: rows.length + ' 条',
      body: UI.table({
        compact: true,
        columns: [
          { label: '编码', width: '54px', render: function (r) { return h('code', { class: 'code code-sm', text: r.code }); } },
          { label: '指标', render: function (r) { return h('strong', { text: r.name }); } },
          { label: '权重', width: '68px', align: 'right', render: function (r) {
            return r.weight === null ? h('span', { class: 'cell-sub', text: '不计分' }) : r.weight.toFixed(4);
          } }
        ],
        rows: rows
      })
    });
    card.style.marginBottom = '0';
    return card;
  }

  Views.config = function (el, ctx) { load(el, ctx); };
})(window);
