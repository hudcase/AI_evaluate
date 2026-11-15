/**
 * views/governance.js — M3 数据治理
 *
 * 这一页的核心不是"进度条"，而是九项门禁：门禁的作用是把"测不准"与"教得差"分开。
 * 因此每行都写清"未通过时动作"，而不是只给一个红灯。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h, fmt = UI.fmt;
  var Views = global.Views = global.Views || {};

  var STAGES = [
    { key: 'probe', name: '校验登记' },
    { key: 'transcode', name: '转码派生' },
    { key: 'extract', name: '抽帧 ROI' },
    { key: 'parse_slides', name: '课件解析' },
    { key: 'mask', name: '脱敏' },
    { key: 'gate', name: '门禁判定' }
  ];

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(6));
    Promise.all([
      global.Api.getQc(ctx.sessionId),
      global.Api.getAssets(ctx.sessionId),
      global.Api.getTasks(ctx.sessionId, 'preprocess')
    ]).then(function (res) {
      render(el, ctx, res[0], res[1], (res[2].items || [])[0] || {
        id: '—', status: 'none', progress: 0, stage: null
      });
    }).catch(function (err) {
      UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
    });
  }

  function render(el, ctx, qc, assets, task) {
    UI.clear(el);
    // 阶段状态以后端为准：done 真做了、skipped 本机做不了（如无 ffmpeg／无检测模型）、failed 失败
    var byKey = {};
    (task.stages || []).forEach(function (s) { byKey[s.key] = s; });
    var doneIdx = task.status === 'succeeded' ? STAGES.length
      : task.stage ? Math.max(0, STAGES.map(function (s) { return s.key; }).indexOf(task.stage))
        : 0;

    var stages = h('div', { class: 'stages' }, STAGES.map(function (s, i) {
      var r = byKey[s.key];
      var state = r
        ? (r.status === 'skipped' ? 'skip' : r.status === 'failed' ? 'fail' : 'done')
        : (i < doneIdx ? 'done' : i === doneIdx ? 'active' : 'todo');
      var mark = state === 'done' ? '✓' : state === 'skip' ? '—' : state === 'fail' ? '!' : String(i + 1);
      return h('div', { class: 'stage stage-' + state, title: r ? r.detail : '' },
        h('div', { class: 'stage-dot', text: mark }),
        h('div', { class: 'stage-name', text: s.name }),
        h('div', { class: 'stage-bar' }, h('div', { class: 'stage-bar-fill', style: { width: state === 'done' ? '100%' : state === 'active' ? (task.progress * 100) + '%' : '0%' } }))
      );
    }));

    var stageCard = UI.card({
      title: '预处理流水',
      sub: task.status === 'running'
        ? '任务 ' + task.id + ' 运行中 · 当前阶段 ' + (task.stage || '—') + ' · ' + Math.round(task.progress * 100) + '%'
        : task.status === 'succeeded'
          ? '任务 ' + task.id + ' 已完成 · 六个阶段已走完'
          : task.status === 'failed'
            ? '任务 ' + task.id + ' 失败：' + (task.error || '见服务端日志')
            : '尚未预处理：门禁按现有证据现算，缺证据项显示"未测"',
      actions: h('button', {
        class: 'btn btn-ghost btn-sm', text: '重新预处理',
        onclick: function () {
          global.Api.preprocess(ctx.sessionId).then(function (r) {
            UI.toast('已提交任务 ' + r.task_id, 'ok');
            setTimeout(function () { load(el, ctx); }, 1200);
          }).catch(function (e) { UI.toast(e.message, 'danger'); });
        }
      }),
      body: stages
    });

    /* --- 门禁 --- */
    /* --- 门禁 --- */
    var gateTone = { pass: 'ok', warn: 'warn', reject: 'danger' };
    var gateText = { pass: '通过', warn: '注意', reject: '阻断' };
    /* 注意项数量按实际门禁算，不写死——写死的话换一场课就会说错话 */
    var warnCount = qc.gates.filter(function (g) { return g.status === 'warn'; }).length;
    var rejectCount = qc.gates.filter(function (g) { return g.status === 'reject'; }).length;
    var gateSub = qc.overall === 'pass' ? '全部 ' + qc.gates.length + ' 项通过'
      : qc.overall === 'warn' ? warnCount + ' 项注意，相关分项已按区域加权校正'
        : rejectCount + ' 项阻断，相应分项不予输出';
    var gateCard = UI.card({
      title: '九项门禁',
      sub: gateSub,
      actions: UI.badge(gateText[qc.overall], gateTone[qc.overall]),
      body: UI.table({
        compact: true,
        columns: [
          { label: '门禁', width: '140px', key: 'name' },
          { label: '结论', width: '72px', render: function (r) { return UI.badge(gateText[r.status], gateTone[r.status]); } },
          { label: '观测值', width: '130px', render: function (r) { return h('code', { class: 'code code-sm', text: r.value }); } },
          { label: '说明', key: 'detail' },
          { label: '未通过时动作', key: 'action', className: 'ta-mute' }
        ],
        rows: qc.gates,
        foot: '门禁阈值属试点标定参数，冻结后实行版本管理；否则同一教师会因模型升级而出现无法解释的分数变化。'
      })
    });

    /* --- 资产 --- */
    var capacity = UI.card({
      title: '派生资产',
      sub: '合计 ' + fmt.bytes(assets.total_bytes) + ' · 派生资产不可删，是报告与申诉的唯一依据',
      body: UI.table({
        compact: true,
        columns: [
          { label: '类型', key: 'label' },
          { label: '数量', align: 'right', width: '90px', render: function (r) { return String(r.count); } },
          { label: '占用', align: 'right', width: '100px', render: function (r) { return fmt.bytes(r.bytes); } },
          { label: '留存', align: 'right', width: '90px', render: function (r) { return r.retention_days ? r.retention_days + ' 天' : '至结项'; } }
        ],
        rows: assets.items
      })
    });

    var retention = UI.card({
      title: '留存策略',
      sub: '存储紧张时只缩短原片留存期，派生资产不动',
      body: h('div', { class: 'retention' }, [
        ['4K 原片', '7 天', '约 43 GB/节', 'danger'],
        ['720p 代理', '30 天', '约 4 GB/节', 'ok'],
        ['抽帧与 ROI', '30 天', '约 0.5 GB/节', 'ok'],
        ['48k 双轨原档', '30 天', '约 1 GB/节', 'ok'],
        ['16k 送 ASR', '24 小时', '调用后即删', 'mute']
      ].map(function (r) {
        return h('div', { class: 'retention-row' },
          h('span', { class: 'retention-name', text: r[0] }),
          h('span', { class: 'retention-days', text: r[1] }),
          h('span', { class: 'retention-size', text: r[2] }),
          UI.badge(r[3] === 'danger' ? '最短' : r[3] === 'mute' ? '临时' : '保留', r[3]));
      }))
    });

    el.appendChild(stageCard);
    el.appendChild(gateCard);
    el.appendChild(UI.grid(2, [capacity, retention], '16px'));
  }

  Views.governance = function (el, ctx) { load(el, ctx); };
})(window);
