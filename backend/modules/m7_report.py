"""modules/m7_report.py — M7 报告、导出与审计

报告的六节与界面一致：会话信息／一、证据覆盖／二、音频分项／三、视频分项／四、一致性／五、合规／六、口径声明。

导出能力分层，写清楚哪层能做什么：
  json  完整结构，永远可用（证据不足时唯一可导的格式）
  docx  本地生成（core/docx.py，纯标准库），六节正文 + 两张分项表
  pdf   留空 501——PDF 要嵌入中文字体才能正确显示，端侧不引字体文件；
        需要 PDF 时用 docx 打开后另存，或浏览器打印当前报告页
  html  可选，给"直接在浏览器里打印成 PDF"用

证据不足（覆盖率 < 0.60）时不生成 docx：一份没有分数的报告一旦流出，
一定会被当成"评分很低"来读，而实际上我们什么都没测到。这条约束写在代码里。
"""
import os

import config
import db
import errors
import util

from core import docx as docx_mod

from . import _common
from . import m6_fusion

SCENARIO_TEXT = {'theory': '理论课', 'seminar': '研讨课', 'practical': '实践课'}


def build_report(sid):
    session = _common.require_session(sid)
    ev = m6_fusion.compute(sid, persist=False)
    items = _common.observations(sid)
    gates, _res = _common.gates_of(sid)
    if not gates:
        from core import gates as gates_mod
        _overall, gates = gates_mod.compute(session, _common.media_rows(sid), {}, {})

    gate_overall = 'pass'
    if any(g['status'] == 'reject' for g in gates):
        gate_overall = 'reject'
    elif any(g['status'] == 'warn' for g in gates):
        gate_overall = 'warn'

    c1 = [o for o in items if o['code'] == 'C1'][0]
    compliance = {
        'items': [] if c1['raw_value'] in (None, 0) else
                 [{'code': 'C1', 'value': c1['raw_value'], 'note': c1['note']}],
        'note': ('未检出候选事件；C1 不进加权，独立成节' if c1['raw_value'] in (None, 0)
                 else '检出候选事件，需人工复核后定性；C1 不进加权'),
    }

    note = {
        'aligned': '两模态判断方向一致',
        'divergent': '两模态判断方向相反，标为证据不一致，不取平均',
        'insufficient': '覆盖率不足，暂不做一致性判定',
    }[ev['consistency']['status']]

    return {
        'session': {
            'id': session['id'], 'title': session['title'],
            'course': session.get('course_title'),
            'scenario': session['scenario'], 'date': session['date'], 'start': session['start'],
            'duration_min': session['duration_min'], 'students': session['students'],
            'teacher': session['teacher'], 'room': session['room'],
        },
        'coverage': {
            'gate': gate_overall,
            'audio': ev['audio']['coverage'],
            'video': ev['video']['coverage'],
            'missing': ev['missing'],
            'gate_items': gates,
        },
        'audio_items': [o for o in items if o['tier'] == 'audio' and o['code'] != 'C1'],
        'video_items': [o for o in items if o['tier'] == 'video' and o['code'] != 'VC3'],
        'scores': {'audio': ev['audio']['score'], 'video': ev['video']['score']},
        'consistency': {'status': ev['consistency']['status'],
                        'delta': ev['consistency']['delta'], 'note': note},
        'compliance': compliance,
        'short_board': ev['short_board'],
        'meta': {
            'config_version': ev['config_version'],
            'generated_at': util.iso(),
            'composite': None,
            'disclaimer': ('分项分只表示该项在其量尺上的取值，不表示学员达成度；'
                           '本系统不出具教学质量总分，也不构成人事考核依据。'),
        },
    }


