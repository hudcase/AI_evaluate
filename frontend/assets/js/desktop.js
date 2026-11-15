/**
 * desktop.js — 桌面端能力探针与原生调用
 *
 * 浏览器给不了"真实路径"：<input type=file> 拿到的是 C:\fakepath\...，而本系统的
 * 入库策略是就地登记（几十 GB 原片只记路径、不搬字节），路径必须是真的。所以桌面版
 * 把"选文件"交给后端进程去做，前端只发一个请求。
 *
 * 所有方法在浏览器模式下都返回"不可用"，调用方据此隐藏原生按钮——
 * 界面不应该出现点了没反应的按钮。
 *
 * 注意超时：原生对话框会一直阻塞到用户点确定／取消，不能套用 api.js 那 15 秒超时。
 */
(function (global) {
  'use strict';

  var info = null;
  var inited = false;
  var DIALOG_TIMEOUT = 30 * 60 * 1000;      // 30 分钟：人在翻文件夹，别催

  var FILTERS = {
    media: ['视频|*.mp4;*.mov;*.mkv;*.avi;*.m4v',
            '音频|*.wav;*.flac;*.mp3;*.m4a;*.aac;*.ogg',
            '课件|*.pptx;*.pdf'],
    video: ['视频|*.mp4;*.mov;*.mkv;*.avi;*.m4v'],
    audio: ['音频|*.wav;*.flac;*.mp3;*.m4a;*.aac;*.ogg'],
    slides: ['课件|*.pptx;*.pdf'],
    docx: ['Word 文档|*.docx'],
    html: ['网页|*.html'],
    json: ['JSON|*.json']
  };

  function fail(code, message) {
    var e = new Error(message);
    e.code = code;
    return e;
  }

  function req(method, path, body, timeoutMs) {
    var ctrl = new AbortController();
    var timer = timeoutMs ? setTimeout(function () { ctrl.abort(); }, timeoutMs) : null;
    var opts = { method: method, headers: { 'Accept': 'application/json' }, signal: ctrl.signal };
    if (body !== undefined && body !== null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    function done() { if (timer) clearTimeout(timer); }

    return fetch(path, opts).then(function (resp) {
      return resp.text().then(function (txt) {
        var data = null;
        try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
        if (!resp.ok) {
          var err = (data && data.error) || {};
          throw fail(err.code || ('HTTP_' + resp.status),
                     err.message || ('请求失败（' + resp.status + '）'));
        }
        return data;
      });
    }).then(function (data) { done(); return data; },
            function (err) {
              done();
              if (err && err.name === 'AbortError') {
                throw fail('TIMEOUT', '等待超时：原生对话框可能仍开着，请回到窗口处理');
              }
              throw err;
            });
  }

  var Desktop = {
    filters: FILTERS,

    /** 登录能力信息；失败也算成功（退回浏览器模式），不阻塞首屏 */
    init: function () {
      if (inited) return Promise.resolve(info);
      inited = true;
      return req('GET', '/api/desktop/info').then(function (d) {
        info = d || { desktop: false };
        return info;
      }).catch(function () {
        info = { desktop: false, available: false };
        return info;
      });
    },

    info: function () { return info; },

    isDesktop: function () { return !!(info && info.desktop); },

    /** 选择文件夹 → 绝对路径；取消返回 null */
    pickFolder: function (title, initial) {
      return req('POST', '/api/desktop/dialog/folder',
                 { title: title || '选择文件夹', initial: initial || '' }, DIALOG_TIMEOUT)
        .then(function (r) { return r && r.path ? r.path : null; });
    },

    /** 选择文件 → 绝对路径数组；取消返回 [] */
    pickFiles: function (title, filters, initial, multiselect) {
      return req('POST', '/api/desktop/dialog/files',
                 { title: title || '选择文件', filters: filters || FILTERS.media,
                   initial: initial || '', multiselect: multiselect !== false },
                 DIALOG_TIMEOUT)
        .then(function (r) { return (r && r.paths) || []; });
    },

    pickSave: function (title, filename, filters, defaultExt) {
      return req('POST', '/api/desktop/dialog/save',
                 { title: title || '另存为', filename: filename || '',
                   filters: filters || FILTERS.media, default_ext: defaultExt || '' },
                 DIALOG_TIMEOUT)
        .then(function (r) { return r && r.path ? r.path : null; });
    },

    /** 目录 → 批量入库清单（含 issues 与统计），供人工确认后再提交 */
    scan: function (root, opts) {
      opts = opts || {};
      return req('POST', '/api/desktop/scan', {
        root: root, consent: opts.consent !== false,
        scenario: opts.scenario || 'theory',
        duration_min: opts.durationMin || 90
      }, 120000);
    },

    /** 报告另存为：对话框选路径 → 后端直接落盘（不经浏览器下载目录） */
    saveReport: function (sessionId, format, suggested) {
      var f = format === 'json' ? FILTERS.json : (format === 'html' ? FILTERS.html : FILTERS.docx);
      var name = suggested || ('课堂教学质量评估报告-' + sessionId + '.' + format);
      return Desktop.pickSave('导出报告', name, f, format).then(function (path) {
        if (!path) return null;
        return req('POST', '/api/desktop/save-report',
                   { session_id: sessionId, format: format, path: path }, 120000);
      });
    },

    reveal: function (path) {
      if (!path) return Promise.resolve();
      return req('POST', '/api/desktop/reveal', { path: path }).catch(function () { /* 定位失败不打扰 */ });
    },

    quit: function () {
      return req('POST', '/api/desktop/quit', { confirm: true });
    }
  };

  global.Desktop = Desktop;
})(window);
