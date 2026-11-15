/**
 * views/courses.js — M1 建档
 *
 * 左列表右详情。目标是结构化编辑：核心／支撑／拓展三档，核心目标决定 A2 的分母，
 * 因此表单里把这句话写出来，而不是让操作者猜。
 */
(function (global) {
  'use strict';
  var UI = global.UI, h = UI.h;
  var Views = global.Views = global.Views || {};

  var state = { courses: [], activeId: null, detail: null, mode: 'detail' };

  function load(el, ctx) {
    UI.clear(el).appendChild(UI.skeleton(5));
    global.Api.getCourses().then(function (d) {
      state.courses = d.items;
      if (!state.activeId && d.items.length) state.activeId = d.items[0].id;
      return state.activeId ? global.Api.getCourse(state.activeId) : null;
    }).then(function (detail) {
      state.detail = detail;
      render(el, ctx);
    }).catch(function (err) {
      UI.clear(el).appendChild(UI.errorBox(err, function () { load(el, ctx); }));
    });
  }

  /* 切换课程要重新取详情：场次与合规状态都在详情里，不能靠列表拼 */
  function selectCourse(el, ctx, id) {
    state.activeId = id;
    state.mode = 'detail';
    state.detail = null;
    render(el, ctx);
    global.Api.getCourse(id).then(function (d) {
      state.detail = d;
      if (state.activeId === id) render(el, ctx);
    }).catch(function (err) { UI.toast(err.message, 'danger'); });
  }

  function render(el, ctx) {
    UI.clear(el);
    var active = state.courses.filter(function (c) { return c.id === state.activeId; })[0];

    var left = UI.card({
      title: '课程',
      sub: state.courses.length + ' 门',
      actions: h('div', { class: 'btn-row' }, [
        h('button', {
          class: 'btn btn-ghost btn-sm', text: '批量入库',
          onclick: function () { state.mode = 'batchImport'; render(el, ctx); }
        }),
        h('button', {
          class: 'btn btn-primary btn-sm', text: '新建课程',
          onclick: function () { state.mode = 'newCourse'; render(el, ctx); }
        })
      ]),
      body: h('div', { class: 'course-list' }, state.courses.map(function (c) {
        return h('div', {
          class: 'course-item' + (c.id === state.activeId ? ' is-active' : ''),
          onclick: function () { selectCourse(el, ctx, c.id); }
        },
          h('div', { class: 'course-item-main' },
            h('strong', { text: c.title }),
            h('span', { class: 'course-meta', text: c.id + ' · ' + c.goals.length + ' 条目标 · ' + c.expected_students + ' 人' })),
          h('button', {
            class: 'btn btn-ghost btn-xs course-del', text: '删除', title: '删除该课程及其全部场次、媒资、观测与评价',
            onclick: function (e) { e.stopPropagation(); confirmDelete(el, ctx, c); }
          })
        );
      }))
    });

    var right;
    if (state.mode === 'newCourse') right = courseForm(el, ctx);
    else if (state.mode === 'batchImport') right = batchImportForm(el, ctx);
    else if (state.mode === 'newSession' && active) right = sessionForm(el, ctx, active);
    else if (active && state.detail && state.detail.id === active.id) right = courseDetail(el, ctx, state.detail);
    else if (active) right = UI.card({ body: UI.skeleton(4) });
    else right = UI.card({ body: UI.emptyState('还没有课程', '先建一门课程，再为它创建场次') });

    el.appendChild(h('div', { class: 'split' }, [left, right]));
  }

  /* 删除课程：二次确认后调 DELETE，成功后回列表。删除不可逆，提示里写清楚会带走什么。 */
  function confirmDelete(el, ctx, c) {
    var n = (c.sessions || []).length;
    UI.confirmDialog({
      title: '删除课程',
      danger: true,
      okText: '删除',
      text: '确定删除《' + c.title + '》？此操作不可逆。',
      detail: h('div', {},
        h('p', { text: '将一并删除：' + n + ' 个场次，以及每个场次下的媒资文件、预处理任务、模型调用记录、观测值与评价快照。' }),
        h('p', { class: 'ta-mute', text: '审计留痕会保留（记录「删除」这个动作本身）。' }))
    }).then(function (ok) {
      if (!ok) return;
      global.Api.deleteCourse(c.id).then(function (r) {
        UI.toast('已删除《' + c.title + '》及 ' + (r.deleted_sessions || n) + ' 个场次', 'ok');
        state.activeId = null;
        state.detail = null;
        state.mode = 'detail';
        load(el, ctx);
      }).catch(function (err) { UI.toast(err.message, 'danger'); });
    });
  }

  /* ---------------------------------------------------------- 课程详情 */

  function courseDetail(el, ctx, c) {
    var goalRows = c.goals.map(function (g, i) {
      return h('tr', {},
        h('td', { class: 'ta-c', text: i + 1 }),
        h('td', { text: g.text }),
        h('td', {}, tierBadge(g.tier))
      );
    });

    var goalsTable = h('table', { class: 'table table-compact' },
      h('thead', {}, h('tr', {},
        h('th', { class: 'ta-c', style: { width: '44px' }, text: '#' }),
        h('th', { text: '目标' }),
        h('th', { style: { width: '96px' }, text: '层次' }))),
      h('tbody', {}, goalRows));

    return UI.card({
      title: c.title,
      sub: c.id + ' · 预计 ' + c.expected_students + ' 人 · 建于 ' + UI.fmt.datetime(c.created_at),
      actions: h('div', { class: 'btn-row' }, [
        h('button', {
          class: 'btn btn-primary btn-sm', text: '创建场次',
          onclick: function () { state.mode = 'newSession'; render(el, ctx); }
        }),
        h('button', {
          class: 'btn btn-danger btn-sm', text: '删除课程',
          onclick: function () { confirmDelete(el, ctx, c); }
        })
      ]),
      children: [
        h('div', { class: 'card-body' }, goalsTable),
        h('div', { class: 'card-body' },
          UI.sectionHead('场次', '同一课程可按课型多次开课'),
          sessionsTable(c, ctx))
      ]
    });
  }

  function tierBadge(tier) {
    var map = { core: ['核心', 'blue'], support: ['支撑', 'ok'], extend: ['拓展', 'mute'] };
    var m = map[tier] || [tier, 'mute'];
    return UI.badge(m[0], m[1]);
  }

  function sessionsTable(c, ctx) {
    // 场次从总览接口取，保证与总览页一致
    var rows = c.sessions || [];
    if (!rows.length) {
      return UI.emptyState('尚无场次', '创建场次后才能接入该次课的媒资');
    }
    return UI.table({
      compact: true,
      columns: [
        { label: '场次', width: '150px', render: function (r) { return h('code', { class: 'code', text: r.id }); } },
        { label: '标题', key: 'title' },
        { label: '课型', width: '72px', render: function (r) {
          return ({ theory: '理论', seminar: '研讨', practical: '实践' })[r.scenario];
        } },
        { label: '日期', width: '100px', render: function (r) { return r.date; } },
        { label: '状态', width: '96px', render: function (r) { return UI.statusBadge(r.status); } }
      ],
      rows: rows,
      onRowClick: function (r) { ctx.setSession(r.id); ctx.go('media'); }
    });
  }

  /* ---------------------------------------------------------- 批量入库 */

  /* 两条路，落到同一个提交口：
       桌面版 —— 选一个根目录，后端按 <课程>/<场次>/文件 的约定扫出清单，填进下面的框，
                 人看一眼再提交（不替用户猜目标，缺 goals.txt 的课会红着列出来）
       浏览器 —— 只能手贴 JSON（浏览器拿不到真实路径，就地登记走不通）
     媒资走「就地登记」：path 指向盘上已有文件，不搬字节，大原片不做二次拷贝。 */
  function batchImportForm(el, ctx) {
    var textarea = h('textarea', {
      class: 'input code-area',
      rows: 15,
      placeholder: '{\n  "courses": [{\n    "title": "新任经理管理能力培训",\n    "expected_students": 32,\n    "goals": [{"text": "能说清管理者的三项核心职责", "tier": "core"}],\n    "sessions": [{\n      "title": "第一讲 角色认知", "date": "2026-11-05", "start": "09:00",\n      "scenario": "theory", "consent_confirmed": true,\n      "media": [{"path": "D:/原始数据/cam1.mp4", "type": "video", "slot": "cam1"}]\n    }]\n  }]\n}'
    });
    var resultBox = h('div', { class: 'form-error' });
    var scanBox = h('div', { class: 'scan-box' });
    var submitBtn = h('button', { class: 'btn btn-primary', text: '开始入库' });
    var consent = UI.input({ type: 'checkbox' });

    function submit() {
      UI.clear(resultBox);
      var doc;
      try {
        doc = JSON.parse(textarea.value || '{}');
      } catch (err) {
        resultBox.appendChild(UI.errorBox({ code: 'JSON_PARSE', message: '清单不是合法 JSON：' + err.message }));
        return;
      }
      if (!doc.courses || !doc.courses.length) {
        resultBox.appendChild(UI.errorBox({ code: 'VALIDATION_FAILED', message: '清单需包含 courses 数组' }));
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = '入库中…';
      global.Api.importBatch(doc).then(function (r) {
        submitBtn.disabled = false;
        submitBtn.textContent = '开始入库';
        resultBox.appendChild(importSummary(r));
        UI.toast(r.failed ? ('入库完成，' + r.failed + ' 项失败') : '入库完成',
                 r.failed ? 'warn' : 'ok');
        load(el, ctx);
      }).catch(function (err) {
        submitBtn.disabled = false;
        submitBtn.textContent = '开始入库';
        resultBox.appendChild(UI.errorBox(err));
      });
    }
    submitBtn.onclick = submit;

    /* ---- 桌面版：选目录 → 扫描 → 填进清单 ---- */
    var nativeBar = null;
    if (global.Desktop && global.Desktop.isDesktop()) {
      var pickBtn = h('button', { class: 'btn btn-primary btn-sm', text: '选择课程文件夹…' });

      pickBtn.onclick = function () {
        if (!consent.checked) {
          UI.toast('先勾选"已取得知情同意"再扫描——未确认的场次后端会直接拒收', 'warn');
          consent.focus();
          return;
        }
        global.Desktop.pickFolder('选择课程根目录（其下每层是课程，再往下是场次）')
          .then(function (root) {
            if (!root) return null;
            pickBtn.disabled = true;
            pickBtn.textContent = '扫描中…';
            return global.Desktop.scan(root, { consent: true }).then(function (r) {
              textarea.value = JSON.stringify(r.manifest, null, 2);
              renderScan(scanBox, r);
              var bad = (r.issues || []).filter(function (i) { return i.level === 'error'; }).length;
              UI.toast('扫描完成：' + r.stats.courses + ' 门课 / ' + r.stats.sessions
                       + ' 场次 / ' + r.stats.media + ' 个媒资' + (bad ? '，' + bad + ' 处需要处理' : ''),
                       bad ? 'warn' : 'ok');
            });
          })
          .catch(function (err) { UI.toast(err.message, 'danger'); })
          .then(function () {
            pickBtn.disabled = false;
            pickBtn.textContent = '选择课程文件夹…';
          });
      };

      nativeBar = h('div', { class: 'native-bar' },
        h('div', { class: 'native-bar-main' },
          pickBtn,
          h('span', { class: 'ta-mute', text: '按 <课程>/<场次>/文件 的目录约定自动生成清单；选完可先核对再提交' })),
        h('div', { class: 'native-bar-hint', text: '场次目录建议命名为「2026-11-05 09-00」，日期与开始时间会从目录名解析，缺省用今天 09:00。' }));
    }

    return UI.card({
      title: '批量入库',
      sub: '一次导入多门课程、场次与媒资；媒资按 path 就地登记，不复制字节',
      actions: h('button', {
        class: 'btn btn-ghost btn-sm', text: '取消',
        onclick: function () { state.mode = 'detail'; render(el, ctx); }
      }),
      children: [
        h('div', { class: 'card-body' }, [
          h('div', { class: 'note-strip' },
            h('strong', { text: '规则：' }),
            h('span', { text: '每门课至少 1 条核心目标；每场次 consent_confirmed 必须为 true；scenario 只能是 theory／seminar／practical。同名课程、同日期同开始时间的场次会自动复用，可安全重跑。' })),
          nativeBar,
          h('label', { class: 'consent' },
            consent,
            h('span', {}, [
              h('strong', { text: '已取得授课教师与学员的知情同意' }),
              h('em', { text: '整套清单统一声明；扫描与入库都以此为前置（接口返回 CONSENT_REQUIRED）' })
            ])),
          scanBox,
          UI.field('清单 JSON', textarea, '与 tools/import.py 的 manifest 结构一致；media.path 为盘上文件绝对路径'),
          resultBox,
          h('div', { class: 'form-actions' }, submitBtn)
        ])
      ]
    });
  }

  /* 扫描结果：统计 + 逐条问题（缺 goals.txt、类型不认识、机位冲突…）。
     问题不折叠、不汇总成一句话——操作者要能照着改目录。 */
  function renderScan(box, r) {
    UI.clear(box);
    var bad = (r.issues || []).filter(function (i) { return i.level === 'error'; });
    var warn = (r.issues || []).filter(function (i) { return i.level === 'warn'; });

    box.appendChild(h('div', { class: 'scan-head' },
      h('strong', { text: '扫描结果' }),
      UI.badge(r.stats.courses + ' 门课', 'blue'),
      UI.badge(r.stats.sessions + ' 场次', 'blue'),
      UI.badge(r.stats.media + ' 个媒资', 'blue'),
      UI.badge(UI.fmt.bytes(r.stats.bytes), 'mute')));

    box.appendChild(h('p', { class: 'scan-root', text: r.root }));

    if (!r.issues || !r.issues.length) {
      box.appendChild(h('p', { class: 'scan-ok', text: '没有发现问题，清单已填入下面的编辑框。' }));
      return;
    }

    box.appendChild(h('div', { class: 'scan-issues' }, r.issues.map(function (i) {
      return h('div', { class: 'issue-row is-' + i.level },
        UI.badge(i.level === 'error' ? '需处理' : '注意', i.level === 'error' ? 'danger' : 'warn'),
        h('span', { class: 'issue-where', text: i.where }),
        h('span', { class: 'issue-text', text: i.text }));
    })));

    if (bad.length) {
      box.appendChild(h('p', { class: 'scan-note' ,
        text: '标记"需处理"的课／场次仍会提交，但后端会逐项拒收并在结果里列出原因；改完目录重扫即可。' }));
    } else if (warn.length) {
      box.appendChild(h('p', { class: 'scan-note', text: '以上"注意"项不影响入库，只是提醒。' }));
    }
  }

  /* 把后端逐项回报渲染成一张小结卡：哪门成了、哪条媒资重复、哪里失败。 */
  function importSummary(r) {
    var rows = [];
    function walkCourse(c) {
      rows.push({ kind: c.reused ? '课程（复用）' : '课程', title: c.title || '(无标题)', ok: c.ok, note: c.error || (c.course_id || '') });
      (c.sessions || []).forEach(function (s) {
        rows.push({ kind: s.reused ? '  场次（复用）' : '  场次', title: s.title || '(无标题)', ok: s.ok, note: s.error || (s.session_id || '') });
        (s.assets || []).forEach(function (a) {
          rows.push({ kind: '    媒资', title: a.file || '(无路径)', ok: a.ok, note: a.duplicate ? '重复，未重复入库' : (a.error || '') });
        });
        (s.observations || []).forEach(function (o) {
          rows.push({ kind: '    观测 ' + (o.code || ''), title: '', ok: o.ok, note: o.error || (o.score !== undefined && o.score !== null ? '分项分 ' + o.score : '') });
        });
      });
    }
    (r.items || []).forEach(walkCourse);

    var head = h('div', { class: 'section-head' },
      h('div', {},
        h('h2', { class: 'section-title', text: '入库结果' }),
        h('p', { class: 'section-sub', text: '课程 ' + r.courses + ' · 场次 ' + r.sessions + ' · 媒资 ' + r.assets +
          ' · 观测 ' + r.observations + ' · 重复 ' + r.duplicate + ' · 失败 ' + r.failed })));

    var table = UI.table({
      compact: true,
      columns: [
        { label: '条目', width: '160px', render: function (row) { return row.kind; } },
        { label: '名称', render: function (row) { return row.title; } },
        { label: '结果', width: '200px', render: function (row) {
          return row.ok ? UI.badge('成功', 'ok') : UI.badge('失败', 'danger');
        } },
        { label: '说明', render: function (row) { return row.note || ''; } }
      ],
      rows: rows
    });

    return h('div', { class: 'card-body' }, head, table);
  }

  /* ---------------------------------------------------------- 新建课程 */

  function courseForm(el, ctx) {
    var goals = [{ text: '', tier: 'core' }];
    var titleInput = UI.input({ type: 'text', maxlength: 100, placeholder: '例如：新员工安全生产培训' });
    var studentsInput = UI.input({ type: 'number', value: 30, min: 1, max: 10000 });
    var goalBox = h('div', { class: 'goal-editor' });
    var errorBox = h('div', { class: 'form-error' });

    function paintGoals() {
      UI.clear(goalBox);
      goals.forEach(function (g, i) {
        goalBox.appendChild(h('div', { class: 'goal-row' },
          h('span', { class: 'goal-index', text: i + 1 }),
          UI.input({
            type: 'text', value: g.text, maxlength: 200, placeholder: '用可观测的行为描述学习结果',
            oninput: function (e) { g.text = e.target.value; }
          }),
          UI.select([
            { value: 'core', label: '核心' },
            { value: 'support', label: '支撑' },
            { value: 'extend', label: '拓展' }
          ], g.tier, { onchange: function (e) { g.tier = e.target.value; } }),
          h('button', {
            class: 'btn btn-ghost btn-sm', text: '删除', disabled: goals.length <= 1,
            onclick: function () { goals.splice(i, 1); paintGoals(); }
          })
        ));
      });
      goalBox.appendChild(h('button', {
        class: 'btn btn-ghost btn-sm', text: '+ 添加目标',
        onclick: function () {
          if (goals.length >= 30) return UI.toast('目标最多 30 条', 'warn');
          goals.push({ text: '', tier: 'support' }); paintGoals();
        }
      }));
    }
    paintGoals();

    function submit() {
      UI.clear(errorBox);
      var payload = {
        title: titleInput.value.trim(),
        expected_students: Number(studentsInput.value) || 0,
        goals: goals.filter(function (g) { return g.text.trim(); }).map(function (g) {
          return { text: g.text.trim(), tier: g.tier };
        })
      };
      global.Api.createCourse(payload).then(function (r) {
        UI.toast('课程已创建 ' + r.id, 'ok');
        state.activeId = r.id;
        state.mode = 'detail';
        load(el, ctx);
      }).catch(function (err) {
        errorBox.appendChild(UI.errorBox(err));
      });
    }

    return UI.card({
      title: '新建课程',
      sub: '课程标题与目标会作为 A1/A2/A3 的判定依据',
      actions: h('button', {
        class: 'btn btn-ghost btn-sm', text: '取消',
        onclick: function () { state.mode = 'detail'; render(el, ctx); }
      }),
      children: [
        h('div', { class: 'card-body' }, [
          UI.field('课程标题', titleInput, '1–100 字符'),
          UI.field('预计人数', studentsInput, '1–10000'),
          h('div', { class: 'field' },
            h('span', { class: 'field-label', text: '课程目标' }),
            h('span', { class: 'field-hint', text: '1–30 条。至少 1 条核心目标；核心目标参与 A2 加权覆盖的分母' }),
            goalBox),
          errorBox,
          h('div', { class: 'form-actions' },
            h('button', { class: 'btn btn-primary', text: '创建课程', onclick: submit }))
        ])
      ]
    });
  }

  /* ---------------------------------------------------------- 新建场次 */

  function sessionForm(el, ctx, c) {
    var titleInput = UI.input({ type: 'text', placeholder: '例如：第三讲 高处作业防护' });
    var scenario = UI.select([
      { value: 'theory', label: '理论课' },
      { value: 'seminar', label: '研讨课' },
      { value: 'practical', label: '实践课' }
    ], 'theory');
    var dateInput = UI.input({ type: 'date', value: new Date().toISOString().slice(0, 10) });
    var startInput = UI.input({ type: 'time', value: '09:00' });
    var teacherInput = UI.input({ type: 'text', placeholder: 'T-014' });
    var roomInput = UI.input({ type: 'text', placeholder: 'A-302' });
    var consent = UI.input({ type: 'checkbox' });
    var submitBtn = h('button', { class: 'btn btn-primary', text: '创建场次', disabled: true });
    var errorBox = h('div', { class: 'form-error' });

    consent.addEventListener('change', function () {
      submitBtn.disabled = !consent.checked;
      submitBtn.title = consent.checked ? '' : '未确认知情同意不得入库';
    });

    function submit() {
      UI.clear(errorBox);
      global.Api.createSession({
        course_id: c.id,
        title: titleInput.value.trim() || c.title,
        scenario: scenario.value,
        consent_confirmed: consent.checked,
        /* 日期与开始时间必须一起送：后端缺省是"今天 00:00"，
           收了表单却不送，报告与总览的时间列会和实际排课不一致 */
        date: dateInput.value || undefined,
        start: startInput.value || undefined,
        teacher: teacherInput.value.trim(),
        room: roomInput.value.trim(),
        expected_students: c.expected_students
      }).then(function (r) {
        UI.toast('场次已创建 ' + r.id, 'ok');
        state.mode = 'detail';
        ctx.setSession(r.id);
        render(el, ctx);
      }).catch(function (err) { errorBox.appendChild(UI.errorBox(err)); });
    }

    return UI.card({
      title: '为《' + c.title + '》创建场次',
      sub: '课型影响 B1 语速区间与 VB1 警戒线，填错会导致后续判定偏移',
      actions: h('button', {
        class: 'btn btn-ghost btn-sm', text: '取消',
        onclick: function () { state.mode = 'detail'; render(el, ctx); }
      }),
      children: [
        h('div', { class: 'card-body' }, [
          UI.field('场次标题', titleInput),
          UI.field('课型', scenario, 'theory / seminar / practical'),
          h('div', { class: 'form-row' }, [
            UI.field('授课日期', dateInput),
            UI.field('开始时间', startInput),
            UI.field('教师编号', teacherInput),
            UI.field('教室', roomInput)
          ]),
          h('label', { class: 'consent' },
            consent,
            h('span', {}, [
              h('strong', { text: '已取得授课教师与学员的知情同意' }),
              h('em', { text: '人脸与声纹属敏感个人信息，未确认不得入库（接口返回 CONSENT_REQUIRED）' })
            ])),
          errorBox,
          h('div', { class: 'form-actions' }, submitBtn)
        ])
      ]
    });
  }

  Views.courses = function (el, ctx) {
    state.mode = 'detail';
    load(el, ctx);
  };
})(window);
