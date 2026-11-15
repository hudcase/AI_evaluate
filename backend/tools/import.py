#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/import.py — 批量导入课例数据

三种用法，都走 HTTP 接口（不直接写库），所以规格校验、探针、sha256 去重、审计一个都不会漏。

  1. 清单导入（推荐，字段完整可控）
       python backend/tools/import.py manifest 清单.json --base http://127.0.0.1:8000

  2. 目录扫描（手上就是一堆按目录放好的文件）
       python backend/tools/import.py scan ./原始数据 --consent --base http://127.0.0.1:8000

  3. 指标原始量导入（观测值 CSV）
       python backend/tools/import.py obs 观测.csv --session S-20261105-03 --base ...

通用参数：
  --base URL      后端地址，默认 http://127.0.0.1:8000
  --dry-run       只打印计划，不发请求
  --in-place      只登记盘上已有文件，不复制字节（大原片用它）
  --replace       同 slot 已有资产时替换（默认报冲突）
  --preprocess    导入完成后立刻触发预处理
  --timeout 秒    单次请求超时，默认 600（大文件慢盘要放宽）

退出码：0 全部成功；1 有失败项（失败原因逐条打印）。
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote

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

STAT = {'course': 0, 'session': 0, 'asset': 0, 'duplicate': 0, 'obs': 0,
        'skip': 0, 'fail': 0}


# ---------------------------------------------------------------- HTTP

class ApiFail(Exception):
    def __init__(self, code, message, status=0):
        super(ApiFail, self).__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _base_url(s):
    s = (s or '').strip().rstrip('/')
    if not s.startswith('http'):
        s = 'http://' + s
    return s


def _read_json(resp):
    raw = resp.read()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode('utf-8'))
    except ValueError:
        return {'raw': raw[:200].decode('utf-8', 'replace')}


def call(base, method, path, body=None, timeout=600):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read_json(resp)
    except urllib.error.HTTPError as exc:
        payload = _read_json(exc)
        err = (payload or {}).get('error') or {}
        raise ApiFail(err.get('code') or 'HTTP_%d' % exc.code,
                      err.get('message') or str(exc), exc.code)
    except urllib.error.URLError as exc:
        raise ApiFail('UNREACHABLE', '连不上 %s：%s' % (base, exc.reason))


class _Multipart(object):
    """边读边发的 multipart 请求体：几十 GB 的原片不会进内存。"""

    def __init__(self, fields, filepath, fieldname='file'):
        self.boundary = '----evalimport' + uuid.uuid4().hex
        b = self.boundary.encode('ascii')
        self.parts = []
        for k, v in (fields or {}).items():
            if v is None:
                continue
            head = ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n'
                    % (self.boundary, k)).encode('utf-8')
            self.parts.append((head + str(v).encode('utf-8') + b'\r\n', None))
        name = os.path.basename(filepath).replace('"', '_')
        head = ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n'
                % (self.boundary, fieldname, name)).encode('utf-8')
        self.parts.append((head, filepath))
        self.parts.append((b'\r\n--' + b + b'--\r\n', None))

        self.length = 0
        for blob, path in self.parts:
            self.length += len(blob)
            if path:
                self.length += os.path.getsize(path)
        self._it = None
        self._buf = b''
        self._sent = 0

    def _chunks(self):
        for blob, path in self.parts:
            if blob:
                yield blob
            if path:
                with open(path, 'rb') as fh:
                    while True:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            break
                        yield chunk

    def read(self, amt=-1):
        if self._it is None:
            self._it = self._chunks()
        if amt is None or amt < 0:
            amt = self.length - self._sent
        while len(self._buf) < amt:
            try:
                self._buf += next(self._it)
            except StopIteration:
                break
        out, self._buf = self._buf[:amt], self._buf[amt:]
        self._sent += len(out)
        return out


