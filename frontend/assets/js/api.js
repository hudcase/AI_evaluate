/**
 * api.js — 唯一数据出口
 *
 * 所有页面只通过这里取数，不直接碰 fetch，也不直接读 Mock。接真实后端时改 config.js 即可。
 * 每个方法上方注明对应的 HTTP 方法与路径，与 docs/接口约定.md 一一对应。
 */
(function (global) {
  'use strict';

  var CFG = global.APP_CONFIG;

  /* -------------------------------------------------------------- HTTP 基础 */

  function delay(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }

  function qs(params) {
    if (!params) return '';
    var parts = [];
    Object.keys(params).forEach(function (k) {
      if (params[k] === undefined || params[k] === null || params[k] === '') return;
      parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  function request(method, path, body, opts) {
    opts = opts || {};
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, CFG.timeout);
    var headers = { 'Accept': 'application/json' };
    if (body !== undefined && body !== null) headers['Content-Type'] = 'application/json';
    if (opts.headers) Object.assign(headers, opts.headers);

    return fetch(CFG.apiBase + path, {
      method: method,
      headers: headers,
      body: body === undefined || body === null ? undefined : JSON.stringify(body),
      signal: ctrl.signal
    }).then(function (res) {
      clearTimeout(timer);
      var ct = res.headers.get('content-type') || '';
      if (opts.binary) {
        if (!res.ok) {
          // 二进制请求失败时后端仍返回 JSON 错误体，把 message 带出来，别只报 HTTP 501
          var ctb = res.headers.get('content-type') || '';
          if (ctb.indexOf('application/json') >= 0) {
            return res.json().then(function (j) {
              var eb = (j && j.error) || {};
              throw toError(res.status, eb.message || 'HTTP ' + res.status,
                eb.code || 'HTTP_' + res.status);
            });
          }
          throw toError(res.status, 'HTTP ' + res.status, null);
        }
        return res.blob();
      }
      if (ct.indexOf('application/json') < 0) {
        return res.text().then(function (t) { return { ok: res.ok, text: t, status: res.status }; });
      }
      return res.json().then(function (json) {
        if (!res.ok) {
          var e = (json && json.error) || {};
          throw toError(res.status, e.message || 'HTTP ' + res.status, e.code || 'HTTP_' + res.status, e.field);
        }
        return json;
      });
    }, function (err) {
      clearTimeout(timer);
      if (err && err.name === 'AbortError') throw toError(0, '请求超时（' + CFG.timeout + 'ms）', 'TIMEOUT');
      throw toError(0, '无法连接后端 ' + CFG.apiBase, 'NETWORK_ERROR');
    });
  }

  function toError(status, message, code, field) {
    var e = new Error(message);
    e.status = status;
    e.code = code || 'UNKNOWN';
    e.field = field || null;
    return e;
  }

  /* -------------------------------------------------------------- 统一出口 */

  /** GET 或 mock */
  function call(mockFn, method, path, body, opts) {
    if (CFG.useMock) {
      return delay(140 + Math.random() * 120).then(function () {
        return mockFn();
      });
    }
    return request(method, path, body, opts);
  }

  function fail(code, message) {
    return Promise.reject(toError(400, message, code));
  }

  var Api = {

    /* ---------------- 总览（聚合，后端可另开 /api/overview） ---------------- */

    /** GET /api/overview — 课次列表 + KPI + 健康状态 */
    getOverview: function () {
      return call(function () { return Mock.overview(); }, 'GET', '/api/overview');
    },

    /** GET /api/health */
    getHealth: function () {
      return call(function () { return Mock.health(); }, 'GET', '/api/health');
    },

    /* ---------------- M1 建档 ---------------- */

    /** GET /api/courses */
    getCourses: function () {
      return call(function () {
        return { items: Mock.courses, total: Mock.courses.length, page: 1, size: 20 };
      }, 'GET', '/api/courses');
    },

    /** GET /api/courses/{id} */
    getCourse: function (id) {
      return call(function () {
        var c = Mock.getCourse(id);
        var sessions = Mock.sessions.filter(function (s) { return s.course_id === id; });
        return Object.assign({}, c, { sessions: sessions });
      }, 'GET', '/api/courses/' + encodeURIComponent(id));
    },

    /** POST /api/courses */
    createCourse: function (payload) {
      if (!payload.title || payload.title.length > 100) return fail('VALIDATION_FAILED', '课程标题需为 1–100 字符');
      if (!payload.goals || !payload.goals.length) return fail('VALIDATION_FAILED', '至少填写 1 条课程目标');
      var core = payload.goals.filter(function (g) { return g.tier === 'core'; });
      if (!core.length) return fail('VALIDATION_FAILED', '至少标记 1 条核心目标，A2 覆盖率以其权重和为分母');
      return call(function () {
        var id = 'C-' + new Date().toISOString().slice(0, 10).replace(/-/g, '') + '-' + (Mock.courses.length + 1);
        Mock.courses.push(Object.assign({ id: id, created_at: new Date().toISOString() }, payload));
        return { id: id };
      }, 'POST', '/api/courses', payload);
    },

    /** DELETE /api/courses/{id}?confirm=true */
    deleteCourse: function (id) {
      return call(function () {
        var idx = -1;
        Mock.courses.forEach(function (c, i) { if (c.id === id) idx = i; });
        if (idx >= 0) Mock.courses.splice(idx, 1);
        Mock.sessions = Mock.sessions.filter(function (s) { return s.course_id !== id; });
        return { id: id, deleted_sessions: 1 };
      }, 'DELETE', '/api/courses/' + encodeURIComponent(id) + qs({ confirm: true }));
    },

    /** POST /api/import — 批量入库（manifest 清单） */
    importBatch: function (manifest) {
      return call(function () {
        // 演示模式：本地串行走 createCourse/createSession 的 mock 逻辑，返回同样的汇总形状
        var summary = { courses: 0, sessions: 0, assets: 0, observations: 0, duplicate: 0, failed: 0, items: [] };
        (manifest.courses || []).forEach(function (c) {
          var cr = { title: c.title, ok: true, reused: false, sessions: [] };
          summary.courses++;
          (c.sessions || []).forEach(function (s) {
            summary.sessions++;
            cr.sessions.push({ title: s.title, ok: true, reused: false, assets: [], observations: [] });
          });
          summary.items.push(cr);
        });
        return summary;
      }, 'POST', '/api/import', manifest);
    },

    /** POST /api/sessions */
    createSession: function (payload) {
      if (!payload.consent_confirmed) return fail('CONSENT_REQUIRED', '未确认知情同意，场次不得入库');
      if (['theory', 'seminar', 'practical'].indexOf(payload.scenario) < 0) {
        return fail('VALIDATION_FAILED', '课型需为 theory / seminar / practical');
      }
      return call(function () {
        var id = 'S-' + new Date().toISOString().slice(0, 10).replace(/-/g, '') + '-' + (Mock.sessions.length + 1);
        Mock.sessions.push(Object.assign({
          id: id, status: 'created', stage: 'created', consent_confirmed: true,
          nulls: ['B3'], overrides: {}, vb1Valley: null,
          date: new Date().toISOString().slice(0, 10), start: '00:00',
          duration_min: 90, students: payload.expected_students || 0
        }, payload));
        return { id: id, status: 'created' };
      }, 'POST', '/api/sessions', payload);
    },

    /** GET /api/sessions/{id} */
    getSession: function (id) {
      return call(function () { return Mock.getSession(id); },
        'GET', '/api/sessions/' + encodeURIComponent(id));
    },

    /** GET /api/sessions/{id}/tasks — 最近的任务（预处理等） */
    getTasks: function (sessionId, kind) {
      return call(function () { return { items: [Mock.task(sessionId)] }; },
        'GET', '/api/sessions/' + sessionId + '/tasks' + qs({ kind: kind || 'preprocess', limit: 20 }));
    },

    /* ---------------- M2 数据接入 ---------------- */

    /** GET /api/sessions/{id}/media */
    getMedia: function (sessionId) {
      return call(function () { return { items: Mock.media(sessionId) }; },
        'GET', '/api/sessions/' + sessionId + '/media');
    },

    /** POST /api/sessions/{id}/media */
    uploadMedia: function (sessionId, payload) {
      return call(function () {
        return {
          asset_id: 'M-' + Math.random().toString(36).slice(2, 8),
          type: payload.type, slot: payload.slot,
          sha256: Math.random().toString(16).slice(2, 10) + 'c1e2b4d7',
          bytes: payload.bytes || 0, retention_days: payload.type === 'video' ? 7 : 30,
          probe: payload.probe || {}, duplicate: false
        };
      }, 'POST', '/api/sessions/' + sessionId + '/media', payload);
    },

    /** DELETE /api/sessions/{id}/media/{asset_id}?confirm=true&purge=false */
    deleteMediaAsset: function (sessionId, assetId, purge) {
      return call(function () {
        return { deleted: [assetId], freed_bytes: 0, file: 'none', remaining: 0,
          stale: false, note: '演示模式：未真正删除' };
      }, 'DELETE', '/api/sessions/' + sessionId + '/media/' + encodeURIComponent(assetId)
        + qs({ confirm: true, purge: purge ? true : undefined }));
    },

    /* ---------------- M3 数据治理 ---------------- */

    /** POST /api/sessions/{id}/preprocess */
    preprocess: function (sessionId, stages) {
      return call(function () {
        return { task_id: 'T-' + Math.random().toString(36).slice(2, 7), status: 'queued', stages: stages || 'all' };
      }, 'POST', '/api/sessions/' + sessionId + '/preprocess', { stages: stages, async: true });
    },

    /** GET /api/tasks/{id} */
    getTask: function (taskId) {
      return call(function () { return Mock.task(Mock.sessions[0].id); },
        'GET', '/api/tasks/' + taskId);
    },

    /** GET /api/sessions/{id}/qc — 九项门禁 */
    getQc: function (sessionId) {
      return call(function () {
        var gs = Mock.gates(sessionId);
        var worst = gs.some(function (g) { return g.status === 'reject'; }) ? 'reject'
          : gs.some(function (g) { return g.status === 'warn'; }) ? 'warn' : 'pass';
        return { overall: worst, gates: gs };
      }, 'GET', '/api/sessions/' + sessionId + '/qc');
    },

    /** GET /api/sessions/{id}/assets */
    getAssets: function (sessionId) {
      return call(function () { return Mock.assets(sessionId); },
        'GET', '/api/sessions/' + sessionId + '/assets');
    },

    /* ---------------- M4 模型 ---------------- */

    /** GET /api/sessions/{id}/ai-calls */
    getAiCalls: function (sessionId) {
      return call(function () { return Mock.aiCalls(sessionId); },
        'GET', '/api/sessions/' + sessionId + '/ai-calls');
    },

    /* ---------------- M5 指标计算 ---------------- */

    /** GET /api/sessions/{id}/observations */
    getObservations: function (sessionId) {
      return call(function () { return { items: Mock.observations(sessionId) }; },
        'GET', '/api/sessions/' + sessionId + '/observations');
    },

    /** POST /api/sessions/{id}/observations */
    postObservation: function (sessionId, payload) {
      if (payload.evidence_note && payload.evidence_note.length > 120) {
        return fail('VALIDATION_FAILED', 'evidence_note 不得超过 120 字符');
      }
      if (/\d{11}|\d{17}[\dXx]|[\w.+-]+@[\w-]+\.[\w.]+/.test(payload.evidence_note || '')) {
        return fail('PII_DETECTED', 'evidence_note 含手机号／身份证／邮箱等直接标识');
      }
      return call(function () {
        var ind = null;
        Mock.INDICATORS.forEach(function (i) { if (i.code === payload.code) ind = i; });
        return {
          id: 'O-' + Math.random().toString(36).slice(2, 7),
          code: payload.code,
          score: ind ? Mock.scale(ind, payload.raw_value) : null,
          confidence: payload.confidence,
          coverage_after: 0.9
        };
      }, 'POST', '/api/sessions/' + sessionId + '/observations', payload);
    },

    /** POST /api/sessions/{id}/score */
    rescore: function (sessionId, configVersion) {
      return call(function () {
        return { scored: 19, empty: 2, audio_coverage: 0.9, video_coverage: 1.0 };
      }, 'POST', '/api/sessions/' + sessionId + '/score', { config_version: configVersion });
    },

    /* ---------------- M6 合成与一致性 ---------------- */

    /** GET /api/sessions/{id}/evaluation */
    getEvaluation: function (sessionId) {
      return call(function () { return Mock.evaluation(sessionId); },
        'GET', '/api/sessions/' + sessionId + '/evaluation');
    },

    /** GET /api/sessions/{id}/vb1-series — 抬头率时序（报告附件） */
    getVb1Series: function (sessionId) {
      return call(function () { return { points: Mock.vb1Series(sessionId) }; },
        'GET', '/api/sessions/' + sessionId + '/vb1-series');
    },

    /* ---------------- M7 报告与审计 ---------------- */

    /** GET /api/sessions/{id}/report?format=json */
    getReport: function (sessionId) {
      return call(function () { return Mock.report(sessionId); },
        'GET', '/api/sessions/' + sessionId + '/report' + qs({ format: 'json' }));
    },

    /** GET /api/sessions/{id}/report?format=pdf|docx — 返回 Blob */
    exportReport: function (sessionId, format) {
      if (CFG.useMock) {
        return delay(600).then(function () {
          if (format === 'json') {
            return new Blob([JSON.stringify(Mock.report(sessionId), null, 2)], { type: 'application/json' });
          }
          // 演示模式下不生成真二进制，返回说明文本
          var note = '演示模式：' + format.toUpperCase() + ' 由后端渲染。\n' +
            '接入真实后端后，本请求命中 GET /api/sessions/' + sessionId + '/report?format=' + format +
            '，返回二进制流。\n';
          return new Blob([note], { type: 'text/plain;charset=utf-8' });
        });
      }
      return request('GET', '/api/sessions/' + sessionId + '/report' + qs({ format: format }), null, { binary: true });
    },

    /** GET /api/indicators */
    getIndicators: function () {
      return call(function () { return Mock.indicators(); }, 'GET', '/api/indicators');
    },

    /** PUT /api/indicators */
    putIndicators: function (payload) {
      return call(function () {
        return { config_version: payload.config_version, changed: (payload.items || []).length };
      }, 'PUT', '/api/indicators', payload);
    },

    /** GET /api/audit */
    getAudit: function (page) {
      return call(function () {
        var rows = Mock.audit();
        return { items: rows, total: rows.length, page: page || 1, size: 50 };
      }, 'GET', '/api/audit' + qs({ page: page || 1, size: 50 }));
    },

    /** DELETE /api/sessions/{id}/media?scope=raw&confirm=true */
    deleteMedia: function (sessionId, scope) {
      return call(function () {
        var items = Mock.media(sessionId);
        return {
          deleted: items.filter(function (m) { return scope === 'all' || (scope === 'raw' && m.type !== 'slides'); })
            .map(function (m) { return m.id; }),
          freed_bytes: 16106127360 + 15032385536
        };
      }, 'DELETE', '/api/sessions/' + sessionId + '/media' + qs({ scope: scope, confirm: true }));
    }
  };

  global.Api = Api;
})(window);