def get_report(sid, fmt='json'):
    rep = build_report(sid)
    if fmt == 'json' or not fmt:
        return rep

    # 能力性留空先判：PDF 不管数据够不够都不可能生成，报 501 比报 409 更准确
    if fmt == 'pdf':
        raise errors.ApiError(
            'NOT_IMPLEMENTED',
            'PDF 导出留接口：需嵌入中文字体（等宽+宋体子集）后才能正确显示，端侧不引入字体文件。'
            '请改用 format=docx 导出后在 WPS 另存为 PDF，或浏览器打印报告页。')
    if fmt not in ('docx', 'html'):
        errors.fail('VALIDATION_FAILED', 'format 需为 json／docx／pdf／html', 'format')

    # 证据不足时不生成正式报告：一份没有分数的报告流出后一定会被当成"评分很低"来读
    if rep['consistency']['status'] == 'insufficient':
        raise errors.ApiError('STATE_CONFLICT',
                              '证据不足（覆盖率低于 0.60），不生成正式报告；可导出 format=json 用于排查',
                              'format')

    if fmt == 'docx':
        return _export_docx(rep)
    return _render_html(rep)


def _export_docx(rep):
    s = rep['session']
    blocks = [
        ('title', '课堂教学质量评估报告（过程分）'),
        ('p', '课程：%s　场次：%s' % (s['course'] or '—', s['id'])),
        ('p', '课题：%s　课型：%s' % (s['title'], SCENARIO_TEXT.get(s['scenario'], s['scenario']))),
        ('p', '时间：%s %s · %d 分钟　地点：%s　教师：%s　学员：%d 人'
              % (s['date'], s['start'], s['duration_min'], s['room'] or '—',
                 s['teacher'] or '—', s['students'])),
        ('small', '生成时间 %s　配置版本 %s　本报告不出具总分' %
                  (rep['meta']['generated_at'], rep['meta']['config_version'])),

        ('h1', '一、证据覆盖'),
        ('p', '门禁结论：%s　音频覆盖率：%.0f%%　视频覆盖率：%.0f%%'
              % ({'pass': '全部通过', 'warn': '存在注意项', 'reject': '存在阻断项'}[rep['coverage']['gate']],
                 rep['coverage']['audio'] * 100, rep['coverage']['video'] * 100)),
    ]
    if rep['coverage']['missing']:
        blocks.append(('small', '未输出分项：' + '；'.join(
            '%s（%s）' % (m['name'], m['reason']) for m in rep['coverage']['missing'])))
    blocks.append(('table', (
        ['门禁', '结论', '观测', '说明'],
        [[g['name'], {'pass': '通过', 'warn': '注意', 'reject': '阻断'}[g['status']], g['value'], g['detail']]
         for g in rep['coverage']['gate_items']],
        [1600, 800, 1800, 3600])))

    blocks.append(('h1', '二、音频分项（9 项计分 ＋ C1 门禁）'))
    blocks.append(('table', (
        ['代码', '指标', '原始量', '分项分', '置信度', '说明'],
        [[o['code'], o['name'],
          '—' if o['raw_value'] is None else ('%.4g' % o['raw_value']),
          '—' if o['score'] is None else ('%.1f' % o['score']),
          '—' if o['confidence'] is None else ('%.2f' % o['confidence']),
          (o['note'] or o['empty_reason'] or '')[:40]]
         for o in rep['audio_items']],
        [700, 1800, 900, 800, 800, 4000])))

    blocks.append(('h1', '三、视频分项（10 项计分 ＋ VC3 列示）'))
    blocks.append(('table', (
        ['代码', '指标', '原始量', '分项分', '置信度', '说明'],
        [[o['code'], o['name'],
          '—' if o['raw_value'] is None else ('%.4g' % o['raw_value']),
          '—' if o['score'] is None else ('%.1f' % o['score']),
          '—' if o['confidence'] is None else ('%.2f' % o['confidence']),
          (o['note'] or o['empty_reason'] or '')[:40]]
         for o in rep['video_items']],
        [700, 1800, 900, 800, 800, 4000])))

    blocks.append(('h1', '四、合成与一致性'))
    blocks.append(('p', '音频分 Sₐ = %.1f（覆盖率 %.2f）　视频分 Sᵥ = %.1f（覆盖率 %.2f）'
                  % (rep['scores']['audio'], rep['coverage']['audio'],
                     rep['scores']['video'], rep['coverage']['video'])))
    blocks.append(('p', '一致性：%s。分差 %.1f 分。%s'
                  % ({'aligned': '一致', 'divergent': '证据不一致', 'insufficient': '证据不足'}
                     [rep['consistency']['status']],
                     rep['consistency']['delta'], rep['consistency']['note'])))
    blocks.append(('small', '两份分数并列呈现，不提供合成总分：音频与视频测的不是同一构念，'
                            '加权合成需要通约系数 α，两份来源材料均未给出。'))
    for sb in rep['short_board']:
        blocks.append(('p', '· ' + sb['text']))

    blocks.append(('h1', '五、合规与危险言论（C1）'))
    blocks.append(('p', rep['compliance']['note']))

    blocks.append(('h1', '六、口径声明'))
    blocks.append(('p', '1. 分项分满分 100，表示该项在其量尺上的取值，不表示学员达成程度。'))
    blocks.append(('p', '2. 缺测不补零、不重分权：某项没数据时记空值并写原因，覆盖率单独报。'))
    blocks.append(('p', '3. 门禁先于计分：门禁阻断的分项不予输出，界面上显示"未输出"而不是 0。'))
    blocks.append(('p', '4. ' + rep['meta']['disclaimer']))

    os.makedirs(config.EXPORT_DIR, exist_ok=True)
    path = os.path.join(config.EXPORT_DIR, 'report-%s.docx' % s['id'])
    docx_mod.build(path, blocks, title='课堂教学质量评估报告 %s' % s['id'])
    db.audit('report.export', s['id'], 'admin', {'format': 'docx', 'path': os.path.basename(path)})
    return {'path': path, 'filename': '课堂教学质量评估报告-%s.docx' % s['id'],
            'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


def _render_html(rep):
    """极简可打印 HTML：给"浏览器直接打印成 PDF"用"""
    s = rep['session']

    def esc(t):
        return (str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

    rows = ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                   % (esc(o['code']), esc(o['name']),
                      '—' if o['raw_value'] is None else '%.4g' % o['raw_value'],
                      '—' if o['score'] is None else '%.1f' % o['score'])
                   for o in rep['audio_items'] + rep['video_items'])
    html = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>评估报告 %s</title><style>
body{font-family:"宋体",serif;max-width:800px;margin:24px auto;line-height:1.8;font-size:13px;color:#1A2230}
h1{font-size:16px;border-bottom:1px solid #ccc;padding-bottom:4px;margin-top:22px}
table{border-collapse:collapse;width:100%%;font-size:12px}
td,th{border:1px solid #ddd;padding:4px 6px}
.score{font-size:15px}
@media print{body{margin:0}}
</style></head><body>
<h1 style="text-align:center;border:0">课堂教学质量评估报告（过程分）</h1>
<p>课程：%s　场次：%s　课题：%s</p>
<p>时间：%s %s · %d 分钟　地点：%s　教师：%s</p>
<p class="score">音频分 Sₐ <b>%.1f</b>（覆盖率 %.2f）　视频分 Sᵥ <b>%.1f</b>（覆盖率 %.2f）　<b>不出总分</b></p>
<p>一致性：%s　%s</p>
<table><tr><th>代码</th><th>指标</th><th>原始量</th><th>分项分</th></tr>%s</table>
<p style="color:#666">%s</p>
</body></html>""" % (esc(s['id']), esc(s['course']), esc(s['id']), esc(s['title']),
                    esc(s['date']), esc(s['start']), s['duration_min'], esc(s['room']),
                    esc(s['teacher']), rep['scores']['audio'], rep['coverage']['audio'],
                    rep['scores']['video'], rep['coverage']['video'],
                    esc(rep['consistency']['status']), esc(rep['consistency']['note']),
                    rows, esc(rep['meta']['disclaimer']))
    return {'html': html, 'filename': 'report-%s.html' % s['id']}


def list_audit(page=1, size=50):
    rows = db.q('SELECT * FROM audit ORDER BY at DESC LIMIT 2000')
    items = [{'id': r['id'], 'action': r['action'], 'object_id': r['object_id'],
              'actor': r['actor'], 'at': r['at']} for r in rows]
    return util.paginate(items, page, size)
