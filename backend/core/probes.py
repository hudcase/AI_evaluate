"""core/probes.py — 轻量媒资探针（不依赖 ffprobe）

为什么要自己写：端侧主机常常没有 ffmpeg，而"规格校验"是 M2 的硬约束，必须有确定结论。
这里只读容器头，够用的部分真读，读不出的字段如实返回 None——

  MP4/MOV  按 box 结构走：ftyp 判品牌、moov/mvhd 取时长、trak/tkhd 取宽高、stsd 判编码、stsz 估帧率
  WAV      按 RIFF 块走：fmt 取采样率／位深／声道，data 抽样算峰值与削波比例
  PPTX     解压后数 slideN.xml，按是否含 <p:pic> 且无 <a:t> 判"纯图页"
  PDF      数 /Type /Page

真正的转码与抽帧不在这里，见 core/pipeline.py——那里有 ffmpeg 才做，没有就显式跳过。
"""
import os
import struct
import zipfile

VIDEO_EXT = ('.mp4', '.mov', '.m4v')
AUDIO_EXT = ('.wav', '.flac', '.m4a', '.mp3', '.aac', '.ogg')
SLIDE_EXT = ('.pptx', '.pdf')


# ---------------------------------------------------------------- MP4／MOV

def _boxes(buf, start=0, end=None):
    """遍历同一层级的 box，返回 (type, payload_start, payload_end)"""
    end = len(buf) if end is None else end
    pos = start
    while pos + 8 <= end:
        size = struct.unpack('>I', buf[pos:pos + 4])[0]
        btype = buf[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                break
            size = struct.unpack('>Q', buf[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            break
        yield btype, pos + header, pos + size
        pos += size


def _find(buf, path, start=0, end=None):
    """按 box 路径下钻，例如 [b'moov', b'mvhd']"""
    head, rest = path[0], path[1:]
    for btype, ps, pe in _boxes(buf, start, end):
        if btype != head:
            continue
        if not rest:
            return ps, pe
        found = _find(buf, rest, ps, pe)
        if found:
            return found
    return None


def _probe_mp4(path, size):
    info = {'container': 'mp4', 'width': None, 'height': None, 'fps': None,
            'codec': None, 'duration_s': None, 'brand': None}
    with open(path, 'rb') as f:
        head = f.read(2 * 1024 * 1024)      # moov 在 faststart 里，读前 2 MB 足够
        ft = _find(head, [b'ftyp'])
        if ft:
            info['brand'] = head[ft[0]:ft[0] + 4].decode('ascii', 'replace')

        mv = _find(head, [b'moov', b'mvhd'])
        tk = _find(head, [b'moov', b'trak', b'tkhd'])
        sz = _find(head, [b'moov', b'trak', b'mdia', b'minf', b'stbl', b'stsz'])

        if not mv and size > len(head):
            # 相机与手机默认把 moov 写在文件尾部（非 faststart），只读文件头会什么都读不到。
            # 这里再读尾部 8 MB 找 moov——4K 一节课的时长与分辨率就靠这一步。
            try:
                f.seek(max(0, size - 8 * 1024 * 1024))
                tail = f.read()
            except OSError:
                tail = b''
            idx = tail.find(b'moov')
            if idx >= 4:
                sub = tail[idx - 4:]        # 从 moov 的 size 字段开始，保证 box 对齐
                mv = _find(sub, [b'moov', b'mvhd'])
                tk = _find(sub, [b'moov', b'trak', b'tkhd'])
                sz = _find(sub, [b'moov', b'trak', b'mdia', b'minf', b'stbl', b'stsz'])
                if sub.find(b'avc1') >= 0:
                    info['codec'] = 'h264'
                elif sub.find(b'hvc1') >= 0 or sub.find(b'hev1') >= 0:
                    info['codec'] = 'hevc'
                head = sub + head       # 让后面的 codec 嗅探也能看到尾部

    if mv:
        ps, pe = mv
        version = head[ps]
        try:
            if version == 1:
                timescale = struct.unpack('>I', head[ps + 20:ps + 24])[0]
                duration = struct.unpack('>Q', head[ps + 24:ps + 32])[0]
            else:
                timescale = struct.unpack('>I', head[ps + 12:ps + 16])[0]
                duration = struct.unpack('>I', head[ps + 16:ps + 20])[0]
            if timescale:
                info['duration_s'] = round(duration / float(timescale), 2)
        except struct.error:
            pass
    if tk:
        ps, pe = tk
        try:
            w, h = struct.unpack('>II', head[pe - 8:pe])
            info['width'], info['height'] = w >> 16, h >> 16
        except struct.error:
            pass
    for fourcc, name in ((b'hvc1', 'hevc'), (b'hev1', 'hevc'), (b'avc1', 'h264'),
                         (b'mp4a', 'aac'), (b'vp09', 'vp9')):
        if head.find(fourcc) >= 0:
            if name in ('hevc', 'h264', 'vp9'):
                info['codec'] = name
            break
    if sz and info['duration_s']:
        ps, pe = sz
        try:
            count = struct.unpack('>I', head[ps + 8:ps + 12])[0]
            if count:
                info['fps'] = round(count / info['duration_s'], 2)
                info['frames'] = count
        except struct.error:
            pass
    if info['duration_s']:
        info['bitrate_mbps'] = round(size * 8 / info['duration_s'] / 1e6, 2)
    return info


def _probe_mp4_audio(path, size):
    """M4A／AAC（MP4 容器的纯音频轨）探针。

    m4a 与 mp4 同容器（ftyp=mp42 等），只是里面只有音频 trak。采样率有个坑：
    stsd/mp4a 的采样率字段按规范应为 0（留给 esds 里的 DecoderSpecificInfo），
    真实采样率要从 esds 里解——5 位采样率索引查表（96000/88200/64000/48000/…/7350）。
    声道同理在 esds 的 channelConfiguration。
    """
    info = {'container': 'm4a', 'codec': 'aac', 'sample_rate': None, 'channels': None,
            'duration_s': None, 'brand': None}

    # 采样率索引表（MPEG-4 Audio Object Type 0x02 的 samplingFrequencyIndex）
    RATES = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
             16000, 12000, 11025, 8000, 7350)

    def _esds_params(sub):
        """在 mp4a 载荷里找 esds 的 DecoderSpecificInfo，解采样率与声道"""
        # DecoderSpecificInfo 第一个字节高 5 位 = audioObjectType，接下来 4 位 = 采样率索引
        # 常见布局：... 0x05 (AudioSpecificConfig) + 长度 + 2 字节 config
        i = sub.find(b'esds')
        if i < 0:
            return None, None
        # esds 全载荷
        end = len(sub)
        # 找 0x05 标签（AudioSpecificConfig），后接 descriptor 长度，再后是 config 字节
        j = sub.find(b'\x05', i + 4)
        if j < 0:
            return None, None
        # 取 j 后 2 字节：第一字节高5位=AOT(常 0x02)，第二字节高4位=采样率索引
        cfg = sub[j:j + 6]
        # cfg 结构：0x05 len? config...  保守地在附近 8 字节里找可解析的索引
        for off in range(len(cfg) - 1):
            b0 = cfg[off]
            if b0 & 0xF8 == 0x10:        # AOT 高5位 = 2 (AAC LC) → 0x02<<3 = 0x10
                idx = cfg[off + 1] >> 4
                if 0 <= idx < len(RATES):
                    ch = cfg[off + 1] & 0x0F
                    return RATES[idx], ch
        return None, None

    with open(path, 'rb') as f:
        head = f.read(2 * 1024 * 1024)
        ft = _find(head, [b'ftyp'])
        if ft:
            info['brand'] = head[ft[0]:ft[0] + 4].decode('ascii', 'replace')
        mv = _find(head, [b'moov', b'mvhd'])
        stsd = _find(head, [b'moov', b'trak', b'mdia', b'minf', b'stbl', b'stsd'])
        if (not mv or not stsd) and size > len(head):
            # moov 在尾部：回读 8 MB 再找
            try:
                f.seek(max(0, size - 8 * 1024 * 1024))
                tail = f.read()
            except OSError:
                tail = b''
            idx = tail.find(b'moov')
            if idx >= 4:
                sub = tail[idx - 4:]
                mv = mv or _find(sub, [b'moov', b'mvhd'])
                stsd = stsd or _find(sub, [b'moov', b'trak', b'mdia', b'minf', b'stbl', b'stsd'])
                head = sub + head

    if mv:
        ps, _pe = mv
        try:
            version = head[ps]
            if version == 1:
                timescale = struct.unpack('>I', head[ps + 20:ps + 24])[0]
                duration = struct.unpack('>Q', head[ps + 24:ps + 32])[0]
            else:
                timescale = struct.unpack('>I', head[ps + 12:ps + 16])[0]
                duration = struct.unpack('>I', head[ps + 16:ps + 20])[0]
            if timescale:
                info['duration_s'] = round(duration / float(timescale), 2)
        except struct.error:
            pass

    if stsd:
        # stsd payload：version/flags(4B) + entry_count(4B)，之后是 sample entry。
        # 音频轨的 sample entry 是 mp4a box：offset 8 起是 entry size(4B)，offset 12 起是 'mp4a' 四字节码。
        # mp4a box 本体从 offset 8 开始（含 size 字段），采样率/声道相对该 box：
        #   +24 2B channelcount，+32 4B samplerate(16.16 定点，高 16 位是整数)
        ps, pe = stsd
        sbody = head[ps:pe]
        raw_ch = raw_rate = None
        if sbody[12:16] == b'mp4a':
            try:
                body = sbody[8:]        # mp4a box 本体，含 size 字段
                raw_ch = struct.unpack('>H', body[24:26])[0]
                raw_rate = struct.unpack('>I', body[32:36])[0] >> 16
            except struct.error:
                raw_ch = raw_rate = None
        # 个别编码器把 mp4a 采样率字段写 0，真实值在 esds 的 DecoderSpecificInfo 里，此时才回退去解
        sr = ch = None
        if not raw_rate or not raw_ch:
            sr, ch = _esds_params(sbody)
        info['sample_rate'] = raw_rate or sr
        info['channels'] = raw_ch or ch
        info['codec'] = 'aac'

    if info['duration_s']:
        info['bitrate_kbps'] = round(size * 8 / info['duration_s'] / 1000, 1)
    return info


# ---------------------------------------------------------------- WAV

def _probe_wav(path):
    info = {'container': 'wav', 'sample_rate': None, 'channels': None,
            'bits': None, 'duration_s': None, 'peak': None, 'clip_ratio': None}
    with open(path, 'rb') as f:
        riff = f.read(12)
        if len(riff) < 12 or riff[0:4] != b'RIFF' or riff[8:12] != b'WAVE':
            return info
        fmt = None
        data_size = None
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            cid, csize = hdr[0:4], struct.unpack('<I', hdr[4:8])[0]
            if cid == b'fmt ':
                body = f.read(csize)
                if len(body) >= 16:
                    _afmt, ch, rate, _br, _ba, bits = struct.unpack('<HHIIHH', body[:16])
                    fmt = (ch, rate, bits)
                if csize % 2:
                    f.seek(1, os.SEEK_CUR)
            elif cid == b'data':
                data_size = csize
                break
            else:
                f.seek(csize + (csize % 2), os.SEEK_CUR)
        if fmt:
            ch, rate, bits = fmt
            info.update({'channels': ch, 'sample_rate': rate, 'bits': bits})
            if data_size and rate:
                info['duration_s'] = round(data_size / float(rate * ch * (bits // 8)), 2)
        if bits == 16 and data_size:
            f.seek(0, os.SEEK_END)
            total = f.tell()
            f.seek(total - min(total, 8 * 1024 * 1024))   # 取尾部 8 MB 抽样
            raw = f.read()
            n = (len(raw) // 2) * 2
            if n:
                samples = struct.unpack('<%dh' % (n // 2), raw[:n])
                peak = max(abs(min(samples)), abs(max(samples)))
                clipped = sum(1 for s in samples if abs(s) >= 32760)
                info['peak'] = round(peak / 32768.0, 4)
                info['clip_ratio'] = round(clipped / float(len(samples)), 6)
    return info


# ---------------------------------------------------------------- 课件

def _probe_pptx(path):
    info = {'container': 'pptx', 'pages': 0, 'images': 0, 'image_only_pages': 0}
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            slides = sorted([n for n in names
                             if n.startswith('ppt/slides/slide') and n.endswith('.xml')])
            info['pages'] = len(slides)
            info['images'] = len([n for n in names if n.startswith('ppt/media/')])
            image_only = 0
            for n in slides:
                xml = z.read(n).decode('utf-8', 'replace')
                if '<p:pic' in xml and '<a:t>' not in xml:
                    image_only += 1
            info['image_only_pages'] = image_only
    except (zipfile.BadZipFile, KeyError, OSError):
        info['container'] = 'unknown'
    return info


def _probe_pdf(path):
    info = {'container': 'pdf', 'pages': 0, 'images': 0, 'image_only_pages': 0}
    try:
        # page 对象未必在文件头——非"线性化"的 PDF 常把 Page 字典压在 xref 附近（文件后半段）。
        # 只读前 20 MB 会漏掉尾部页字典，页数被算成 0，规格校验误判"未解析到页面"。
        # 这里按文件大小读全（上限 128 MB，超出的课程 PDF 极少见，读到哪算到哪）。
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            raw = f.read(min(size, 128 * 1024 * 1024))
        # /Type /Pages（复数）是 /Type /Page（单数）的子串，先减掉再数页，避免把"页面树"算成页。
        info['pages'] = raw.count(b'/Type /Page') - raw.count(b'/Type /Pages')
        if info['pages'] < 0:
            info['pages'] = raw.count(b'/Type/Page')
        info['images'] = raw.count(b'/Image')
    except OSError:
        pass
    return info


# ---------------------------------------------------------------- 入口

def probe(path, kind, filename=None):
    """kind ∈ {video, audio, slides}；返回 dict，失败时带 probe_error

    filename：原始文件名。上传时落盘的是临时文件（后缀 .part），容器类型只能靠原文件名判，
    否则所有真实上传都会掉进"未知容器"，规格校验变成永远通过——那等于没有校验。
    """
    if not path or not os.path.exists(path):
        return {'probe_error': '文件不存在'}
    size = os.path.getsize(path)
    ext = os.path.splitext(filename or path)[1].lower()
    try:
        if kind == 'video' and ext in VIDEO_EXT:
            info = _probe_mp4(path, size)
        elif kind == 'audio' and ext in AUDIO_EXT:
            if ext in ('.m4a', '.mp3', '.aac', '.ogg'):
                info = _probe_mp4_audio(path, size)
            else:
                info = _probe_wav(path)
        elif kind == 'slides' and ext == '.pptx':
            info = _probe_pptx(path)
        elif kind == 'slides' and ext == '.pdf':
            info = _probe_pdf(path)
        else:
            info = {'container': ext.lstrip('.'), 'note': '未知容器，仅登记字节数'}
    except Exception as exc:                      # 探针绝不因个别文件崩掉整条流水线
        info = {'probe_error': '%s: %s' % (type(exc).__name__, exc)}
    info['bytes'] = size
    return info


def check_spec(kind, info, session=None):
    """规格硬校验。返回 (ok, problems[])。只校验"读得出来且文档有硬要求"的项：
    读不出的字段不判失败——宁可标记未知，也不假造一个合规结论。"""
    problems = []
    if not info or info.get('probe_error'):
        return False, ['探针失败：%s' % (info or {}).get('probe_error', '未知原因')]

    if kind == 'video':
        w, h = info.get('width'), info.get('height')
        # ftyp 与 mvhd 都没有，说明这根本不是 MP4 容器（改了扩展名的东西、损坏文件）。
        # 注意不能只判 duration：moov 在尾部的文件此处已回读，仍读不到才判定无效。
        if not info.get('brand') and not info.get('duration_s') and not info.get('width'):
            problems.append('不是有效的 MP4：未找到 ftyp／moov')
        if w and h and (w < 1280 or h < 720):
            problems.append('分辨率 %dx%d 低于 1280x720' % (w, h))
        codec = info.get('codec')
        if codec and codec not in ('hevc', 'h264'):
            problems.append('编码 %s 不在 H.265／H.264 之列' % codec)
        fps = info.get('fps')
        if fps and not (20 <= fps <= 60):
            problems.append('帧率 %.2f 超出 20–60 的可用范围' % fps)
    elif kind == 'audio':
        rate = info.get('sample_rate')
        container = info.get('container', '')
        if not rate and not info.get('duration_s'):
            # 区分容器给更准的提示：WAV 看 RIFF，M4A/AAC 看 mp4a/esds
            if container == 'm4a':
                problems.append('不是有效的 M4A／AAC：未找到 mp4a／esds 音频轨')
            else:
                problems.append('不是有效的 WAV：未找到 RIFF 的 fmt／data 块')
        if rate and rate < 16000:
            problems.append('采样率 %d Hz 低于 16 kHz' % rate)
        clip = info.get('clip_ratio')
        if clip is not None and clip > 0.02:
            problems.append('削波样本占 %.2f%%，超过 2%% 上限' % (clip * 100))
    elif kind == 'slides':
        pages = info.get('pages') or 0
        if pages <= 0:
            problems.append('未解析到页面')
        elif pages > 300:
            problems.append('页数 %d 超过 300' % pages)
    return (len(problems) == 0), problems
