/**
 * views/gateway.js — M4 模型
 *
 * 整页使用云端配色（浅蓝底 + 蓝描边），与端侧页面形成对比：这里的数据全部来自外部服务。
 * 页面目的不是"操作"，而是事后核对：调了多少次、花了多少、哪个能力不稳、版本是什么。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h, fmt = UI.fmt;
  var Views = global.Views = global.Views || {};

  var CAPS = [
    { key: 'asr', name: 'ASR ＋ 说话人分离' },
    { key: 'ocr', name: 'OCR' },
    { key: 'embed', name: '向量化 Embedding' },
    { key: 'llm', name: 'LLM 判定' },
    { key: 'vlm', name: 'VLM 判定' }
  ];

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(6));
    Promise.all([
      global.Api.getAiCalls(ctx.sessionId),
      global.Api.getHealth()
    ]).then(function (res) {
      render(el, ctx, res[0], res[1]);
    }).catch(function (err) {
      UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
    });
  }

  function render(el, ctx, data, health) {
    UI.clear(el);
    var s = data.summary;

    /* 模拟模式下五类能力一律返回 degraded —— 那是"没接真模型"，不是"服务挂了"。
       按 provider_mode 换一套说法，避免把模拟读成故障。 */
    var stub = health.provider_mode === 'stub';
    function toneOf(v) {
      if (v === 'ok') return 'ok';
      if (v === 'degraded') return stub ? 'stub' : 'degraded';
      return 'down';   /* unavailable 等一律按不可用显示 */
    }
    function textOf(v) {
      if (v === 'ok') return '正常';
      if (v === 'degraded') return stub ? '模拟' : '降级';
      return '不可用';
    }

    /* --- 服务状态条 --- */
    var statuses = h('div', { class: 'provider-bar' }, Object.keys(health.providers).map(function (k) {
      var v = health.providers[k];
      return h('div', { class: 'provider provider-' + toneOf(v) },
        h('span', { class: 'provider-dot' }),
        h('strong', { text: k.toUpperCase() }),
        h('span', { class: 'provider-state', text: textOf(v) }));
    }));

    var desc = stub
      ? '模拟模式：五类能力返回确定性占位结果，不调用外部服务、不计费，调用记录 simulated=true。接真模型只改 MODEL_PROVIDER。'
      : '经 M4 网关调用，是唯一出网出口。不接收原片与原档，不落业务结论，逐次写 ai_calls。';

    el.appendChild(h('div', { class: 'cloud-banner' },
      h('div', { class: 'cloud-banner-text' },
        h('div', { class: 'cloud-banner-title' },
          h('strong', { text: '云端 · 外部模型服务' }),
          stub ? UI.badge('模拟', 'info') : null),
        h('span', { text: desc })),
      statuses));

    /* --- 成本概览 --- */
    el.appendChild(UI.grid(4, [
      UI.stat({ label: '本场调用', value: s.calls, unit: '次' }),
      UI.stat({ label: '缓存命中', value: s.cached, unit: '次', note: 'TTL 7 天，按 input_hash 判重' }),
      UI.stat({ label: '累计成本', value: '¥' + s.cost.toFixed(2), unit: '',
        note: s.simulated ? '估算值：' + s.simulated + ' 次为模拟调用，非真实账单' : '按 token 与图像张数计' }),
      UI.stat({ label: 'P95 延迟', value: (s.p95_latency_ms / 1000).toFixed(1), unit: 's', note: 'VLM 为主要耗时项' })
    ]));

    /* --- 能力卡 --- */
    el.appendChild(UI.sectionHead('五类能力'));
    el.appendChild(UI.grid(5, CAPS.map(function (c) {
      var raw = health.providers[c.key] || 'ok';
      return h('div', { class: 'cap-card' },
        h('div', { class: 'cap-head' },
          h('strong', { text: c.name }),
          h('span', { class: 'cap-state' },
            h('span', { class: 'cap-dot cap-' + toneOf(raw) }),
            h('em', { text: textOf(raw) }))));
    }), '12px'));

    /* --- 调用日志 --- */
    var maxCalls = s.byCapability.reduce(function (m, r) {
      return Math.max(m, r.calls);
    }, 1);
    /* 条形长度表示该能力的调用占比，不代表好坏，故固定用中性蓝，不走分数档配色 */
    var byCap = s.byCapability.map(function (r) {
      return h('div', { class: 'cost-row' },
        h('span', { class: 'cost-name', text: r.capability.toUpperCase() }),
        UI.bar(r.calls / maxCalls * 100, { label: false, slim: true, tone: 'high' }),
        h('span', { class: 'cost-num', text: r.calls + ' 次' }),
        h('span', { class: 'cost-money', text: '¥' + r.cost.toFixed(2) }));
    });

    el.appendChild(UI.card({
      title: '模型计费',
      body: byCap.length
        ? h('div', { class: 'cost-list' }, byCap)
        : h('p', { class: 'hint', text: '本场次尚无模型调用' })
    }));

    el.appendChild(UI.card({
      title: '调用日志',
      sub: '共 ' + data.items.length + ' 条（演示为抽样）',
      body: UI.table({
        compact: true,
        columns: [
          { label: '能力', width: '76px', render: function (r) { return h('code', { class: 'code code-sm', text: r.capability }); } },
          { label: '模型', key: 'provider' },
          { label: '模型版本', width: '96px', key: 'model_version' },
          { label: '提示词版本', width: '120px', key: 'prompt_version' },
          { label: '输入', align: 'right', width: '80px', render: function (r) { return r.tokens_in ? r.tokens_in.toLocaleString() : '—'; } },
          { label: '输出', align: 'right', width: '72px', render: function (r) { return r.tokens_out ? String(r.tokens_out) : '—'; } },
          { label: '延迟', align: 'right', width: '80px', render: function (r) { return (r.latency_ms / 1000).toFixed(1) + 's'; } },
          { label: '成本', align: 'right', width: '76px', render: function (r) { return '¥' + r.cost.toFixed(2); } },
          { label: '缓存', width: '64px', align: 'center', render: function (r) { return r.cached ? UI.badge('命中', 'ok') : '—'; } },
          { label: '时间', width: '130px', render: function (r) { return fmt.datetime(r.at).slice(11); } }
        ],
        rows: data.items
      })
    }));
  }

  Views.gateway = function (el, ctx) { load(el, ctx); };
})(window);
