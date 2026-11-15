/**
 * views/evaluation.js — M6 合成与一致性
 *
 * 两份分数并列，中间不设总分位——留白本身就是结论。
 * 一致性判定、五条融合规则状态、短板约束三块决定"这份结果能不能用"。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h, fmt = UI.fmt;
  var Views = global.Views = global.Views || {};

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(6));
    Promise.all([
      global.Api.getEvaluation(ctx.sessionId),
      global.Api.getVb1Series(ctx.sessionId)
    ]).then(function (res) { render(el, ctx, res[0], res[1]); })
      .catch(function (err) {
        UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
      });
  }

  function render(el, ctx, ev, vb1) {
    UI.clear(el);
    var series = vb1.points || [];
    var valley = vb1.valley || null;
    var threshold = vb1.threshold || 0.5;
    var insufficient = ev.consistency.status === 'insufficient';

    /* --- 顶部横幅 --- */
    if (insufficient) {
      el.appendChild(h('div', { class: 'notice notice-danger' },
        h('strong', { text: '证据不足，暂停输出模态分' }),
        h('span', { text: '双模态覆盖率低于 0.60（音频 ' + fmt.pct(ev.audio.coverage) + '、视频 ' + fmt.pct(ev.video.coverage) +
          '）。' })));
    } else if (ev.consistency.status === 'divergent') {
      el.appendChild(h('div', { class: 'notice notice-warn' },
        h('strong', { text: '证据不一致' }),
        h('span', { text: '两模态分差 ' + Math.abs(ev.consistency.delta).toFixed(1) +
          ' 分且方向相反。' })));
    }

    /* --- 并列分数 --- */
    var pair = h('div', { class: 'score-pair' },
      scorePanel('音频分 Sₐ', 'AUDIO', ev.audio, insufficient, '内容对齐：目标告知、覆盖、聚焦、授课状态'),
      h('div', { class: 'score-seam' },
        h('span', { class: 'seam-text', text: '不合成' }),
        h('span', { class: 'seam-line' }),
        h('span', { class: 'seam-note', text: '规则一：并列呈现，不输出总评分' })),
      scorePanel('视频分 Sᵥ', 'VIDEO', ev.video, insufficient, '课堂形态：教师行为、学生状态、互动结构')
    );
    el.appendChild(pair);

    /* --- 一致性 + 规则 --- */
    var consistencyTone = { aligned: 'ok', divergent: 'warn', insufficient: 'danger' }[ev.consistency.status];
    var consistencyCard = UI.card({
      title: '跨模态一致性',
      actions: UI.badge({ aligned: '一致', divergent: '不一致', insufficient: '不足' }[ev.consistency.status], consistencyTone),
      body: h('div', {},
        h('div', { class: 'consistency' },
          h('div', { class: 'consistency-num' },
            h('strong', { text: fmt.signed(ev.consistency.delta) }),
            h('span', { text: '分' })),
          h('p', { class: 'consistency-note', text: ev.consistency.status === 'aligned'
            ? '两模态判断方向一致，分差在合理范围内。'
            : ev.consistency.status === 'divergent'
              ? '方向相反：音频侧评价较好而视频侧偏低（或反之），说明至少一个模态在此情境下失效。'
              : '覆盖率不足，不做一致性判定。' })),
        ev.consistency.divergent.length
          ? h('div', { class: 'divergent-tags' }, ev.consistency.divergent.map(function (t) {
              return UI.badge(t, 'warn');
            }))
          : null,
        h('dl', { class: 'kv consistency-kv' },
          h('div', { class: 'kv-row' }, h('dt', { text: '判定阈值' }), h('dd', { text: '分差 ≥ 15 分且方向相反' })),
          h('div', { class: 'kv-row' }, h('dt', { text: '本场分差' }), h('dd', { text:
            fmt.signed(ev.consistency.delta) + ' 分' +
            (ev.consistency.status === 'aligned' ? '（阈值内）' : ev.consistency.status === 'divergent' ? '（超阈值）' : '（未判定）') })),
          h('div', { class: 'kv-row' }, h('dt', { text: '是否计分' }), h('dd', { text: '否——一致性率是系统健康度指标，不参与评分' })))
      )
    });

    el.appendChild(consistencyCard);

    /* --- 短板约束 + 时序 --- */
    var shortCard = UI.card({
      title: '短板约束',
      body: h('div', {},
        h('div', { class: 'short-list' }, ev.short_board.map(function (s) {
          return h('div', { class: 'short-row' + (s.downgrade ? ' is-down' : '') },
            UI.badge(s.downgrade ? '降档' : '正常', s.downgrade ? 'danger' : 'ok'),
            h('span', { text: s.text }));
        })),
        series.length ? h('div', { class: 'chart-wrap' },
          h('div', { class: 'chart-title', text: 'VB1 抬头率时序（1 分钟粒度）' }),
          UI.lineChart(series, { valley: valley, threshold: threshold }),
          h('div', { class: 'chart-legend' },
            h('span', { class: 'lg-line', text: '抬头率' }),
            h('span', { class: 'lg-valley', text: '谷值区间' }),
            h('span', { class: 'lg-th', text: '警戒线 ' + Math.round(threshold * 100) + '%' })))
          : h('p', { class: 'hint', text: vb1.note || '该场次尚无抬头率时序数据。' }),
        h('p', { class: 'hint', text: '触发降档时报告须写明原因与时间区间；短板约束只降不升。' })
      )
    });

    /* --- 缺失清单 --- */
    var missingCard = UI.card({
      title: '缺失与列示',
      body: UI.table({
        compact: true,
        columns: [
          { label: '编码', width: '64px', render: function (r) { return h('code', { class: 'code code-sm', text: r.code }); } },
          { label: '指标', width: '140px', key: 'name' },
          { label: '原因', key: 'reason' },
          { label: '权重', width: '80px', align: 'right', render: function (r) { return r.weight ? r.weight.toFixed(4) : '不计分'; } }
        ],
        rows: ev.missing,
        empty: '本场次无缺失分项'
      })
    });

    el.appendChild(UI.grid(2, [shortCard, missingCard], '16px'));
  }

  function scorePanel(title, tagText, agg, muted, desc) {
    var level = agg.score >= 75 ? 'high' : agg.score >= 60 ? 'mid' : 'low';
    var ring = h('div', { class: 'ring ring-' + level },
      h('div', { class: 'ring-inner' },
        h('strong', { text: muted ? '—' : agg.score.toFixed(1) }),
        h('span', { text: muted ? '暂停' : '分' })));
    // 自定义属性必须走 setProperty，直接写 style 对象不会生效
    ring.style.setProperty('--pct', muted ? 0 : agg.score);

    return h('div', { class: 'score-panel' + (muted ? ' is-muted' : '') },
      h('div', { class: 'panel-head' },
        h('div', { class: 'panel-tag', text: tagText }),
        h('h3', { text: title })),
      ring,
      h('p', { class: 'panel-desc', text: desc }),
      h('div', { class: 'panel-meta' },
        h('div', {}, h('span', { text: '覆盖率' }), h('strong', { text: fmt.pct(agg.coverage) })),
        h('div', {}, h('span', { text: '参与项' }), h('strong', { text: agg.items + ' 项' })),
        h('div', {}, h('span', { text: '权重和' }), h('strong', { text: agg.weight_sum.toFixed(4) })))
    );
  }

  Views.evaluation = function (el, ctx) { load(el, ctx); };
})(window);
