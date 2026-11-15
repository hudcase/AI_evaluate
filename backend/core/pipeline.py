"""core/pipeline.py — 预处理流水线（六阶段）

  probe → transcode → extract → parse_slides → mask → gate

每阶段都返回明确状态，且状态只有四种说法：
  done      真做了，产物在 derived/
  skipped   当前环境做不了（没 ffmpeg／没检测模型），写明缺什么 —— 不假装做过
  degraded  做了一半，写明降级到哪一步
  failed    做失败了，错误进 task.error

设计原则与门禁一致：**能算的真算，算不了的显式留空**。因此没有 ffmpeg 时，
转码与抽帧会标 skipped，门禁里"画面可用性"就自然变成 warn，而不是凭空 pass。
"""
import json
import os
import shutil
import subprocess
import zipfile

import config

from . import gates as gates_mod

STAGE_ORDER = [
    ('probe', '校验登记'),
    ('transcode', '转码派生'),
    ('extract', '抽帧 ROI'),
    ('parse_slides', '课件解析'),
    ('mask', '脱敏'),
    ('gate', '门禁判定'),
]


def session_dir(session_id):
    return os.path.join(config.MEDIA_DIR, session_id)


def derived_dir(session_id):
    d = os.path.join(session_dir(session_id), 'derived')
    os.makedirs(d, exist_ok=True)
    return d


def _run(cmd, timeout=900):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          timeout=timeout, check=False)


def _dir_bytes(path):
    total = 0
    count = 0
    if not os.path.isdir(path):
        return 0, 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
                count += 1
            except OSError:
                pass
    return total, count


# ---------------------------------------------------------------- 各阶段

def stage_probe(ctx):
    media = ctx['media']
    if not media:
        return 'failed', '未登记任何媒资'
    missing = [m['name'] for m in media if m.get('path') and not os.path.exists(m['path'])]
    nofile = [m['name'] for m in media if not m.get('path')]
    if missing:
        return 'failed', '文件丢失：%s' % '、'.join(missing[:3])
    if nofile:
        return 'degraded', '仅登记未落盘：%s（规格以登记信息为准）' % '、'.join(nofile[:3])
    return 'done', '%d 个资产探针通过' % len(media)


def stage_transcode(ctx):
    videos = [m for m in ctx['media'] if m['type'] == 'video' and m.get('path')]
    if not videos:
        return 'skipped', '无视频资产，跳过转码'
    if not config.FFMPEG:
        return 'skipped', '本机未安装 ffmpeg：720p 代理未生成，播放与抽帧将直读原片'
    out_dir = derived_dir(ctx['session_id'])
    made = []
    for i, m in enumerate(videos, 1):
        dst = os.path.join(out_dir, 'proxy_%d.mp4' % i)
        if os.path.exists(dst):
            made.append(dst)
            continue
        try:
            r = _run([config.FFMPEG, '-y', '-i', m['path'], '-vf', 'scale=-2:720',
                      '-c:v', 'libx264', '-crf', '28', '-preset', 'veryfast', '-an', dst])
            if r.returncode == 0 and os.path.exists(dst):
                made.append(dst)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return 'failed', '转码失败：%s' % exc
    if not made:
        return 'failed', '转码未产出任何代理文件'
    ctx['proxy'] = made
    return 'done', '生成 %d 个 720p 代理' % len(made)


