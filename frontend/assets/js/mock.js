/**
 * mock.js — 演示数据
 *
 * 全部为构造数据，用于在无后端时跑通界面。数据结构与 docs/接口约定.md 严格一致，
 * 后端就绪后把 config.js 的 useMock 置 false 即可切换，前端页面无需改动。
 *
 * 计分不在前端做"随便给个数"：mock 里的分项分同样按 indicator_config 的梯形量尺算出来，
 * 因此界面上看到的分数与原始量、量尺参数三者自洽，评审时经得起反推。
 */
(function (global) {
  'use strict';

  /* ---------------------------------------------------------------- 指标元数据 */

  // domain 键：tm 目标匹配 / ts 授课状态 / tb 教师行为 / ss 学生状态 / st 互动结构
  var INDICATORS = [
    // ---- 音频 · 9 项计分 ----
    { code: 'A1', name: '开课目标告知', tier: 'audio', domain: 'tm', weight: 0.06, dir: 'level',
      unit: '0–1', a: 0, b: 1, c: null, d: null, denom: '等级折算', scored: true },
    { code: 'A2', name: '加权目标覆盖', tier: 'audio', domain: 'tm', weight: 0.24, dir: 'inc',
      unit: 'ratio', a: 0, b: 0.75, c: null, d: null, denom: '核心目标权重和', scored: true },
    { code: 'A3', name: '内容目标聚焦', tier: 'audio', domain: 'tm', weight: 0.10, dir: 'inc',
      unit: 'ratio', a: 0.40, b: 0.85, c: null, d: null, denom: '有效讲授时长', scored: true },
    { code: 'B1', name: '语速与停顿', tier: 'audio', domain: 'ts', weight: 0.13, dir: 'interval',
      unit: '字/分', a: 140, b: 185, c: 250, d: 330, denom: '—', scored: true },
    { code: 'B2', name: '语调与重音', tier: 'audio', domain: 'ts', weight: 0.09, dir: 'level',
      unit: '0–1', a: 0, b: 1, c: null, d: null, denom: '等级折算', scored: true },
    { code: 'B3', name: '口音可懂度', tier: 'audio', domain: 'ts', weight: 0.10, dir: 'inc',
      unit: 'ratio', a: 0.70, b: 0.95, c: null, d: null, denom: '盲听词次', scored: true },
    { code: 'B4', name: '语言流畅度', tier: 'audio', domain: 'ts', weight: 0.09, dir: 'level',
      unit: '0–1', a: 0, b: 1, c: null, d: null, denom: '等级折算', scored: true },
    { code: 'B5', name: '讲解与组织清晰', tier: 'audio', domain: 'ts', weight: 0.10, dir: 'level',
      unit: '0–1', a: 0, b: 1, c: null, d: null, denom: '等级折算', scored: true },
    { code: 'B6', name: '课堂互动状态', tier: 'audio', domain: 'ts', weight: 0.09, dir: 'inc',
      unit: 'ratio', a: 0.20, b: 0.75, c: null, d: null, denom: '有效提问数', scored: true },
    { code: 'C1', name: '违规或危险言论', tier: 'audio', domain: 'gate', weight: null, dir: 'gate',
      unit: '事件数', a: null, b: null, c: null, d: null, denom: '—', scored: false },

    // ---- 视频 · 10 项计分 + 1 项列示 ----
    { code: 'VA1', name: '手势', tier: 'video', domain: 'tb', weight: 0.0515, dir: 'interval',
      unit: '次/分', a: 5, b: 12, c: 18, d: 30, denom: '可评价时长', scored: true },
    { code: 'VA2', name: '体态开放度', tier: 'video', domain: 'tb', weight: 0.0722, dir: 'interval',
      unit: 'ratio', a: 0.30, b: 0.70, c: 0.90, d: 1.0, denom: '可评价时长', scored: true },
    { code: 'VA3', name: '眼神交流', tier: 'video', domain: 'tb', weight: 0.0928, dir: 'interval',
      unit: 'ratio', a: 0.20, b: 0.55, c: 0.80, d: 1.0, denom: '有效观测时长', scored: true },
    { code: 'VA4', name: '空间行为', tier: 'video', domain: 'tb', weight: 0.1031, dir: 'interval',
      unit: '次/课时', a: 2, b: 8, c: 14, d: 25, denom: '课时', scored: true },
    { code: 'VA5', name: '媒体与呈示', tier: 'video', domain: 'tb', weight: 0.0928, dir: 'interval',
      unit: 'ratio', a: 0, b: 0.08, c: 0.22, d: 0.50, denom: '讲授总时长', scored: true },
    { code: 'VB1', name: '注意投入', tier: 'video', domain: 'ss', weight: 0.1855, dir: 'inc',
      unit: 'ratio', a: 0.35, b: 0.80, c: null, d: null, denom: '可判定人时', scored: true },
    { code: 'VB2', name: '分心行为', tier: 'video', domain: 'ss', weight: 0.1753, dir: 'reverse',
      unit: 'ratio', a: 0.03, b: 0.25, c: null, d: null, denom: '可判定人时', scored: true },
    { code: 'VB3', name: '参与互动', tier: 'video', domain: 'ss', weight: 0.1031, dir: 'inc',
      unit: 'ratio', a: 0.10, b: 0.60, c: null, d: null, denom: '在座人数', scored: true },
    { code: 'VC1', name: '话语结构', tier: 'video', domain: 'st', weight: 0.0722, dir: 'interval',
      unit: 'ratio', a: 0.03, b: 0.15, c: 0.40, d: 0.65, denom: '话语总时长', scored: true },
    { code: 'VC2', name: '活动结构', tier: 'video', domain: 'st', weight: 0.0515, dir: 'combo',
      unit: '0–1', a: 0, b: 1, c: null, d: null, denom: '环节完整度', scored: true },
    { code: 'VC3', name: '目标达成', tier: 'video', domain: 'listed', weight: null, dir: 'listed',
      unit: '得分率', a: null, b: null, c: null, d: null, denom: '当堂检测', scored: false }
  ];

  var DOMAINS = {
    tm: { name: '目标匹配度', weight: 0.40, tier: 'audio' },
    ts: { name: '授课状态', weight: 0.60, tier: 'audio' },
    tb: { name: '教师行为', weight: 0.4124, tier: 'video' },
    ss: { name: '学生状态', weight: 0.4639, tier: 'video' },
    st: { name: '互动结构', weight: 0.1237, tier: 'video' },
    gate: { name: '合规门禁', weight: null, tier: 'audio' },
    listed: { name: '结果层（列示）', weight: null, tier: 'video' }
  };

  /* ---------------------------------------------------------------- 量尺 */

  function clip01(x) { return Math.max(0, Math.min(1, x)); }

  /**
   * 按 indicator_config 的量尺把原始量映射为 0–100 分项分。
   * 实现只有一份，在 ui.js 的 UI.scale（与服务端 core/membership.py 同构）；
   * 这里保留同名入口，是为了让 mock 数据仍能独立算分，界面代码统一调 UI.scale。
   */
  function scale(ind, raw) {
    return global.UI ? global.UI.scale(ind, raw) : null;
  }

  /* ---------------------------------------------------------------- 课程与场次 */

  var COURSES = [
    {
      id: 'C-20261105-01', title: '新员工安全生产培训',
      expected_students: 42, created_at: '2026-11-05T08:10:00+08:00',
      goals: [
        { text: '能识别车间三类高危作业场景', tier: 'core' },
        { text: '能正确佩戴与检查个人防护装备', tier: 'core' },
        { text: '能说明事故上报与应急处置流程', tier: 'core' },
        { text: '了解班组安全责任制的基本要求', tier: 'support' }
      ]
    },
    {
      id: 'C-20261104-02', title: '骨干教师课堂提问技巧',
      expected_students: 24, created_at: '2026-11-04T09:00:00+08:00',
      goals: [
        { text: '能区分封闭式与开放式提问的适用场景', tier: 'core' },
        { text: '能在讲授中设计至少两轮追问', tier: 'core' },
        { text: '能控制候答时长不低于 3 秒', tier: 'support' }
      ]
    },
    {
      id: 'C-20261103-01', title: '现场急救处置实训',
      expected_students: 30, created_at: '2026-11-03T13:30:00+08:00',
      goals: [
        { text: '能完成成人心肺复苏的标准按压流程', tier: 'core' },
        { text: '能正确使用 AED 并完成电极片粘贴', tier: 'core' },
        { text: '能判断现场环境安全并呼叫支援', tier: 'support' }
      ]
    }
  ];

  var SESSIONS = [
    {
      id: 'S-20261105-03', course_id: 'C-20261105-01', title: '第三讲 高处作业防护',
      scenario: 'theory', consent_confirmed: true, teacher: 'T-014', room: 'A-302',
      date: '2026-11-05', start: '13:30', duration_min: 90, students: 42,
      status: 'ok', stage: 'report',
      nulls: ['B3'],
      overrides: {},
      vb1Valley: { from: 760, to: 1090, min: 0.41 }
    },
    {
      id: 'S-20261104-02', course_id: 'C-20261104-02', title: '第二讲 追问的设计与候答',
      scenario: 'seminar', consent_confirmed: true, teacher: 'T-021', room: 'B-105',
      date: '2026-11-04', start: '09:00', duration_min: 90, students: 24,
      status: 'divergent', stage: 'report',
      nulls: ['B3'],
      overrides: { A2: 0.70, A3: 0.78, B6: 0.62, VB1: 0.44, VB2: 0.22, VB3: 0.22, VC1: 0.55 },
      vb1Valley: { from: 1200, to: 1680, min: 0.33 }
    },
    {
      id: 'S-20261103-01', course_id: 'C-20261103-01', title: '实操单元 心肺复苏与 AED',
      scenario: 'practical', consent_confirmed: true, teacher: 'T-008', room: '实训楼 C-1',
      date: '2026-11-03', start: '13:30', duration_min: 120, students: 30,
      status: 'insufficient', stage: 'report',
      nulls: ['B3', 'B2', 'B4', 'B5', 'B6', 'VA3', 'VA4', 'VA5', 'VB1'],
      overrides: {},
      vb1Valley: null
    },
    {
      id: 'S-20261105-04', course_id: 'C-20261105-01', title: '第四讲 用电安全与检修挂牌',
      scenario: 'theory', consent_confirmed: true, teacher: 'T-014', room: 'A-302',
      date: '2026-11-05', start: '15:30', duration_min: 90, students: 41,
      status: 'processing', stage: 'preprocess',
      nulls: [], overrides: {}, vb1Valley: null
    }
  ];

  /* 基准原始量（S-20261105-03），其余场次按 overrides 覆盖 */
  var BASE_RAW = {
    A1: 0.82, A2: 0.62, A3: 0.68, B1: 178, B2: 0.74, B3: null, B4: 0.81, B5: 0.70, B6: 0.45,
    VA1: 9, VA2: 0.66, VA3: 0.52, VA4: 7, VA5: 0.32,
    VB1: 0.68, VB2: 0.12, VB3: 0.34, VC1: 0.48, VC2: 0.75
  };

  var EVIDENCE_T = {
    A1: 96, A2: 750, A3: 2410, B1: 1820, B2: 2380, B3: null, B4: 2960, B5: 3420, B6: 2110,
    VA1: 1260, VA2: 430, VA3: 880, VA4: 1620, VA5: 2760,
    VB1: 760, VB2: 1340, VB3: 2110, VC1: 1520, VC2: 60
  };

  var NOTE = {
    A1: '前 5 分钟内陈述 3 条学习结果，未夹带章节标题',
    A2: '核心目标 3/3 命中；语义相似度与 LLM 判定一致',
    A3: '离题段落 2 段（设备采购闲聊），共 4 分 10 秒',
    B1: '净发音速率中位数 178 字/分，P10 142、P90 236',
    B2: '句末降调占比 0.71，重音落点与术语一致',
    B3: '无盲听数据；无人工环节下该指标不可得',
    B4: '犹豫 14 次、重启 5 次，必要修正 7 次未扣分',
    B5: '结构提示 9 处，术语解释 6 个，案例 2 例',
    B6: '有效提问 11 次，有回应 5 次，平均候答 2.1 秒',
    VA1: '手势 9 次/分；内容性占比记空值（需人工编码）',
    VA2: '开放姿态占 0.66，抱臂累计 1 分 52 秒',
    VA3: '学生区注视 0.52，扫视 27 次',
    VA4: '走动 7 次/课时，九宫格覆盖 6 格',
    VA5: '疑似念读 0.32，主要为条款逐条宣读',
    VB1: '抬头率均值 0.68，12:40 起连续 5 分 30 秒低于警戒线',
    VB2: '非教学手机使用 0.12，集中于 22–27 分钟',
    VB3: '举手 6 人次，应答 14 人次',
    VC1: '学生话语占比 0.48，提问—回应链 9 组',
    VC2: '导入／讲授／互动／小结四项齐备'
  };

  var SOURCE_TRACK = {
    A2: ['audio', 'slides'], A3: ['audio', 'slides'], B5: ['audio', 'slides'],
    VA5: ['video', 'audio', 'slides'], VC1: ['video', 'audio'], VC2: ['video', 'audio'],
    VB3: ['video', 'audio'], VB1: ['video'], VB2: ['video'], VA1: ['video'],
    VA2: ['video'], VA3: ['video'], VA4: ['video']
  };

  function getSession(id) {
    for (var i = 0; i < SESSIONS.length; i++) if (SESSIONS[i].id === id) return SESSIONS[i];
    return SESSIONS[0];
  }

  function getCourse(id) {
    for (var i = 0; i < COURSES.length; i++) if (COURSES[i].id === id) return COURSES[i];
    return COURSES[0];
  }

  /* ---------------------------------------------------------------- 观测值 */

  function observations(sessionId) {
    var s = getSession(sessionId);
    return INDICATORS.map(function (ind) {
      var raw = BASE_RAW[ind.code];
      if (s.overrides[ind.code] !== undefined) raw = s.overrides[ind.code];
      if (s.nulls.indexOf(ind.code) >= 0) raw = null;
      if (ind.code === 'B3') raw = null;
      if (raw === undefined) raw = null;   // C1／VC3 无基准量，按空值处理

      var score = scale(ind, raw);
      var conf = null;
      if (raw !== null) conf = ind.dir === 'gate' || ind.dir === 'listed' ? null : 0.72 + (score / 100) * 0.22;

      var empty = null;
      if (raw === null) {
        if (ind.code === 'B3') empty = '无盲听数据：无人工环节下该指标不可得';
        else if (ind.dir === 'gate') empty = '未检出候选事件，门禁通过';
        else if (ind.dir === 'listed') empty = '列示项：本项目不设当堂测验，无数据来源';
        else empty = '门禁未通过或数据缺失，不予输出';
      }

      return {
        code: ind.code,
        name: ind.name,
        tier: ind.tier,
        domain: ind.domain,
        weight: ind.weight,
        raw_value: raw,
        denominator: ind.denom,
        unit: ind.unit,
        score: score,
        confidence: conf === null ? null : Math.round(conf * 100) / 100,
        evidence_t: raw === null ? null : EVIDENCE_T[ind.code],
        source_track: SOURCE_TRACK[ind.code] || ['audio'],
        note: NOTE[ind.code],
        empty_reason: empty
      };
    });
  }

  /* ---------------------------------------------------------------- 评价快照 */

  function evaluation(sessionId) {
    var s = getSession(sessionId);
    var items = observations(sessionId);
    var audio = items.filter(function (x) { return x.tier === 'audio' && INDICATORS.filter(function (i) { return i.code === x.code; })[0].scored; });
    var video = items.filter(function (x) { return x.tier === 'video' && INDICATORS.filter(function (i) { return i.code === x.code; })[0].scored; });

    function agg(list) {
      var w = 0, sum = 0, n = 0;
      list.forEach(function (x) {
        if (x.score === null) return;
        w += x.weight; sum += x.weight * x.score; n++;
      });
      return {
        score: Math.round(sum * 10) / 10,
        coverage: Math.round(w * 1000) / 1000,
        items: n,
        weight_sum: Math.round(w * 10000) / 10000
      };
    }

    var A = agg(audio), V = agg(video);
    var missing = items.filter(function (x) { return x.score === null; }).map(function (x) {
      return { code: x.code, name: x.name, reason: x.empty_reason, weight: x.weight || 0 };
    });

    var delta = Math.round((A.score - V.score) * 10) / 10;
    var status = 'aligned';
    if (A.coverage < 0.6 || V.coverage < 0.6) status = 'insufficient';
    else if (Math.abs(delta) >= 15) status = 'divergent';

    var flags = [];
    if (A.coverage < 1) {
      flags.push({ key: 'coverage_partial', level: 'info',
        text: 'B3 未输出，音频覆盖率 ' + A.coverage.toFixed(2) + '；按规则三不补零、不重分权' });
    }
    if (s.status === 'divergent') {
      flags.push({ key: 'divergent', level: 'warn',
        text: '两模态分差 ' + Math.abs(delta).toFixed(1) + ' 分，方向相反，标为证据不一致' });
    }
    if (s.status === 'insufficient') {
      flags.push({ key: 'insufficient', level: 'danger',
        text: '双模态覆盖率均低于 0.60，暂停输出模态分，只列可用分项' });
    }

    var shortBoard = [];
    if (s.vb1Valley) {
      shortBoard.push({ key: 'vb1_valley', downgrade: true,
        text: fmtTime(s.vb1Valley.from) + '–' + fmtTime(s.vb1Valley.to) +
              ' 连续 ' + Math.round((s.vb1Valley.to - s.vb1Valley.from) / 60) + ' 分钟抬头率低于警戒线，谷值 ' +
              Math.round(s.vb1Valley.min * 100) + '%' });
    }
    shortBoard.push({ key: 'vc2_complete', downgrade: false, text: '导入／讲授／互动／小结四项齐备，结构完整' });

    return {
      session_id: sessionId,
      config_version: '2026-11-01',
      audio: A,
      video: V,
      composite: null,
      consistency: {
        status: status, delta: delta,
        divergent: status === 'divergent' ? ['A2/A3 ↔ VB1/VB3'] : []
      },
      flags: flags,
      short_board: shortBoard,
      missing: missing,
      independent: { goal_attainment: null }
    };
  }

  function fmtTime(sec) {
    var m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  /* ---------------------------------------------------------------- 媒资 */

  function media(sessionId) {
    var s = getSession(sessionId);
    if (s.stage === 'created') return [];
    var base = [
      { type: 'video', slot: 'cam1', name: 'cam1_4k.mp4', bytes: 16106127360, duration_s: s.duration_min * 60,
        probe: { width: 3840, height: 2160, fps: 25, codec: 'hevc', bitrate_mbps: 16.2 }, retention_days: 7 },
      { type: 'video', slot: 'cam2', name: 'cam2_4k.mp4', bytes: 15032385536, duration_s: s.duration_min * 60,
        probe: { width: 3840, height: 2160, fps: 25, codec: 'hevc', bitrate_mbps: 15.1 }, retention_days: 7 },
      { type: 'audio', slot: 'lavalier', name: 'lav_48k.wav', bytes: 518000000, duration_s: s.duration_min * 60,
        probe: { sample_rate: 48000, channels: 1, bits: 16, clip: false }, retention_days: 30 },
      { type: 'audio', slot: 'ambient', name: 'amb_48k.wav', bytes: 518000000, duration_s: s.duration_min * 60,
        probe: { sample_rate: 48000, channels: 1, bits: 16, clip: false }, retention_days: 30 },
      { type: 'slides', slot: 'deck', name: '高处作业防护.pptx', bytes: 8912345,
        probe: { pages: 38, images: 12, image_only_pages: 3 }, retention_days: null }
    ];
    return base.map(function (m, i) {
      return Object.assign({}, m, {
        id: 'M-' + sessionId.slice(-5) + '-' + (i + 1),
        sha256: ('9f3a' + i + 'c1e2b4d7' + sessionId.slice(-4)).toLowerCase(),
        status: 'ok'
      });
    });
  }

  /* ---------------------------------------------------------------- 门禁 */

  function gates(sessionId) {
    var s = getSession(sessionId);
    var warnSensitivity = s.scenario !== 'practical';
    return [
      { key: 'capture_integrity', name: '采集完整性', status: 'pass', value: '4/4 通道', detail: '无丢帧，音视频偏差 12ms', action: '作废或降级，必要时重采' },
      { key: 'speech_intelligibility', name: '语音可懂度', status: 'pass', value: 'SNR 21.4 dB', detail: '低信噪比片段占 3.2%', action: '标为低证据并人工抽听' },
      { key: 'transcript_quality', name: '转写质量', status: 'pass', value: 'CER 8.1%', detail: '高置信字符 94.2%', action: '不得自动计分' },
      { key: 'role_separation', name: '角色分离', status: 'pass', value: '混淆 6.4%', detail: '重叠语音漏检 2 段', action: '互动类指标暂停输出' },
      { key: 'time_alignment', name: '时间对齐', status: 'pass', value: '偏差 0.18s', detail: '以 t=0 为课程起点', action: '重做对齐后计算' },
      { key: 'group_robustness', name: '分组稳健性', status: warnSensitivity ? 'warn' : 'pass', value: '后排误差 +9.7%', detail: '按区域加权校正', action: '触发复训或模型调整' },
      { key: 'detection_sensitivity', name: '视频检测敏感性', status: warnSensitivity ? 'warn' : 'reject', value: warnSensitivity ? '后排检测率 63%' : '后排检测率 51%', detail: warnSensitivity ? '低于 70% 建议线，VB1 已校正' : '实训场地遮挡严重，抬头率不可判定', action: '按区域加权校正或降级' },
      { key: 'frame_usability', name: '画面可用性', status: 'pass', value: '教师出画 0:38', detail: '机位 2 路覆盖', action: '相应分项不予输出' },
      { key: 'metadata_completeness', name: '元数据完整性', status: 'pass', value: '目标 4 条', detail: '课型、班额齐备', action: '目标匹配域记为空值' }
    ];
  }

  /* ---------------------------------------------------------------- 派生资产 */

  function assets(sessionId) {
    var s = getSession(sessionId);
    var frames = Math.round(s.duration_min * 60 / 10) * 2;
    return {
      items: [
        { kind: 'proxy', label: '720p 代理', count: 2, bytes: 4294967296, retention_days: 30 },
        { kind: 'frames', label: '抽帧（1 帧/10 秒）', count: frames, bytes: frames * 200000, retention_days: 30 },
        { kind: 'roi', label: 'ROI 裁切', count: 146, bytes: 284000000, retention_days: 30 },
        { kind: 'audio16k', label: '16k 单声道（送 ASR）', count: 2, bytes: 350000000, retention_days: 1 },
        { kind: 'slides', label: '课件解析 JSON', count: 1, bytes: 210000, retention_days: null }
      ],
      total_bytes: 4294967296 + frames * 200000 + 284000000 + 350000000 + 210000
    };
  }

  /* ---------------------------------------------------------------- 模型调用 */

  function aiCalls(sessionId) {
    // [capability, provider, model_version, prompt_version, tokens_in, tokens_out, latency_ms, cost, cached]
    var rows = [
      ['asr', 'asr-pro', '2026-09', 'asr-zh-v4', 0, 0, 41200, 1.28, false],
      ['asr', 'asr-pro', '2026-09', 'asr-zh-v4', 3100, 940, 38600, 1.18, false],
      ['ocr', 'ocr-doc', '2026-07', 'ocr-page-v2', 220, 60, 1420, 0.09, false],
      ['ocr', 'ocr-doc', '2026-07', 'ocr-page-v2', 180, 40, 1310, 0.08, true],
      ['embed', 'embed-l', '2026-05', 'emb-1024', 480, 0, 640, 0.02, false],
      ['llm', 'llm-chat', '2026-09', 'a2-v3', 1820, 240, 2140, 0.24, false],
      ['llm', 'llm-chat', '2026-09', 'a3-v2', 1640, 180, 1980, 0.21, false],
      ['llm', 'llm-chat', '2026-09', 'b5-v2', 2100, 320, 2410, 0.30, false],
      ['llm', 'llm-chat', '2026-09', 'b6-v1', 1480, 160, 1760, 0.19, true],
      ['vlm', 'vlm-frame', '2026-08', 'vlm-frame-v3', 9400, 620, 4820, 0.62, false],
      ['vlm', 'vlm-frame', '2026-08', 'vlm-frame-v3', 8800, 580, 4610, 0.58, false],
      ['vlm', 'vlm-frame', '2026-08', 'vlm-frame-v3', 9100, 610, 4720, 0.61, true]
    ];
    var items = rows.map(function (r, i) {
      return {
        id: 'A-' + (i + 1), capability: r[0], provider: r[1], model_version: r[2], prompt_version: r[3],
        tokens_in: r[4], tokens_out: r[5], latency_ms: r[6], cost: r[7], cached: r[8],
        at: '2026-11-05T' + (13 + Math.floor(i / 4)) + ':' + String((i * 7) % 60).padStart(2, '0') + ':00+08:00'
      };
    });
    var cached = items.filter(function (x) { return x.cached; }).length;
    return {
      items: items,
      summary: {
        // 汇总按全部调用计（本表仅抽样 12 条），与 byCapability 保持一致
        calls: 236, cached: 58, cost: 7.29,
        p95_latency_ms: 4820,
        byCapability: [
          { capability: 'asr', calls: 2, cost: 2.46 },
          { capability: 'ocr', calls: 3, cost: 0.18 },
          { capability: 'embed', calls: 1, cost: 0.02 },
          { capability: 'llm', calls: 76, cost: 1.42 },
          { capability: 'vlm', calls: 154, cost: 3.21 }
        ]
      }
    };
  }

  /* ---------------------------------------------------------------- 审计与健康 */

  function audit() {
    return [
      { id: 'L-014', action: 'report.export', object_id: 'S-20261105-03', actor: 'admin', at: '2026-11-05T19:31:00+08:00' },
      { id: 'L-013', action: 'evaluation.compute', object_id: 'S-20261105-03', actor: 'system', at: '2026-11-05T19:28:00+08:00' },
      { id: 'L-012', action: 'observation.write', object_id: 'S-20261105-03', actor: 'system', at: '2026-11-05T19:26:00+08:00' },
      { id: 'L-011', action: 'preprocess.succeeded', object_id: 'S-20261105-03', actor: 'system', at: '2026-11-05T19:21:00+08:00' },
      { id: 'L-010', action: 'media.upload', object_id: 'S-20261105-03', actor: 'admin', at: '2026-11-05T19:14:00+08:00' },
      { id: 'L-009', action: 'session.create', object_id: 'S-20261105-03', actor: 'admin', at: '2026-11-05T19:12:00+08:00' }
    ];
  }

  function health() {
    return {
      status: 'ok', db: 'sqlite', storage_free_gb: 3120,
      providers: { asr: 'ok', ocr: 'ok', embed: 'ok', llm: 'degraded', vlm: 'ok' },
      version: '0.1.0',
      pipeline: { consistency_rate: 0.86, cer: 0.081, der: 0.064, gate_block_rate: 0.07, low_conf_rate: 0.12 }
    };
  }

  /* ---------------------------------------------------------------- 任务 */

  function task(sessionId) {
    var s = getSession(sessionId);
    if (s.stage === 'preprocess') {
      return { id: 'T-77a1', session_id: sessionId, kind: 'preprocess', status: 'running',
        progress: 0.62, stage: 'extract', error: null, started_at: '2026-11-05T15:40:00+08:00' };
    }
    return { id: 'T-77a0', session_id: sessionId, kind: 'preprocess', status: 'succeeded',
      progress: 1, stage: 'gate', error: null, started_at: '2026-11-05T13:35:00+08:00' };
  }

  /* ---------------------------------------------------------------- 总览 */

  function overview() {
    var rows = SESSIONS.map(function (s) {
      var ev = s.status === 'processing' ? null : evaluation(s.id);
      // 覆盖率不足时不展示模态分（规则三），列表与详情页口径一致
      var shown = ev && ev.consistency.status !== 'insufficient';
      return {
        id: s.id, title: s.title, course: getCourse(s.course_id).title,
        date: s.date, start: s.start, scenario: s.scenario, teacher: s.teacher,
        students: s.students, status: s.status, stage: s.stage,
        audio: shown ? ev.audio.score : null, video: shown ? ev.video.score : null,
        coverage: ev ? Math.min(ev.audio.coverage, ev.video.coverage) : null
      };
    });

    // 覆盖率均值随场次数据算出，避免与课次表两个数字打架
    var withCov = rows.filter(function (r) { return r.coverage !== null; });
    var avgCov = withCov.length
      ? withCov.reduce(function (a, r) { return a + r.coverage; }, 0) / withCov.length
      : 0;

    return {
      sessions: rows,
      kpis: {
        total: SESSIONS.length,
        reported: SESSIONS.filter(function (s) { return s.stage === 'report'; }).length,
        avg_coverage: avgCov,
        monthly_cost: 7.29
      },
      health: health()
    };
  }

  /* ---------------------------------------------------------------- 指标配置 */

  function indicators() {
    return {
      config_version: '2026-11-01',
      published_at: '2026-11-01T00:00:00+08:00',
      items: INDICATORS.map(function (i) {
        return {
          code: i.code, name: i.name, tier: i.tier, domain: i.domain,
          domain_name: DOMAINS[i.domain].name, domain_weight: DOMAINS[i.domain].weight,
          weight: i.weight, direction: i.dir, a: i.a, b: i.b, c: i.c, d: i.d,
          unit: i.unit, denominator_rule: i.denom, scored: i.scored
        };
      })
    };
  }

  /* ---------------------------------------------------------------- 报告 */

  function report(sessionId) {
    var ev = evaluation(sessionId);
    var s = getSession(sessionId);
    var items = observations(sessionId);
    return {
      session: {
        id: s.id, title: s.title, course: getCourse(s.course_id).title,
        scenario: s.scenario, date: s.date, start: s.start,
        duration_min: s.duration_min, students: s.students, teacher: s.teacher, room: s.room
      },
      coverage: {
        gate: s.status === 'insufficient' ? 'reject' : 'warn',
        audio: ev.audio.coverage, video: ev.video.coverage,
        missing: ev.missing, gate_items: gates(sessionId)
      },
      audio_items: items.filter(function (x) { return x.tier === 'audio' && x.code !== 'C1'; }),
      video_items: items.filter(function (x) { return x.tier === 'video' && x.code !== 'VC3'; }),
      scores: { audio: ev.audio.score, video: ev.video.score },
      consistency: { status: ev.consistency.status, delta: ev.consistency.delta,
        note: ev.consistency.status === 'aligned' ? '两模态判断方向一致' :
              ev.consistency.status === 'divergent' ? '两模态判断方向相反，标为证据不一致，不取平均' :
              '覆盖率不足，暂不做一致性判定' },
      compliance: { items: [], note: '未检出候选事件；C1 不进加权，独立成节' },
      short_board: ev.short_board
    };
  }

  /* 供 M6 页画抬头率时序 */
  function vb1Series(sessionId) {
    var s = getSession(sessionId);
    var pts = [], v = 0.74, seed = sessionId.charCodeAt(sessionId.length - 1);
    for (var t = 0; t <= s.duration_min * 60; t += 60) {
      seed = (seed * 9301 + 49297) % 233280;
      var noise = (seed / 233280 - 0.5) * 0.09;
      var base = 0.76 + 0.10 * Math.sin(t / 900);
      if (s.vb1Valley && t >= s.vb1Valley.from && t <= s.vb1Valley.to) {
        base = s.vb1Valley.min + 0.04 * Math.sin(t / 240);
      }
      v = Math.max(0.18, Math.min(0.96, base + noise));
      pts.push({ t: t, v: Math.round(v * 1000) / 1000 });
    }
    return pts;
  }

  global.Mock = {
    INDICATORS: INDICATORS,
    DOMAINS: DOMAINS,
    scale: scale,
    courses: COURSES,
    sessions: SESSIONS,
    getSession: getSession,
    getCourse: getCourse,
    observations: observations,
    evaluation: evaluation,
    media: media,
    gates: gates,
    assets: assets,
    aiCalls: aiCalls,
    audit: audit,
    health: health,
    task: task,
    overview: overview,
    indicators: indicators,
    report: report,
    vb1Series: vb1Series,
    fmtTime: fmtTime
  };
})(window);
