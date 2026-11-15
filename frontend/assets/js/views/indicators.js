/**
 * views/indicators.js — M5 指标计算
 *
 * 21 条指标分音频／视频两表。分项分用 0–100 水平条，空值项整行灰化并写原因：
 * 不填 0，因为 0 与"没测到"是两件事。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h, fmt = UI.fmt;
  var Views = global.Views = global.Views || {};

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(8));
    Promise.all([
      global.Api.getObservations(ctx.sessionId),
      global.Api.getEvaluation(ctx.sessionId),
      global.Api.getIndicators()
    ]).then(function (res) { render(el, ctx, res[0].items, res[1], res[2].items); })
      .catch(function (err) {
        UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
      });
  }

  function render(el, ctx, items, ev, cfgItems) {
    UI.clear(el);
    // 量尺参数以接口为准（配置改版后这里自动跟着变），补录预览用它折算
    var IND = {};
    (cfgItems || []).forEach(function (i) {
      IND[i.code] = { dir: i.direction, a: i.a, b: i.b, c: i.c, d: i.d, scored: i.scored };
    });

    var audio = items.filter(function (x) { return x.tier === 'audio'; });
    var video = items.filter(function (x) { return x.tier === 'video'; });

    el.appendChild(h('div', { class: 'notice notice-info' },
      h('strong', { text: '全部分项满分 100' })
    ));

    el.appendChild(UI.grid(2, [
      summaryCard('音频分 Sₐ', ev.audio, '9 项计分 · 权重和 1.0000', 'audio'),
      summaryCard('视频分 Sᵥ', ev.video, '10 项计分 · 权重和 1.0000', 'video')
    ], '16px'));

    el.appendChild(scaleCard(items));

    el.appendChild(tableCard('音频指标（10 项：9 计分 ＋ C1 门禁）', audio, ctx, el, IND));
    el.appendChild(tableCard('视频指标（11 项：10 计分 ＋ VC3 列示）', video, ctx, el, IND));
  }

  /* ------------------------------------------------------------ 量尺映射 */

  /* 四类取向的映射定义，与服务端 core/membership.py 一一对应。
     a／b／c／d 取自指标配置，不取理想值——阈值可追溯就落在这几个数上。 */
  var SCALE_DEF = [
    { key: 'inc', name: '递增型', code: 'inc',
      formula: 'μ = clip((x − a) / (b − a))', note: 'x ≤ a 折 0 分，x ≥ b 折满分' },
    { key: 'reverse', name: '反向型', code: 'reverse',
      formula: 'μ = 1 − clip((x − a) / (b − a))', note: 'x ≤ a 折满分，x ≥ b 折 0 分' },
    { key: 'interval', name: '区间型', code: 'interval',
      formula: 'a–b 升 · b–c 满 · c–d 降', note: 'x < a 或 x > d 折 0 分' },
    { key: 'level', name: '等级型', code: 'level / combo',
      formula: 'μ = clip(x)', note: 'x 已是 0–1 合成等级，直接折算' }
  ];

  function scaleCard(items) {
    var cnt = { inc: 0, reverse: 0, interval: 0, level: 0 };
    var off = 0;
    items.forEach(function (i) {
      var k = i.direction === 'combo' ? 'level' : i.direction;
      if (cnt[k] === undefined) off += 1; else cnt[k] += 1;
    });

    return UI.card({
      title: '量尺映射',
      actions: [
        UI.badge('分项分 s = 100μ', 'info'),
        off ? UI.badge(off + ' 条不计分', 'mute') : null
      ],
      body: h('div', { class: 'scale-grid' }, SCALE_DEF.map(function (d) {
        return h('div', { class: 'scale-cell' + (cnt[d.key] ? '' : ' is-idle') },
          h('div', { class: 'scale-head' },
            h('strong', { text: d.name }),
            h('span', { class: 'scale-tag' },
              h('code', { class: 'code code-sm', text: d.code }),
              h('span', { class: 'scale-count', text: cnt[d.key] + ' 条' }))),
          h('div', { class: 'scale-formula', text: d.formula }),
          h('div', { class: 'scale-note', text: d.note }));
      }))
    });
  }

  /** 单条指标的量尺：取向 + 参数值，行内可读。门禁／列示项没有量尺。 */
  function num(v) {
    if (v === null || v === undefined) return '—';
    return String(Number(v));
  }

  function scaleOf(r) {
    if (r.direction === 'gate') return h('span', { class: 'cell-sub', text: '门禁' });
    if (r.direction === 'listed') return h('span', { class: 'cell-sub', text: '列示' });
    var params = (r.direction === 'interval')
      ? [r.a, r.b, r.c, r.d].map(num).join('/')
      : (r.direction === 'level' || r.direction === 'combo')
        ? '0–1'
        : num(r.a) + '→' + num(r.b);
    return h('span', { class: 'scale-inline' },
      h('code', { class: 'code code-sm', text: r.direction }),
      h('span', { class: 'scale-params', text: params }));
  }

  function summaryCard(title, agg, sub, tone) {
    return h('div', { class: 'score-card score-' + tone },
      h('div', { class: 'score-head' },
        h('span', { text: title }),
        UI.badge(agg.coverage >= 1 ? '完整' : agg.coverage >= 0.6 ? '部分覆盖' : '证据不足',
          agg.coverage >= 1 ? 'ok' : agg.coverage >= 0.6 ? 'warn' : 'danger')),
      h('div', { class: 'score-num' },
        h('strong', { text: agg.score.toFixed(1) }),
        h('span', { text: '/ 100' })),
      h('div', { class: 'score-meta' },
        h('span', { text: sub }),
        h('span', { text: '参与 ' + agg.items + ' 项 · 权重和 ' + agg.weight_sum.toFixed(4) }),
        h('span', { text: '覆盖率 ' + fmt.pct(agg.coverage) + (agg.coverage < 1 ? '（未重归一）' : '') }))
    );
  }

  function tableCard(title, rows, ctx, el, IND) {
    return UI.card({
      title: title,
      sub: '原始量 → 量尺映射 → 分项分；点击行可补录或修正单条观测',
      body: UI.table({
        compact: true,
        columns: [
          { label: '编码', width: '60px', render: function (r) { return h('code', { class: 'code code-sm', text: r.code }); } },
          { label: '指标', width: '140px', render: function (r) { return h('strong', { text: r.name }); } },
          { label: '原始量', width: '104px', align: 'right', render: function (r) {
            if (r.raw_value === null) return h('span', { class: 'cell-sub', text: '—' });
            return h('span', {}, [
              h('strong', { text: fmt.raw(r.raw_value, r.unit) }),
              h('span', { class: 'cell-sub', text: ' ' + r.unit })
            ]);
          } },
          { label: '量尺', width: '180px', render: scaleOf },
          { label: '分母口径', width: '108px', className: 'ta-mute', render: function (r) { return r.denominator; } },
          { label: '置信度', width: '72px', align: 'right', render: function (r) {
            if (r.confidence === null) return '—';
            var t = r.confidence >= 0.8 ? 'ok' : r.confidence >= 0.65 ? 'warn' : 'danger';
            return h('span', { class: 'conf conf-' + t, text: r.confidence.toFixed(2) });
          } },
          { label: '证据', width: '70px', align: 'right', render: function (r) {
            return r.evidence_t === null ? '—' : h('code', { class: 'code code-sm', text: fmt.time(r.evidence_t) });
          } },
          { label: '权重', width: '74px', align: 'right', render: function (r) {
            return r.weight === null ? h('span', { class: 'cell-sub', text: '不计分' }) : r.weight.toFixed(4);
          } },
          { label: '分项分', width: '170px', render: function (r) {
            if (r.score === null) {
              var label = r.code === 'C1' ? '无事件' : r.code === 'VC3' ? '列示' : '未输出';
              return h('div', { class: 'empty-score' },
                h('span', { class: 'chip-empty', text: label }),
                h('em', { text: r.empty_reason || '' }));
            }
            return UI.bar(r.score);
          } }
        ],
        rows: rows,
        rowClass: function (r) { return r.score === null ? 'row-empty' : ''; },
        onRowClick: function (r) { editDialog(r, ctx, el, IND); }
      })
    });
  }

  /* ---------------------------------------------------------- 补录浮层 */

  function editDialog(obs, ctx, el, IND) {
    var ind = (IND && IND[obs.code]) || { dir: obs.direction, a: obs.a, b: obs.b,
      c: obs.c, d: obs.d, scored: obs.scored };

    if (!obs.weight && obs.code !== 'C1' && obs.code !== 'VC3') {
      UI.toast('该指标不计分，无需补录', 'warn');
      return;
    }

    var rawInput = UI.input({ type: 'number', step: '0.001', value: obs.raw_value === null ? '' : obs.raw_value });
    var confInput = UI.input({ type: 'number', step: '0.01', min: 0, max: 1, value: obs.confidence === null ? 0.8 : obs.confidence });
    var noteInput = UI.input({ type: 'text', maxlength: 120, value: obs.note || '' });
    var errBox = h('div', { class: 'form-error' });
    var preview = h('div', { class: 'preview' });

    function refreshPreview() {
      UI.clear(preview);
      var v = rawInput.value === '' ? null : Number(rawInput.value);
      var sc = v === null ? null : UI.scale(ind, v);
      preview.appendChild(h('span', { text: '按当前量尺 a=' + ind.a + ' b=' + ind.b + (ind.c !== null ? ' c=' + ind.c + ' d=' + ind.d : '') + ' 折算：' }));
      preview.appendChild(h('strong', { text: sc === null ? '—' : sc.toFixed(1) + ' 分' }));
    }
    rawInput.addEventListener('input', refreshPreview);
    refreshPreview();

    var host = document.getElementById('modal-host');
    function close() {
      if (host.firstChild) host.removeChild(host.firstChild);
      document.body.classList.remove('modal-open');
    }

    var panel = h('div', { class: 'modal modal-wide' },
      h('h3', { text: obs.code + ' ' + obs.name }),
      h('p', { class: 'modal-text', text: '补录原始量后由服务端折算分项分（POST /api/sessions/{id}/observations）。' }),
      h('div', { class: 'form-row' }, [
        UI.field('原始量（单位 ' + obs.unit + '）', rawInput),
        UI.field('置信度', confInput)
      ]),
      UI.field('证据说明', noteInput),
      preview,
      errBox,
      h('div', { class: 'modal-actions' },
        h('button', { class: 'btn btn-ghost', text: '取消', onclick: close }),
        h('button', {
          class: 'btn btn-primary', text: '提交',
          onclick: function () {
            UI.clear(errBox);
            var payload = {
              code: obs.code,
              raw_value: Number(rawInput.value),
              denominator: 1.0,
              unit: obs.unit,
              confidence: Number(confInput.value),
              evidence_t: obs.evidence_t || 0,
              source_track: obs.source_track,
              evidence_note: noteInput.value
            };
            global.Api.postObservation(ctx.sessionId, payload).then(function (r) {
              UI.toast(obs.code + ' 已写入，分项分 ' + r.score.toFixed(1), 'ok');
              obs.raw_value = payload.raw_value;
              obs.score = r.score;
              obs.confidence = r.confidence;
              close();
              load(el, ctx);
            }).catch(function (err) { errBox.appendChild(UI.errorBox(err)); });
          }
        })
      )
    );

    host.appendChild(h('div', { class: 'modal-mask', onclick: function (e) { if (e.target === e.currentTarget) close(); } }, panel));
    document.body.classList.add('modal-open');
  }

  Views.indicators = function (el, ctx) { load(el, ctx); };
})(window);