def stage_extract(ctx):
    videos = [m for m in ctx['media'] if m['type'] == 'video' and m.get('path')]
    audios = [m for m in ctx['media'] if m['type'] == 'audio' and m.get('path')]
    if not videos and not audios:
        return 'skipped', '无可抽取的音视频'
    if not config.FFMPEG:
        return 'skipped', '本机未安装 ffmpeg：抽帧与 16k 音频未生成'
    out_dir = derived_dir(ctx['session_id'])
    frames_dir = os.path.join(out_dir, 'frames')
    os.makedirs(frames_dir, exist_ok=True)
    src = (ctx.get('proxy') or [videos[0]['path']])[0]
    frames = 0
    try:
        r = _run([config.FFMPEG, '-y', '-i', src, '-vf', 'fps=1/10,scale=640:-2',
                  '-frames:v', '600', os.path.join(frames_dir, 'f_%04d.jpg')])
        if r.returncode == 0:
            frames = len([f for f in os.listdir(frames_dir) if f.endswith('.jpg')])
    except (subprocess.TimeoutExpired, OSError):
        pass
    audio_out = None
    if audios:
        audio_out = os.path.join(out_dir, 'audio_16k.wav')
        if not os.path.exists(audio_out):
            try:
                _run([config.FFMPEG, '-y', '-i', audios[0]['path'], '-ac', '1',
                      '-ar', '16000', '-c:a', 'pcm_s16le', audio_out])
            except (subprocess.TimeoutExpired, OSError):
                audio_out = None
    if not frames and not audio_out:
        return 'failed', '抽帧与降采样均失败'
    ctx['frames'] = frames
    ctx['audio16k'] = audio_out
    return 'done', '抽帧 %d 张，16k 音频 %s' % (frames, '已生成' if audio_out else '未生成')