def upload(base, sid, fields, filepath, timeout=600):
    stream = _Multipart(fields, filepath)
    req = urllib.request.Request(
        base + '/api/sessions/%s/media' % sid, data=stream, method='POST',
        headers={'Content-Type': 'multipart/form-data; boundary=%s' % stream.boundary,
                 'Content-Length': str(stream.length)})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read_json(resp)
    except urllib.error.HTTPError as exc:
        payload = _read_json(exc)
        err = (payload or {}).get('error') or {}
        raise ApiFail(err.get('code') or 'HTTP_%d' % exc.code,
                      err.get('message') or str(exc), exc.code)
    except urllib.error.URLError as exc:
        raise ApiFail('UNREACHABLE', '连不上 %s：%s' % (base, exc.reason))


# ---------------------------------------------------------------- 输出

def say(msg=''):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def ok(msg):
    say('  ok    ' + msg)


def warn(msg, count=True):
    say('  skip  ' + msg)
    if count:
        STAT['skip'] += 1


def bad(msg):
    say('  FAIL  ' + msg)
    STAT['fail'] += 1


# ---------------------------------------------------------------- 媒体分类

def guess_slot(path, typ, taken):
    """按文件名猜 slot；猜不出就按顺序占位，并把这件事说出来（不静默）。"""
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
        if any(k in name for k in ('ambient', 'env', '环境', 'room')):
            return 'ambient'
        return 'lavalier'
    if typ == 'slides':
        return 'deck'
    return None


# ---------------------------------------------------------------- 复用已有对象
#
# 导入脚本必须能重跑：批量导入经常在第三门课失败、改完继续跑。
# 如果每次都新建课程和场次，重跑一次就多出一整套重复课次。
# 复用判据用"课程标题相同"和"日期＋开始时间＋标题相同"——这两组在实际业务里已经足够唯一。

def today():
    return datetime.date.today().strftime('%Y-%m-%d')


def find_course(ctx, title):
    if ctx.new:
        return None
    try:
        out = call(ctx.base, 'GET', '/api/courses?size=200&q=' + quote(title), timeout=30)
    except ApiFail:
        return None
    for c in out.get('items') or []:
        if (c.get('title') or '').strip() == title.strip():
            return c['id']
    return None


def find_session(ctx, cid, title, date, start):
    if ctx.new:
        return None
    try:
        c = call(ctx.base, 'GET', '/api/courses/' + cid, timeout=30)
    except ApiFail:
        return None
    for s in c.get('sessions') or []:
        if ((s.get('title') or '').strip() == title.strip()
                and (s.get('date') or '') == date
                and (s.get('start') or '')[:5] == (start or '')[:5]):
            return s['id']
    return None


def ensure_course(ctx, title, goals, students=0):
    """返回 (course_id, reused)。带 goals 的课程不覆盖已有目标——目标是对外口径，不做静默改写。"""
    if ctx.dry_run:
        say('    ..    课程：%s' % ('复用已有' if find_course(ctx, title) else '新建'))
        return 'C-DRYRUN', False
    cid = find_course(ctx, title)
    if cid:
        ok('复用课程 %s（目标沿用已存在的版本，不覆盖）' % cid)
        return cid, True
    cid = call(ctx.base, 'POST', '/api/courses',
               {'title': title, 'expected_students': students, 'goals': goals})['id']
    STAT['course'] += 1
    ok('课程 %s' % cid)
    return cid, False


def ensure_session(ctx, cid, body):
    """返回 (session_id, reused)。"""
    if ctx.dry_run:
        say('    ..    场次：%s %s %s'
            % (body['date'], body['start'], body['title']))
        return 'S-DRYRUN', False
    sid = find_session(ctx, cid, body['title'], body['date'], body['start'])
    if sid:
        ok('复用场次 %s（%s）' % (sid, body['scenario']))
        return sid, True
    sid = call(ctx.base, 'POST', '/api/sessions', body)['id']
    STAT['session'] += 1
    ok('场次 %s（%s）' % (sid, body['scenario']))
    return sid, False


# ---------------------------------------------------------------- 子命令：manifest

