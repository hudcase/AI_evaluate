"""scan_dir.py — 目录扫描 → 批量入库清单

桌面版的"选个文件夹就入库"靠它：用户在原生对话框里挑一个根目录，这里按约定把
目录树翻译成 POST /api/import 能吃的 manifest，前端把清单显示出来供人确认，
再提交给 m8_import 落库。全程不猜业务字段——缺 goals.txt 就报缺，不替用户编目标。

目录约定（与 backend/tools/import.py 的 scan 子命令完全一致）：

    <根>/
      课程 A/
        goals.txt            # 一行一条，首行为核心目标；或 goals.json
        2026-11-05 09-00/    # 场次目录，目录名里的日期与时间会被解析
          cam1.mp4
          lavalier.m4a
          讲义.pptx
      课程 B/
        goals.json
        只有一层/            # 课程目录下直接放文件 = 单场次

单场次可缺省日期/时间，缺省时用 today/09:00，但会在 issues 里说出来。
"""
import json
import os
import re

VIDEO_EXT = ('.mp4', '.mov', '.mkv', '.avi', '.m4v')
AUDIO_EXT = ('.wav', '.flac', '.mp3', '.m4a', '.aac', '.ogg')
SLIDE_EXT = ('.pptx', '.pdf')

TYPE_OF_EXT = {}
for _e in VIDEO_EXT:
    TYPE_OF_EXT[_e] = 'video'
for _e in AUDIO_EXT:
    TYPE_OF_EXT[_e] = 'audio'
for _e in SLIDE_EXT:
    TYPE_OF_EXT[_e] = 'slides'

DATE_RE = re.compile(r'(20\d{2})[-_.年]?(\d{2})[-_.月]?(\d{2})')
TIME_RE = re.compile(r'(\d{1,2})[-_.:时]?(\d{2})(?!\d)')

MAX_VIDEO_SLOTS = 2          # V3.0：视频只认 2 路（cam1 全景、cam2 后排）


def _today():
    import datetime
    return datetime.date.today().strftime('%Y-%m-%d')