def stage_parse_slides(ctx):
    decks = [m for m in ctx['media'] if m['type'] == 'slides']
    if not decks:
        return 'skipped', '未上传课件，A2／A3 将缺少第二路证据'
    deck = decks[0]
    probe = ctx['probe_of'].get(deck['id'], {})
    if not deck.get('path') or not os.path.exists(deck['path']):
        return 'degraded', '课件仅登记未落盘，无法解析正文（页数 %s 来自登记信息）' % probe.get('pages', '?')
    ext = os.path.splitext(deck['path'])[1].lower()
    if ext != '.pptx':
        return 'skipped', 'PDF 课件留接口：需版面分析（OCR）后才能取正文，当前仅记页数'
    pages = []
    try:
        with zipfile.ZipFile(deck['path']) as z:
            names = sorted([n for n in z.namelist()
                            if n.startswith('ppt/slides/slide') and n.endswith('.xml')])
            for idx, n in enumerate(names, 1):
                xml = z.read(n).decode('utf-8', 'replace')
                pages.append({'page': idx, 'chars': xml.count('<a:t>'),
                              'has_image': '<p:pic' in xml,
                              'text': _strip_pptx_text(xml)})
    except (zipfile.BadZipFile, OSError) as exc:
        return 'failed', '课件解析失败：%s' % exc
    out = os.path.join(derived_dir(ctx['session_id']), 'slides.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({'pages': pages}, f, ensure_ascii=False)
    ctx['slides'] = pages
    ctx['slides_path'] = out
    empty = len([p for p in pages if p['chars'] == 0])
    return 'done', '解析 %d 页，其中 %d 页无文本（需 OCR）' % (len(pages), empty)


def _strip_pptx_text(xml):
    """轻量取文本：只取 <a:t> 节点内容，不建完整 DOM，够做覆盖判定"""
    out = []
    pos = 0
    while True:
        s = xml.find('<a:t>', pos)
        if s < 0:
            break
        e = xml.find('</a:t>', s)
        if e < 0:
            break
        out.append(xml[s + 5:e])
        pos = e + 6
    return ''.join(out)[:4000]


def stage_mask(ctx):
    """ROI 打码需要人脸／人体检测模型。留空，但把"该打什么"列清楚，
    避免让人误以为"已经脱敏过"。"""
    frames = ctx.get('frames') or 0
    if not frames:
        return 'skipped', '无抽帧，无需脱敏'
    return 'skipped', ('ROI 打码留接口：需人脸／人体检测模型（留空不影响计分，'
                       '但原片不得离开端侧）')


def stage_gate(ctx):
    session = ctx['session']
    derived = {'frames': ctx.get('frames') or 0,
               'slides_pages': len(ctx.get('slides') or [])}
    metrics = ctx.get('model_metrics') or {}
    overall, gl = gates_mod.compute(session, ctx['media'], metrics, derived)
    ctx['gates'] = gl
    ctx['gate_overall'] = overall
    passed = len([g for g in gl if g['status'] == 'pass'])
    return 'done', '%d/9 项通过，总体 %s' % (passed, overall)


STAGE_FN = {
    'probe': stage_probe,
    'transcode': stage_transcode,
    'extract': stage_extract,
    'parse_slides': stage_parse_slides,
    'mask': stage_mask,
    'gate': stage_gate,
}


# ---------------------------------------------------------------- 编排

def run(session_id, session, media, stages=None, on_progress=None, model_metrics=None):
    """同步执行；tasks.py 在后台线程里调它。返回写入 ai_tasks.result_json 的 dict。"""
    wanted = stages or [k for k, _ in STAGE_ORDER]
    ctx = {
        'session_id': session_id,
        'session': session,
        'media': media,
        'probe_of': {m['id']: util_loads(m.get('probe_json')) for m in media},
        'model_metrics': model_metrics or {},
    }
    results = []
    for i, (key, label) in enumerate(STAGE_ORDER):
        if key not in wanted:
            results.append({'key': key, 'label': label, 'status': 'skipped', 'detail': '未在本次请求中'})
            continue
        if on_progress:
            on_progress(i / float(len(STAGE_ORDER)), key)
        try:
            status, detail = STAGE_FN[key](ctx)
        except Exception as exc:                       # 单个阶段异常不吞掉整条流水线
            status, detail = 'failed', '%s: %s' % (type(exc).__name__, exc)
        results.append({'key': key, 'label': label, 'status': status, 'detail': detail})

    assets = collect_assets(session_id, ctx)
    return {
        'stages': results,
        'assets': assets,
        'gates': ctx.get('gates') or [],
        'gate_overall': ctx.get('gate_overall'),
        'model_metrics': ctx.get('model_metrics') or {},
        'slides_pages': len(ctx.get('slides') or []),
        'frames': ctx.get('frames') or 0,
        'finished_at': None,
    }


def collect_assets(session_id, ctx=None):
    """派生资产清单：能数出来的数，数不出来的不写数字。"""
    d = os.path.join(session_dir(session_id), 'derived')
    items = []

    proxies = []
    if os.path.isdir(d):
        proxies = [f for f in os.listdir(d) if f.startswith('proxy_') and f.endswith('.mp4')]
    if proxies:
        pb = sum(os.path.getsize(os.path.join(d, f)) for f in proxies)
        items.append({'kind': 'proxy', 'label': '720p 代理', 'count': len(proxies),
                      'bytes': pb, 'retention_days': 30})

    frames_dir = os.path.join(d, 'frames')
    if os.path.isdir(frames_dir):
        files = [f for f in os.listdir(frames_dir) if f.endswith('.jpg')]
        if files:
            fb = sum(os.path.getsize(os.path.join(frames_dir, f)) for f in files)
            items.append({'kind': 'frames', 'label': '抽帧（1 帧/10 秒）', 'count': len(files),
                          'bytes': fb, 'retention_days': 30})

    audio16k = os.path.join(d, 'audio_16k.wav')
    if os.path.exists(audio16k):
        items.append({'kind': 'audio16k', 'label': '16k 单声道（送 ASR）', 'count': 1,
                      'bytes': os.path.getsize(audio16k), 'retention_days': 1})

    slides = os.path.join(d, 'slides.json')
    if os.path.exists(slides):
        items.append({'kind': 'slides', 'label': '课件解析 JSON', 'count': 1,
                      'bytes': os.path.getsize(slides), 'retention_days': None})

    return {'items': items, 'total_bytes': sum(i['bytes'] for i in items)}


def util_loads(text):
    try:
        return json.loads(text or '{}')
    except ValueError:
        return {}