MANIFEST_HINT = """清单结构（JSON）：
{
  "courses": [{
    "title": "新任经理管理能力培训", "expected_students": 32,
    "goals": [{"text": "能说清管理者的三项核心职责", "tier": "core"}],
    "sessions": [{
      "title": "第一讲 角色认知", "date": "2026-11-05", "start": "09:00",
      "duration_min": 90, "scenario": "theory", "teacher": "张某", "room": "A301",
      "consent_confirmed": true,
      "media": [{"file": "1105/cam1.mp4", "type": "video", "slot": "cam1"}],
      "observations": [{"code": "A2", "raw_value": 0.82,
                        "source_track": ["audio", "slides"], "confidence": 0.9}]
    }]
  }]
}
规则：goals 至少要有一条 tier=core；每个场次必须 consent_confirmed=true；
media.file 路径相对清单文件所在目录；scenario 只能是 theory／seminar／practical。"""


def load_goals_from_dir(course_dir):
    """目录里如果有 goals.json / goals.txt 就读出来；没有就返回 None（不编目标）。"""
    js = os.path.join(course_dir, 'goals.json')
    if os.path.isfile(js):
        with open(js, 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
        if isinstance(raw, list):
            return [g if isinstance(g, dict) else {'text': str(g), 'tier': 'core' if i == 0 else 'support'}
                    for i, g in enumerate(raw)]
        if isinstance(raw, dict) and raw.get('goals'):
            return raw['goals']
    txt = os.path.join(course_dir, 'goals.txt')
    if os.path.isfile(txt):
        out = []
        with open(txt, 'r', encoding='utf-8') as fh:
            for line in fh:
                s = line.strip().lstrip('-*· ').strip()
                if not s or s.startswith('#'):
                    continue
                out.append({'text': s, 'tier': 'core' if not out else 'support'})
        return out or None
    return None


def run_manifest(ctx, doc):
    root = os.path.dirname(os.path.abspath(ctx.manifest)) or os.getcwd()
    if not isinstance(doc.get('courses'), list) or not doc['courses']:
        bad('清单里没有 courses 数组')
        return

    for c in doc['courses']:
        title = (c.get('title') or '').strip()
        goals = c.get('goals') or []
        say('')
        say('[课程] %s（%d 条目标）' % (title or '(无标题)', len(goals)))
        if not title:
            bad('课程缺 title，跳过')
            continue
        if not goals:
            bad('课程 %s 缺 goals（至少要一条 core 目标，A2 的分母靠它）' % title)
            continue
        try:
            cid, _ = ensure_course(ctx, title, goals, c.get('expected_students') or 0)
        except ApiFail as exc:
            bad('建课程失败 %s：%s' % (exc.code, exc.message))
            continue

        for s in c.get('sessions') or []:
            run_session(ctx, cid, s, root)


def run_session(ctx, cid, s, root):
    title = (s.get('title') or '').strip()
    say('')
    say('  [场次] %s' % (title or '(无标题)'))
    consent = s.get('consent_confirmed')
    if consent is not True:
        if not ctx.consent:
            bad('场次缺 consent_confirmed=true（知情同意是流程约束，不提供就不得入库；'
                '确认已取得后加 --consent 重跑）')
            return
        consent = True

    body = {'course_id': cid, 'title': title, 'consent_confirmed': True,
            'scenario': s.get('scenario') or 'theory',
            'date': s.get('date') or today(), 'start': s.get('start') or '09:00',
            'duration_min': s.get('duration_min') or 90,
            'teacher': s.get('teacher'), 'room': s.get('room'),
            'expected_students': s.get('expected_students')}
    try:
        sid, _ = ensure_session(ctx, cid, body)
    except ApiFail as exc:
        bad('建场次失败 %s：%s' % (exc.code, exc.message))
        return

    for m in s.get('media') or []:
        import_one(ctx, sid, m, root)

    for o in s.get('observations') or []:
        post_obs(ctx, sid, o)

    if ctx.preprocess and not ctx.dry_run:
        try:
            t = call(ctx.base, 'POST', '/api/sessions/%s/preprocess' % sid,
                     {'stages': None})
            ok('已触发预处理 %s' % t.get('task_id'))
        except ApiFail as exc:
            bad('触发预处理失败 %s：%s' % (exc.code, exc.message))


def import_one(ctx, sid, m, root):
    typ = m.get('type')
    if typ not in ('video', 'audio', 'slides', 'goals'):
        bad('未知 type=%s' % typ)
        return
    f = m.get('file') or m.get('path')
    if not f:
        bad('媒体缺 file 字段')
        return
    path = f if os.path.isabs(f) else os.path.join(root, f)
    if not os.path.isfile(path):
        bad('文件不存在：%s' % path)
        return

    slot = m.get('slot')
    if typ in ('video', 'audio', 'slides') and not slot:
        slot = guess_slot(path, typ, set())
    fields_common = {'type': typ, 'slot': slot}
    name = os.path.basename(path)

    if ctx.dry_run:
        say('    ..    %s → %s/%s（%s，%.1f MB）%s'
            % (name, typ, slot, '登记' if ctx.in_place else '直传',
               os.path.getsize(path) / 1048576.0,
               '（replace）' if ctx.replace else ''))
        return

    try:
        if ctx.in_place:
            body = {'path': path, 'name': name}
            body.update(fields_common)
            if ctx.replace:
                body['replace'] = True
            out = call(ctx.base, 'POST', '/api/sessions/%s/media' % sid, body)
        else:
            fields = dict(fields_common)
            if ctx.replace:
                fields['replace'] = 'true'
            out = upload(ctx.base, sid, fields, path, timeout=ctx.timeout)
    except ApiFail as exc:
        bad('%s 导入失败 %s：%s' % (name, exc.code, exc.message))
        return

    if out.get('duplicate'):
        STAT['duplicate'] += 1
        warn('%s 内容重复（本场次已有同内容资产 %s），未重复入库'
             % (name, out.get('asset_id') or out.get('id')), count=False)
        return
    STAT['asset'] += 1
    probe = out.get('probe') or {}
    extra = []
    if probe.get('duration_s'):
        extra.append('%d 秒' % round(probe['duration_s']))
    if probe.get('width'):
        extra.append('%dx%d' % (probe['width'], probe['height']))
    if probe.get('sample_rate'):
        extra.append('%d Hz' % probe['sample_rate'])
    ok('%s → %s/%s %s' % (name, typ, out.get('slot') or slot,
                          ('（' + '，'.join(extra) + '）') if extra else ''))


# ---------------------------------------------------------------- 子命令：scan

DATE_RE = re.compile(r'(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})')
TIME_RE = re.compile(r'(\d{2})[-_.:]?(\d{2})(?!\d)')


def parse_dir_name(name):
    d = DATE_RE.search(name)
    t = TIME_RE.search(name[d.end():]) if d else None
    date = '%s-%s-%s' % d.groups() if d else None
    start = ('%s:%s' % t.groups()) if t else None
    return date, start


def run_scan(ctx, root):
    if not os.path.isdir(root):
        bad('目录不存在：%s' % root)
        return
    courses = sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))])
    if not courses:
        bad('目录下没有任何课程子目录：%s（约定：<根>/<课程>/<场次>/文件）' % root)
        return

    for cname in courses:
        cdir = os.path.join(root, cname)
        goals = load_goals_from_dir(cdir)
        say('')
        say('[课程] %s（%d 条目标）' % (cname, len(goals or [])))
        if not goals:
            bad('缺 %s/goals.txt 或 goals.json：课程目标不能由工具编，请按"一行一条、'
                '首行为核心目标"补上后重跑' % cname)
            continue
        try:
            cid, _ = ensure_course(ctx, cname, goals)
        except ApiFail as exc:
            bad('建课程失败 %s：%s' % (exc.code, exc.message))
            continue

        sess_dirs = sorted([d for d in os.listdir(cdir) if os.path.isdir(os.path.join(cdir, d))])
        if not sess_dirs:
            sess_dirs = ['.']       # 课程目录下直接放文件：当作单场次

        for sdir in sess_dirs:
            full = cdir if sdir == '.' else os.path.join(cdir, sdir)
            stitle = cname if sdir == '.' else sdir
            date, start = parse_dir_name(stitle)
            if not ctx.consent:
                bad('场次 %s：未确认知情同意，未入库（确认后加 --consent）' % stitle)
                continue
            body = {'course_id': cid, 'title': stitle, 'consent_confirmed': True,
                    'scenario': 'theory', 'date': date or today(), 'start': start or '09:00',
                    'duration_min': ctx.duration}
            say('')
            say('  [场次] %s（%s %s）' % (stitle, body['date'], body['start']))
            try:
                sid, _ = ensure_session(ctx, cid, body)
            except ApiFail as exc:
                bad('建场次失败 %s：%s' % (exc.code, exc.message))
                continue

            taken = set()
            files = sorted([f for f in os.listdir(full) if os.path.isfile(os.path.join(full, f))])
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                typ = TYPE_OF_EXT.get(ext)
                if not typ:
                    warn('不认识的类型，未导入：%s（支持 %s）'
                         % (fname, '／'.join(VIDEO_EXT + AUDIO_EXT + SLIDE_EXT)))
                    continue
                path = os.path.join(full, fname)
                slot = guess_slot(path, typ, taken)
                if slot is None:
                    bad('%s 没有可用 slot（视频位 cam1–cam4 已占满）' % fname)
                    continue
                taken.add(slot)
                import_one(ctx, sid, {'file': path, 'type': typ, 'slot': slot}, full)

            if ctx.preprocess and not ctx.dry_run:
                try:
                    t = call(ctx.base, 'POST', '/api/sessions/%s/preprocess' % sid, {'stages': None})
                    ok('已触发预处理 %s' % t.get('task_id'))
                except ApiFail as exc:
                    bad('触发预处理失败 %s：%s' % (exc.code, exc.message))