def parse_dir_name(name):
    """从目录名里抠出 (date, start)。抠不出就返回 None，由调用方兜底。"""
    d = DATE_RE.search(name)
    date = None
    start = None
    rest = name
    if d:
        date = '%s-%s-%s' % d.groups()
        rest = name[d.end():]
    t = TIME_RE.search(rest)
    if t:
        hh = int(t.group(1))
        mm = int(t.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            start = '%02d:%02d' % (hh, mm)
    return date, start


def load_goals(course_dir):
    """goals.json 优先，其次 goals.txt（一行一条，首行为核心目标）。没有就 None。"""
    js = os.path.join(course_dir, 'goals.json')
    if os.path.isfile(js):
        try:
            with open(js, 'r', encoding='utf-8-sig') as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return None
        if isinstance(raw, list):
            out = []
            for i, g in enumerate(raw):
                if isinstance(g, dict):
                    out.append({'text': str(g.get('text') or '').strip(),
                                'tier': g.get('tier') or ('core' if i == 0 else 'support')})
                else:
                    out.append({'text': str(g).strip(),
                                'tier': 'core' if i == 0 else 'support'})
            return [g for g in out if g['text']] or None
        if isinstance(raw, dict) and isinstance(raw.get('goals'), list):
            return load_goals_from_list(raw['goals'])
    txt = os.path.join(course_dir, 'goals.txt')
    if os.path.isfile(txt):
        out = []
        try:
            with open(txt, 'r', encoding='utf-8-sig') as fh:
                for line in fh:
                    s = line.strip().lstrip('-*·　 ').strip()
                    if not s or s.startswith('#'):
                        continue
                    out.append({'text': s, 'tier': 'core' if not out else 'support'})
        except OSError:
            return None
        return out or None
    return None


def load_goals_from_list(items):
    out = []
    for i, g in enumerate(items):
        if isinstance(g, dict):
            out.append({'text': str(g.get('text') or '').strip(),
                        'tier': g.get('tier') or ('core' if i == 0 else 'support')})
        else:
            out.append({'text': str(g).strip(), 'tier': 'core' if i == 0 else 'support'})
    return [g for g in out if g['text']] or None


def guess_slot(path, typ, taken):
    name = os.path.basename(path).lower()
    if typ == 'video':
        m = re.search(r'cam\s*([1-4])', name)
        if m:
            return 'cam%s' % m.group(1)
        for i in range(1, 5):
            if 'cam%d' % i not in taken:
                return 'cam%d' % i
        return None
    if typ == 'audio':
        if any(k in name for k in ('ambient', 'env', '环境', 'room', '全向')):
            return 'ambient'
        return 'lavalier'
    if typ == 'slides':
        return 'deck'
    return None


def _media_of(folder, issues, where):
    """把一个场次目录里的文件翻成 media 数组"""
    taken = set()
    media = []
    vcount = 0
    for fname in sorted(os.listdir(folder)):
        path = os.path.join(folder, fname)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(fname)[1].lower()
        typ = TYPE_OF_EXT.get(ext)
        if not typ:
            issues.append({'level': 'warn', 'where': where,
                           'text': '不认识的类型，未纳入：%s' % fname})
            continue
        slot = guess_slot(path, typ, taken)
        if slot is None:
            issues.append({'level': 'error', 'where': where,
                           'text': '%s 没有可用机位（cam1–cam4 已占满）' % fname})
            continue
        if slot in taken:
            issues.append({'level': 'error', 'where': where,
                           'text': '%s 的机位 %s 已被占用，跳过' % (fname, slot)})
            continue
        taken.add(slot)
        if typ == 'video':
            vcount += 1
            if vcount > MAX_VIDEO_SLOTS:
                issues.append({'level': 'warn', 'where': where,
                               'text': '视频已超过 %d 路（%s），规格要求只收 2 路；'
                                       '仍按 %s 登记，后续门禁会判不符' % (MAX_VIDEO_SLOTS, fname, slot)})
        item = {'path': path, 'type': typ, 'slot': slot,
                'name': fname, 'bytes': os.path.getsize(path)}
        media.append(item)
    return media


def scan(root, scenario='theory', duration_min=90, consent=True):
    """扫描根目录，返回 (manifest, issues, stats)。

    consent=True 表示操作者已在界面上勾选"已取得知情同意"——这个字段是流程约束，
    不能由扫描器自己填 true，所以由调用方显式传入。
    """
    root = os.path.abspath(root)
    issues = []
    stats = {'courses': 0, 'sessions': 0, 'media': 0, 'bytes': 0}
    manifest = {'courses': []}

    if not os.path.isdir(root):
        return manifest, [{'level': 'error', 'where': root, 'text': '目录不存在'}], stats

    course_dirs = sorted([d for d in os.listdir(root)
                          if not d.startswith('.') and os.path.isdir(os.path.join(root, d))])
    if not course_dirs:
        return manifest, [{'level': 'error', 'where': root,
                           'text': '根目录下没有课程子目录（约定：<根>/<课程>/<场次>/文件）'}], stats

    for cname in course_dirs:
        cdir = os.path.join(root, cname)
        goals = load_goals(cdir)
        if not goals:
            issues.append({'level': 'error', 'where': cname,
                           'text': '缺 %s/goals.txt 或 goals.json（课程目标不能由工具编，'
                                   '请一行一条、首行为核心目标补上后重扫）' % cname})
            goals = []

        course = {'title': cname, 'goals': goals, 'expected_students': 0, 'sessions': []}
        stats['courses'] += 1

        sess_dirs = sorted([d for d in os.listdir(cdir)
                            if not d.startswith('.') and os.path.isdir(os.path.join(cdir, d))])
        if not sess_dirs:
            sess_dirs = ['.']                      # 课程目录下直接放文件 = 单场次

        for sdir in sess_dirs:
            folder = cdir if sdir == '.' else os.path.join(cdir, sdir)
            stitle = cname if sdir == '.' else sdir
            date, start = parse_dir_name(stitle)
            where = '%s / %s' % (cname, stitle)
            if not date:
                issues.append({'level': 'warn', 'where': where,
                               'text': '目录名里没有日期，按今天 %s 入库' % _today()})
            if not start:
                issues.append({'level': 'warn', 'where': where,
                               'text': '目录名里没有时间，按 09:00 入库'})
            media = _media_of(folder, issues, where)
            if not media:
                issues.append({'level': 'warn', 'where': where,
                               'text': '这个场次目录里没有可入库的音视频或课件'})
            session = {
                'title': stitle, 'date': date or _today(), 'start': start or '09:00',
                'duration_min': duration_min, 'scenario': scenario,
                'consent_confirmed': bool(consent),
                'media': [{k: m[k] for k in ('path', 'type', 'slot', 'name')} for m in media],
            }
            course['sessions'].append(session)
            stats['sessions'] += 1
            stats['media'] += len(media)
            stats['bytes'] += sum(m['bytes'] for m in media)

        manifest['courses'].append(course)

    return manifest, issues, stats
