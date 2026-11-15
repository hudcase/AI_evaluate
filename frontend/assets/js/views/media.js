/**
 * views/media.js — M2 数据接入
 *
 * 四类输入必须齐备且规格相符才允许进入治理。缺失的卡不隐藏——缺失必须可见，
 * 否则操作者会以为"已经可以算分了"。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h, fmt = UI.fmt;
  var Views = global.Views = global.Views || {};

  var SPEC = {
    video: { label: '4K 视频', slots: ['cam1', 'cam2'], need: '3840×2160 · 25fps · H.265／H.264', retention: '7 天' },
    audio: { label: '48kHz 音频', slots: ['lavalier', 'ambient'], need: 'PCM16 · 48000 Hz · 无削波', retention: '30 天' },
    slides: { label: '课件', slots: ['deck'], need: 'PPTX 优先 · PDF 次之 · 1–300 页', retention: '至结项' }
  };

  var SLOT_NAME = { cam1: '机位 1（全景）', cam2: '机位 2（后排）', lavalier: '领夹麦', ambient: '全向麦', deck: '讲义' };

  // 演示期内"刚上传"的资产，按场次累积，不污染 mock.js 的原始数据
  var uploaded = {};
  var currentSession = {};

  function withUploaded(sessionId, items) {
    var extra = uploaded[sessionId] || [];
    var have = {};
    items.forEach(function (m) { have[m.slot] = true; });
    return items.concat(extra.filter(function (m) { return !have[m.slot]; }));
  }

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(5));
    Promise.all([
      global.Api.getMedia(ctx.sessionId),
      global.Api.getCourses(),
      global.Api.getSession(ctx.sessionId)
    ]).then(function (res) {
      render(el, ctx, withUploaded(ctx.sessionId, res[0].items), res[1].items, res[2]);
    }).catch(function (err) {
      UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
    });
  }

  function render(el, ctx, items, courses, session) {
    UI.clear(el);
    var bySlot = {};
    items.forEach(function (m) { bySlot[m.slot] = m; });

    var course = courses.filter(function (c) { return c.id === session.course_id; })[0];
    currentSession = session || {};

    /* --- 视频 --- */
    el.appendChild(UI.grid(3, [
      mediaCard(ctx, 'video', bySlot, el, items),
      mediaCard(ctx, 'audio', bySlot, el, items),
      slidesOrGoals(ctx, bySlot, course, el, items)
    ], '16px'));

    /* --- 上云清单 --- */
    el.appendChild(UI.card({
      title: '上云清单',
      sub: '外发内容仅限下列派生数据，原片与原档不出校',
      body: h('div', { class: 'upload-list' }, [
        { ok: true, name: '16kHz 单声道音频切片（60s）', note: '送 ASR；原档 48k 留本地' },
        { ok: true, name: '打码后的抽帧（长边 1280，1 帧/10 秒）', note: '送 VLM；人脸已高斯模糊' },
        { ok: true, name: 'ROI 裁切块（原分辨率）', note: '板书与后排细节，送 OCR／VLM' },
        { ok: true, name: '课件解析文本与讲稿切片', note: '仅图片页与扫描件走 OCR' },
        { ok: false, name: '4K 原片 / 48kHz 原档', note: '禁止外发' },
        { ok: false, name: '姓名、学号、人脸特征库', note: '不采集、不建库' }
      ].map(function (r) {
        return h('div', { class: 'upload-row' },
          UI.badge(r.ok ? '外发' : '禁止', r.ok ? 'ok' : 'danger'),
          h('span', { class: 'upload-name', text: r.name }),
          h('span', { class: 'upload-note', text: r.note }));
      }))
    }));
  }

  function mediaCard(ctx, type, bySlot, el, items) {
    var spec = SPEC[type];
    var filled = spec.slots.filter(function (s) { return bySlot[s]; });
    var body = h('div', { class: 'media-body' });

    spec.slots.forEach(function (slot) {
      var m = bySlot[slot];
      if (m) {
        body.appendChild(h('div', { class: 'media-slot is-ok' },
          h('div', { class: 'media-slot-head' },
            h('strong', { text: SLOT_NAME[slot] }),
            h('div', { class: 'slot-actions' },
              UI.badge('已就位', 'ok'),
              removeBtn(ctx, m, SLOT_NAME[slot], el))),
          UI.kv([
            ['文件', m.name],
            ['大小', fmt.bytes(m.bytes)],
            ['时长', fmt.time(m.duration_s)],
            ['sha256', m.sha256
              ? h('code', { class: 'code code-sm', text: m.sha256.slice(0, 12) + '…' })
              : h('span', { class: 'ta-mute', text: '未落盘（仅登记）' })],
            ['留存', m.retention_days ? m.retention_days + ' 天' : '至结项']
          ]),
          probeLine(type, m.probe)
        ));
      } else {
        body.appendChild(h('div', { class: 'media-slot is-empty' },
          h('div', { class: 'media-slot-head' },
            h('strong', { text: SLOT_NAME[slot] }),
            UI.badge('待上传', 'warn')),
          h('p', { class: 'media-hint', text: spec.need }),
          h('div', { class: 'btn-row' }, [
            /* 桌面版能拿到真实路径 → 就地登记，几十 GB 原片不搬字节；
               浏览器版只能模拟登记（演示用）。 */
            isDesktop()
              ? h('button', {
                  class: 'btn btn-primary btn-sm', text: '选择文件登记',
                  onclick: function () { pickAndRegister(ctx, type, slot, el); }
                })
              : null,
            h('button', {
              class: 'btn btn-ghost btn-sm', text: isDesktop() ? '模拟登记（演示）' : '模拟上传',
              onclick: function () { simulateUpload(ctx, type, slot, el); }
            })
          ])
        ));
      }
    });

    return UI.card({
      title: spec.label,
      sub: filled.length + '/' + spec.slots.length + ' 路就位 · 留存 ' + spec.retention,
      body: body
    });
  }

  /* 探针只报"读得出来"的项，读不出的字段不补默认值——
     补了就会把"没读到"显示成"合规"。因此每一项都先判空再放行。 */
  function probeLine(type, probe) {
    if (!probe) return null;
    var pairs = [];
    if (type === 'video') {
      if (probe.width && probe.height) pairs.push(['分辨率', probe.width + '×' + probe.height]);
      if (probe.fps) pairs.push(['帧率', probe.fps + ' fps']);
      if (probe.codec) pairs.push(['编码', probe.codec]);
      if (probe.bitrate_mbps) pairs.push(['码率', probe.bitrate_mbps + ' Mbps']);
    } else if (type === 'audio') {
      if (probe.sample_rate) pairs.push(['采样率', (probe.sample_rate / 1000) + ' kHz']);
      if (probe.channels) pairs.push(['声道', probe.channels === 1 ? '单声道' : '双声道']);
      if (probe.bits) pairs.push(['位深', probe.bits + ' bit']);
      // 后端探针给的是 clip_ratio（削波样本占比），不是布尔 clip；
      // 0.02 与 check_spec 的削波上限同源，两边不能各写一个数。
      if (typeof probe.clip_ratio === 'number') {
        pairs.push(['削波', probe.clip_ratio > 0.02
          ? '有（' + (probe.clip_ratio * 100).toFixed(2) + '%）' : '无']);
      } else if (typeof probe.clip === 'boolean') {
        pairs.push(['削波', probe.clip ? '有' : '无']);
      }
    }
    if (!pairs.length) return null;
    return h('div', { class: 'probe' }, pairs.map(function (p) {
      return h('div', { class: 'probe-item' },
        h('span', { text: p[0] }), h('strong', { text: String(p[1]) }));
    }));
  }

  function slidesOrGoals(ctx, bySlot, course, el) {
    var deck = bySlot.deck;
    var goals = course ? course.goals : [];
    // 仅登记（无字节）的课件 probe 可能为空，此时不能直接取 probe.pages，否则显示"undefined 页"
    var dp = (deck && deck.probe) || {};
    var deckRows = [];
    if (deck) {
      if (dp.pages) deckRows.push(['页数', dp.pages + ' 页']);
      if (dp.image_only_pages) deckRows.push(['图片页', dp.image_only_pages + ' 页（走 OCR）']);
      if (!dp.pages) deckRows.push(['页数', '未解析（仅登记，无文件字节）']);
      deckRows.push(['大小', fmt.bytes(deck.bytes)]);
    }

    var deckBlock = deck
      ? h('div', { class: 'media-slot is-ok' },
          h('div', { class: 'media-slot-head' },
            h('strong', { text: deck.name }),
            h('div', { class: 'slot-actions' },
              UI.badge('已就位', 'ok'),
              removeBtn(ctx, deck, '课件', el))),
          UI.kv(deckRows))
      : h('div', { class: 'media-slot is-empty' },
          h('div', { class: 'media-slot-head' },
            h('strong', { text: '讲义' }), UI.badge('待上传', 'warn')),
          h('p', { class: 'media-hint', text: SPEC.slides.need }),
          h('div', { class: 'btn-row' }, [
            isDesktop()
              ? h('button', {
                  class: 'btn btn-primary btn-sm', text: '选择文件登记',
                  onclick: function () { pickAndRegister(ctx, 'slides', 'deck', el); }
                })
              : null,
            h('button', {
              class: 'btn btn-ghost btn-sm', text: isDesktop() ? '模拟登记（演示）' : '模拟上传',
              onclick: function () { simulateUpload(ctx, 'slides', 'deck', el); }
            })
          ]));

    var goalBlock = h('div', { class: 'media-slot is-goal' },
      h('div', { class: 'media-slot-head' },
        h('strong', { text: '课程目标（文本）' }),
        UI.badge(goals.length ? goals.length + ' 条' : '缺失', goals.length ? 'ok' : 'danger')),
      h('ul', { class: 'goal-list' }, goals.map(function (g) {
        return h('li', {},
          UI.badge(g.tier === 'core' ? '核心' : g.tier === 'support' ? '支撑' : '拓展',
            g.tier === 'core' ? 'blue' : 'mute'),
          h('span', { text: g.text }));
      }))
    );

    return UI.card({
      title: '课件与目标',
      body: h('div', { class: 'media-body' }, [deckBlock, goalBlock])
    });
  }

  function isDesktop() {
    return !!(global.Desktop && global.Desktop.isDesktop());
  }

  /* 逐条删除。删掉后该 slot 立刻回到"待上传"，可以重新登记——
     传错文件、选错机位都靠这条撤销，不必整场销毁。
     盘上文件删不删由后端判定：系统自有副本（data/media 下）一并删，
     就地登记的外部原片只解除登记——那是采集机上的唯一一份。 */
  function removeBtn(ctx, m, label, el) {
    return h('button', {
      class: 'btn btn-ghost btn-sm slot-del', text: '删除',
      onclick: function () {
        UI.confirmDialog({
          title: '删除' + label,
          text: '将从本场次移除「' + m.name + '」，该槽位回到待上传。',
          detail: m.stored
            ? '系统自有副本会一并从盘上删除；若是就地登记的外部文件，只解除登记、原文件保留。'
            : '该资产仅有登记记录，盘上无字节可删。',
          okText: '删除',
          danger: true
        }).then(function (ok) {
          if (!ok) return;
          global.Api.deleteMediaAsset(ctx.sessionId, m.id).then(function (r) {
            /* 演示上传的本地缓存要同步清掉，否则重新加载又会被 withUploaded 补回来 */
            if (uploaded[ctx.sessionId]) {
              uploaded[ctx.sessionId] = uploaded[ctx.sessionId].filter(function (x) {
                return x.id !== m.id;
              });
            }
            UI.toast('已删除 ' + label + (r.stale ? '；该场次已有处理结果，需重新预处理' : ''), 'ok');
            load(el, ctx);
          }).catch(function (err) { UI.toast(err.message, 'danger'); });
        });
      }
    });
  }

  /* 桌面版：原生选文件 → 就地登记。只传路径不给字节，后端拿探针直接读盘上那个文件，
     所以 4K 原片既不进浏览器内存，也不产生第二份拷贝。 */
  function pickAndRegister(ctx, type, slot, el) {
    var filters = (global.Desktop && global.Desktop.filters[type]) || null;
    global.Desktop.pickFiles('选择' + (SPEC[type] ? SPEC[type].label : '媒体') + '文件',
                             filters, '', false)
      .then(function (paths) {
        if (!paths || !paths.length) return null;
        var path = paths[0];
        var name = path.split(/[\\/]/).pop();
        return global.Api.uploadMedia(ctx.sessionId, {
          path: path, name: name, type: type, slot: slot
        }).then(function (r) {
          UI.toast('已登记 ' + (r.asset_id || r.id || '') + '（' + SLOT_NAME[slot] + '）', 'ok');
          load(el, ctx);
        });
      })
      .catch(function (err) { UI.toast(err.message, 'danger'); });
  }

  function simulateUpload(ctx, type, slot, el) {
    var probe = type === 'video'
      ? { width: 3840, height: 2160, fps: 25, codec: 'hevc', bitrate_mbps: 15.8 }
      : type === 'audio'
        ? { sample_rate: 48000, channels: 1, bits: 16, clip: false }
        : { pages: 38, images: 12, image_only_pages: 3 };

    global.Api.uploadMedia(ctx.sessionId, {
      type: type, slot: slot, bytes: 12884901888, probe: probe
    }).then(function (r) {
      UI.toast('已登记 ' + r.asset_id + '（' + SLOT_NAME[slot] + '）', 'ok');
      uploaded[ctx.sessionId] = uploaded[ctx.sessionId] || [];
      uploaded[ctx.sessionId].push({
        id: r.asset_id, type: type, slot: slot,
        name: slot + '.' + (type === 'slides' ? 'pptx' : type === 'audio' ? 'wav' : 'mp4'),
        bytes: r.bytes, duration_s: (currentSession.duration_min || 90) * 60,
        // 探针与 sha256 以服务端回传为准：这是"登记了什么"的唯一凭据
        probe: r.probe || probe,
        retention_days: r.retention_days, sha256: r.sha256, status: r.status || 'ok'
      });
      load(el, ctx);
    }).catch(function (err) { UI.toast(err.message, 'danger'); });
  }

  Views.media = function (el, ctx) { load(el, ctx); };
})(window);