# ---------------------------------------------------------------- 子命令：obs

OBS_COLS = ('session_id', 'code', 'raw_value', 'denominator', 'confidence',
            'evidence_t', 'source_track', 'evidence_note', 'empty_reason', 'model_version')


def post_obs(ctx, sid, row):
    code = (row.get('code') or '').strip()
    if not code:
        bad('观测行缺 code')
        return
    body = {'code': code}
    raw = row.get('raw_value')
    if raw is None or str(raw).strip() == '':
        body['raw_value'] = None
    else:
        try:
            body['raw_value'] = float(str(raw).strip())
        except ValueError:
            bad('%s 的 raw_value 不是数值：%r' % (code, raw))
            return
    for k in ('denominator', 'confidence'):
        v = row.get(k)
        if v not in (None, ''):
            try:
                body[k] = float(v)
            except ValueError:
                bad('%s 的 %s 不是数值：%r' % (code, k, v))
                return
    for k in ('evidence_t', 'evidence_note', 'empty_reason', 'model_version'):
        v = row.get(k)
        if v not in (None, ''):
            body[k] = str(v).strip()
    tracks = row.get('source_track')
    if tracks:
        if isinstance(tracks, (list, tuple)):
            body['source_track'] = [str(t).strip() for t in tracks if str(t).strip()]
        else:
            body['source_track'] = [t for t in re.split(r'[+,;|／/\s]+', str(tracks)) if t]

    if ctx.dry_run:
        say('    ..    %s raw=%s' % (code, body.get('raw_value')))
        return
    try:
        out = call(ctx.base, 'POST', '/api/sessions/%s/observations' % sid, body)
        STAT['obs'] += 1
        score = out.get('score')
        ok('%s raw=%s → 分项分 %s' % (code, body.get('raw_value'),
                                     '空值' if score is None else score))
    except ApiFail as exc:
        bad('%s 写入失败 %s：%s' % (code, exc.code, exc.message))


