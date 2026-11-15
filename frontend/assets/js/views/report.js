/**
 * views/report.js — M7 报告与审计
 *
 * 左栏是报告本身（六节），右栏是操作与留痕。报告区刻意做成"纸面"样式，
 * 因为它最终要被打印或转 PDF 交给使用方。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h, fmt = UI.fmt;
  var Views = global.Views = global.Views || {};

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(8));
    Promise.all([
      global.Api.getReport(ctx.sessionId),
      global.Api.getAudit(1)
    ]).then(function (res) { render(el, ctx, res[0], res[1].items); })
      .catch(function (err) {
        UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
      });
  }

  function render(el, ctx, rep, audit) {
    UI.clear(el);
    var blocked = rep.coverage.audio < 0.6 || rep.coverage.video < 0.6;

    var paper = h('article', { class: 'paper' },
      paperHead(rep),
      secCoverage(rep),
      secItems('音频分项', rep.audio_items, '音频 9 项计分 ＋ C1 门禁', rep),
      secItems('视频分项', rep.video_items, '视频 10 项计分 ＋ VC3 列示', rep),
      secScores(rep),
      secConsistency(rep),
      secCompliance(rep),
      paperFoot()
    );

    var side = h('div', { class: 'report-side' },
      UI.card({
        title: '导出',
        body: h('div', { class: 'export-box' },
          h('button', {
            class: 'btn btn-ghost btn-block', text: '导出 PDF（待接入）', disabled: true,
            title: 'PDF 需嵌入中文字体，后端留接口（501）；请导出 DOCX 后在 WPS 另存为 PDF'
          }),
          h('button', {
            class: 'btn btn-primary btn-block', text: '导出 DOCX', disabled: blocked,
            onclick: function () { doExport(ctx, 'docx'); }
          }),
          h('button', {
            class: 'btn btn-ghost btn-block', text: '导出 JSON', onclick: function () { doExport(ctx, 'json'); }
          })
        )
      }),
      UI.card({
        title: '资源有效期限',
        body: h('div', {},
          h('dl', { class: 'kv' },
            h('div', { class: 'kv-row' }, h('dt', { text: '4K 原片' }),
              h('dd', { text: '留存至 ' + plusDays(rep.session.date, 7) })),
            h('div', { class: 'kv-row' }, h('dt', { text: '代理与抽帧' }),
              h('dd', { text: '留存至 ' + plusDays(rep.session.date, 30) })),
            h('div', { class: 'kv-row' }, h('dt', { text: '观测与快照' }), h('dd', { text: '至结项' }))),
          h('button', {
            class: 'btn btn-danger btn-block', text: '删除本场媒资', onclick: function () { doDelete(ctx); }
          }))
      }),
      UI.card({
        title: '审计留痕',
        sub: '全库最近 ' + audit.length + ' 条',
        body: UI.table({
          compact: true,
          columns: [
            { label: '动作 / 对象', render: function (r) {
              return h('div', { class: 'cell-stack' },
                h('code', { class: 'code code-sm', text: r.action }),
                h('span', { class: 'cell-sub', text: r.object_id }));
            } },
            { label: '时间', width: '96px', align: 'right', render: function (r) {
              return h('span', { class: 'nowrap-muted', text: fmt.datetime(r.at).slice(5) });
            } }
          ],
          rows: audit
        })
      })
    );

    el.appendChild(h('div', { class: 'report-layout' }, [paper, side]));
  }

  /* ---------------------------------------------------------- 报告各节 */

  function paperHead(rep) {
    var s = rep.session;
    return h('header', { class: 'paper-head' },
      h('div', { class: 'paper-kicker', text: '课堂教学质量评估报告 · 过程分' }),
      h('h1', { text: s.title }),
      h('div', { class: 'paper-meta' }, [
        ['课程', s.course], ['场次', s.id],
        ['课型', ({ theory: '理论课', seminar: '研讨课', practical: '实践课' })[s.scenario]],
        ['时间', s.date + ' ' + s.start + ' · ' + s.duration_min + ' 分钟'],
        ['教师', s.teacher], ['教室', s.room], ['学员', s.students + ' 人']
      ].map(function (p) {
        return h('div', { class: 'paper-meta-item' },
          h('span', { text: p[0] }), h('strong', { text: p[1] }));
      })));
  }

  function secCoverage(rep) {
    /* 注意项／阻断项按报告自带的 gate_items 数出来，不写死"2 项"——
       写死的数字在换一场课之后就是错的，而报告是要交出去的 */
    var gateItems = rep.coverage.gate_items || [];
    var warns = gateItems.filter(function (g) { return g.status === 'warn'; }).length;
    var rejects = gateItems.filter(function (g) { return g.status === 'reject'; }).length;
    var gateText = rep.coverage.gate === 'pass' ? '全部通过'
      : rep.coverage.gate === 'warn' ? warns + ' 项注意' : rejects + ' 项阻断';
    return h('section', { class: 'paper-sec' },
      h('h2', { text: '一、证据覆盖' }),
      h('div', { class: 'cover-grid' },
        coverCell('门禁结论', gateText,
          rep.coverage.gate === 'pass' ? 'ok' : rep.coverage.gate === 'warn' ? 'warn' : 'danger'),
        coverCell('音频覆盖率', fmt.pct(rep.coverage.audio), rep.coverage.audio >= 1 ? 'ok' : 'warn'),
        coverCell('视频覆盖率', fmt.pct(rep.coverage.video), rep.coverage.video >= 1 ? 'ok' : 'warn'),
        coverCell('缺失分项', String(rep.coverage.missing.length), rep.coverage.missing.length ? 'warn' : 'ok')),
      rep.coverage.missing.length ? h('ul', { class: 'paper-list' }, rep.coverage.missing.map(function (m) {
        return h('li', {}, [h('strong', { text: m.code + ' ' + m.name }), h('span', { text: '：' + m.reason })]);
      })) : h('p', { class: 'paper-p', text: '全部分项齐备。' })
    );
  }

  function coverCell(label, value, tone) {
    return h('div', { class: 'cover-cell cover-' + tone },
      h('span', { text: label }),
      h('strong', { text: value }));
  }

  function secItems(title, items, sub) {
    var rows = items.map(function (it) {
      return h('tr', { class: it.score === null ? 'row-empty' : '' },
        h('td', { class: 'ta-c' }, h('code', { class: 'code code-sm', text: it.code })),
        h('td', { text: it.name }),
        h('td', { class: 'ta-r', text: it.raw_value === null ? '—' : fmt.raw(it.raw_value, it.unit) }),
        h('td', { class: 'ta-r', text: it.score === null ? (it.code === 'C1' ? '无事件' : it.code === 'VC3' ? '列示' : '未输出') : it.score.toFixed(1) }),
        h('td', { class: 'ta-r', text: it.confidence === null ? '—' : it.confidence.toFixed(2) }),
        h('td', { class: 'ta-r', text: it.evidence_t === null ? '—' : fmt.time(it.evidence_t) }),
        h('td', { class: 'ta-mute', text: it.score === null ? (it.empty_reason || '') : (it.note || '') }));
    });

    return h('section', { class: 'paper-sec' },
      h('h2', { text: title }),
      h('p', { class: 'paper-cap', text: sub }),
      h('table', { class: 'paper-table' },
        h('thead', {}, h('tr', {}, [
          h('th', { class: 'ta-c', text: '编码' }), h('th', { text: '指标' }),
          h('th', { class: 'ta-r', text: '原始量' }), h('th', { class: 'ta-r', text: '分项分' }),
          h('th', { class: 'ta-r', text: '置信度' }), h('th', { class: 'ta-r', text: '证据' }),
          h('th', { text: '说明' })
        ])),
        h('tbody', {}, rows))
    );
  }

  function secScores(rep) {
    return h('section', { class: 'paper-sec' },
      h('h2', { text: '四、并列分数' }),
      h('div', { class: 'paper-scores' },
        h('div', { class: 'ps-item' },
          h('span', { text: '音频分 Sₐ' }),
          h('strong', { text: rep.scores.audio.toFixed(1) }),
          h('em', { text: '满分 100 · 9 项计分' })),
        h('div', { class: 'ps-sep', text: '｜' }),
        h('div', { class: 'ps-item' },
          h('span', { text: '视频分 Sᵥ' }),
          h('strong', { text: rep.scores.video.toFixed(1) }),
          h('em', { text: '满分 100 · 10 项计分' }))),
      h('p', { class: 'paper-p', text: '两份分数并列呈现，不合成总分。二者构念不同（内容对齐 vs 课堂形态）、误差结构不同（识别错误 vs 检测遗漏）、用途不同（内容诊断 vs 形态诊断），强行加权等于宣称三者可通约。' })
    );
  }

  function secConsistency(rep) {
    return h('section', { class: 'paper-sec' },
      h('h2', { text: '五、一致性判定' }),
      h('p', { class: 'paper-p', text: rep.consistency.note + '（分差 ' + fmt.signed(rep.consistency.delta) + ' 分）' }),
      rep.short_board && rep.short_board.length
        ? h('ul', { class: 'paper-list' }, rep.short_board.map(function (s) {
            return h('li', {}, [h('strong', { text: s.downgrade ? '短板约束触发' : '结构检查' }), h('span', { text: '：' + s.text })]);
          }))
        : null
    );
  }

  function secCompliance(rep) {
    return h('section', { class: 'paper-sec' },
      h('h2', { text: '六、合规线索' }),
      h('p', { class: 'paper-p', text: rep.compliance.note }),
      h('div', { class: 'paper-warn' },
        h('strong', { text: '表达约束' }),
        h('span', { text: '不出现"学员满意度""学习收获""培训效果"等本系统无权得出的结论；不出现个人层面负面标签；不出现跨课型比较。' }))
    );
  }

  function paperFoot() {
    return h('footer', { class: 'paper-foot' },
      h('p', { text: '本报告为过程分，不表示学员目标达成百分比。分数须与证据水平同读：置信度与覆盖率一并展示，缺失项列明原因。' }));
  }

  /* ---------------------------------------------------------- 操作 */

  /* 留存到期日按场次日期推算，不写死——写死的话换一场课就会显示错的日期 */
  function plusDays(dateStr, days) {
    var d = new Date((dateStr || new Date().toISOString().slice(0, 10)) + 'T00:00:00');
    if (isNaN(d.getTime())) return '—';
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function doExport(ctx, format) {
    /* 桌面版走原生"另存为"：文件由后端直接写到用户选的路径，
       不经浏览器下载目录，也不会在下载栏里留一堆同名副本。 */
    if (global.Desktop && global.Desktop.isDesktop()) {
      return desktopExport(ctx, format);
    }
    global.Api.exportReport(ctx.sessionId, format).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = h('a', {
        href: url,
        download: (format === 'json' ? '评估报告-' : '课堂教学质量评估报告-') + ctx.sessionId + '.' + format
      });
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
      UI.toast('已导出 ' + format.toUpperCase(), 'ok');
    }).catch(function (err) { UI.toast(err.message, 'danger'); });
  }

  function desktopExport(ctx, format) {
    var suggested = (format === 'json' ? '评估报告-' : '课堂教学质量评估报告-')
      + ctx.sessionId + '.' + format;
    global.Desktop.saveReport(ctx.sessionId, format, suggested).then(function (r) {
      if (!r || !r.saved) return;                    // 用户在另存为里取消了
      UI.toast('已保存 ' + r.saved, 'ok');
      UI.confirmDialog({
        title: '报告已保存',
        text: r.saved,
        okText: '打开所在文件夹',
        cancelText: '关闭'
      }).then(function (open) {
        if (open) global.Desktop.reveal(r.saved);
      });
    }).catch(function (err) { UI.toast(err.message, 'danger'); });
  }

  function doDelete(ctx) {
    UI.confirmDialog({
      title: '删除本场媒资',
      text: '将删除 4K 原片与 48kHz 原档（约 31 GB）。观测数据、评价快照与报告不受影响。此操作不可撤销。',
      okText: '确认删除',
      danger: true,
      detail: h('ul', { class: 'bullet' }, [
        '删除范围：raw4k/ 与 raw_audio/',
        '保留：代理流、抽帧、ROI、课件、observations、evaluations',
        '留痕：写入 audit，记录操作者与时间'
      ])
    }).then(function (ok) {
      if (!ok) return;
      global.Api.deleteMedia(ctx.sessionId, 'raw').then(function (r) {
        UI.toast('已删除 ' + r.deleted.length + ' 个资产，释放 ' + fmt.bytes(r.freed_bytes), 'ok');
      }).catch(function (err) { UI.toast(err.message, 'danger'); });
    });
  }

  Views.report = function (el, ctx) { load(el, ctx); };
})(window);