def run_obs(ctx, path):
    if not os.path.isfile(path):
        bad('CSV 不存在：%s' % path)
        return
    with open(path, 'r', encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        bad('CSV 没有数据行')
        return
    missing = [c for c in ('code',) if c not in (rows[0] or {})]
    if missing:
        bad('CSV 缺列：%s（表头建议 %s）' % ('、'.join(missing), '／'.join(OBS_COLS)))
        return

    say('')
    say('[观测值] %d 行' % len(rows))
    for i, row in enumerate(rows, 1):
        # 命令行 --session 优先：CSV 里那一列多半是从别的库拷来的旧编号
        sid = (ctx.session or (row.get('session_id') or '')).strip()
        if not sid:
            bad('第 %d 行没有 session_id，也没给 --session' % i)
            continue
        post_obs(ctx, sid, row)


# ---------------------------------------------------------------- 入口

def main(argv=None):
    ap = argparse.ArgumentParser(
        description='批量导入课例数据（走 HTTP 接口，保留全部校验）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=MANIFEST_HINT)
    sub = ap.add_subparsers(dest='cmd')

    def common(p):
        p.add_argument('--base', default='http://127.0.0.1:8000', help='后端地址')
        p.add_argument('--dry-run', action='store_true', help='只打印计划，不发请求')
        p.add_argument('--in-place', action='store_true', help='只登记盘上文件，不复制字节')
        p.add_argument('--replace', action='store_true', help='同 slot 已有资产时替换')
        p.add_argument('--preprocess', action='store_true', help='导入后触发预处理')
        p.add_argument('--timeout', type=int, default=600, help='单次请求超时（秒）')
        p.add_argument('--new', action='store_true',
                       help='不复用同名课程／同日期场次，强制新建（默认复用，便于重跑）')

    p1 = sub.add_parser('manifest', help='按 JSON 清单导入')
    p1.add_argument('manifest')
    p1.add_argument('--consent', action='store_true', help='统一声明已取得知情同意')
    common(p1)

    p2 = sub.add_parser('scan', help='按目录约定扫描导入')
    p2.add_argument('root')
    p2.add_argument('--consent', action='store_true', help='已取得知情同意')
    p2.add_argument('--duration', type=int, default=90, help='场次时长（分钟），默认 90')
    common(p2)

    p3 = sub.add_parser('obs', help='导入指标原始量（CSV）')
    p3.add_argument('csv')
    p3.add_argument('--session', default='', help='CSV 无 session_id 列时统一指定')
    common(p3)

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2

    args.base = _base_url(args.base)
    args.dry_run = bool(args.dry_run)
    args.consent = bool(getattr(args, 'consent', False))
    args.in_place = bool(args.in_place)
    args.replace = bool(args.replace)
    args.preprocess = bool(args.preprocess)
    args.session = getattr(args, 'session', '')
    args.duration = getattr(args, 'duration', 90)
    args.manifest = getattr(args, 'manifest', None)
    args.new = bool(args.new)

    if not args.dry_run:
        try:
            h = call(args.base, 'GET', '/api/health', timeout=15)
        except ApiFail as exc:
            say('后端不可用：%s' % exc.message)
            say('先启动：python backend/app.py --seed-demo')
            return 2
        say('后端 %s  provider=%s  ffmpeg=%s'
            % (h.get('version'), h.get('provider_mode'), '有' if h.get('ffmpeg') else '无'))

    if args.cmd == 'manifest':
        try:
            with open(args.manifest, 'r', encoding='utf-8-sig') as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            say('读清单失败：%s' % exc)
            return 2
        run_manifest(args, doc)
    elif args.cmd == 'scan':
        run_scan(args, args.root)
    else:
        run_obs(args, args.csv)

    say('')
    say('汇总：课程 %d，场次 %d，媒资 %d，重复 %d，观测 %d，未识别 %d，失败 %d'
        % (STAT['course'], STAT['session'], STAT['asset'], STAT['duplicate'],
           STAT['obs'], STAT['skip'], STAT['fail']))
    if args.dry_run:
        say('（--dry-run：以上均为计划，未写库）')
    return 1 if STAT['fail'] else 0


if __name__ == '__main__':
    sys.exit(main())
