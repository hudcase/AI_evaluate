"""modules/m2_media.py — M2 数据接入

三种登记方式，都能用，语义不同：

  1. **multipart 直传**：文件真的落到 data/media/<session>/，服务端自己算 sha256、
     自己跑探针、按文档规格硬校验（不过就 422），最后写 media_assets。
  2. **本地文件登记**（JSON 带 `path`）：文件已经在盘上（采集机同盘目录、外挂盘、网络盘），
     只登记路径不搬字节。sha256 与探针照算，规格照校验，status 记 ok。
     4K 一节课几十 GB，全量拷贝一次既慢又费盘，这条路就是给它留的。
  3. **仅登记**（JSON 无 `path`、无字节）：只想记"曾经有过这个资产"，sha256 为 null，
     页面显示"未落盘"，探针阶段会标 degraded。前端演示上传走这条。

预签名直传本身留空（501）：那需要对象存储与签名服务，端侧单机部署没有这一层；
接口形状已按文档就位，接 S3／MinIO 时在 presign() 里补即可。
"""
import os
import shutil

import config
import db
import errors
import util

from core import probes

from . import _common

TYPE_SLOT = {
    'video': ('cam1', 'cam2', 'cam3', 'cam4'),
    'audio': ('lavalier', 'ambient'),
    'slides': ('deck',),
    'goals': ('goals',),
}


def list_media(sid):
    _common.require_session(sid)
    return {'items': [_common.media_public(r) for r in _common.media_rows(sid)]}


def _check_type_slot(body):
    typ = body.get('type')
    if typ not in TYPE_SLOT:
        errors.fail('VALIDATION_FAILED', 'type 需为 video／audio／slides／goals', 'type')
    slot = body.get('slot')
    if slot and slot not in TYPE_SLOT[typ]:
        errors.fail('VALIDATION_FAILED', '%s 的 slot 需为 %s' % (typ, '／'.join(TYPE_SLOT[typ])), 'slot')
    return typ, slot or TYPE_SLOT[typ][0]


def _guard_slot(sid, slot, replace):
    """一个 slot 只允许一个有效资产；替换要把旧的软删掉，不能并排躺着。"""
    existing = db.q1("""SELECT * FROM media_assets WHERE session_id=? AND slot=? AND deleted_at IS NULL""",
                     (sid, slot))
    if existing and not replace:
        raise errors.ApiError('STATE_CONFLICT',
                              '%s 位已有资产 %s；如需替换请带 replace=true' % (slot, existing['id']),
                              'slot')
    if existing:
        db.x('UPDATE media_assets SET deleted_at=? WHERE id=?', (util.iso(), existing['id']))
    return existing


def _insert(sid, typ, slot, name, path, size, sha, duration, probe, status):
    asset_id = util.new_id('M')
    db.x("""INSERT INTO media_assets (id, session_id, type, slot, name, path, bytes, sha256,
                                      duration_s, probe_json, retention_days, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (asset_id, sid, typ, slot, name, path, size, sha, duration,
          util.dumps(probe), config.RETENTION.get(typ), status, util.iso()))
    return asset_id


def _by_sha(sha, sid):
    """同一场次内按内容判重：同一节课被人重复导入两次时，第二次应该直接告诉他"已经有了"。

    判重范围**只到场次**，不是全库：同一份课件、同一段演示录像被多节课复用是正常情况，
    全库判重会把第二节及之后的课全部拦掉。
    """
    if not sha:
        return None
    return db.q1("""SELECT * FROM media_assets
                    WHERE sha256 = ? AND session_id = ? AND deleted_at IS NULL LIMIT 1""",
                 (sha, sid))


def register(sid, body):
    """JSON 登记（无文件字节，或只给本地路径）"""
    session = _common.require_session(sid)
    act = body.get('action')
    if act == 'presign':
        raise errors.ApiError(
            'NOT_IMPLEMENTED',
            '预签名直传需对象存储签名服务，本版本未接入；'
            '请改用 multipart 直传（POST /api/sessions/{id}/media, form-data），'
            '或在端侧把文件放好后再用本接口登记。')
    if act == 'commit':
        asset_id = body.get('asset_id')
        row = db.q1('SELECT * FROM media_assets WHERE id = ? AND session_id = ?', (asset_id, sid))
        if not row:
            errors.not_found('资产', asset_id)
        db.x("UPDATE media_assets SET status='ok' WHERE id=?", (asset_id,))
        db.audit('media.commit', sid, 'admin', {'asset_id': asset_id})
        return _common.media_public(db.q1('SELECT * FROM media_assets WHERE id=?', (asset_id,)))

    if body.get('path'):
        return _register_local(sid, session, body)

    typ, slot = _check_type_slot(body)
    _guard_slot(sid, slot, body.get('replace'))

    probe = body.get('probe') or {}
    ok, problems = probes.check_spec(typ, probe, session)
    if not ok and probe:
        # 登记态没有字节，规格只能按调用方报送的 probe 判；不符合即拒收
        raise errors.ApiError('SPEC_MISMATCH', '规格不符：' + '；'.join(problems), 'probe',
                              {'problems': problems})

    asset_id = _insert(sid, typ, slot,
                       body.get('name') or ('%s.%s' % (slot, 'pptx' if typ == 'slides' else 'bin')),
                       None, int(body.get('bytes') or 0), body.get('sha256'),
                       body.get('duration_s') or (session['duration_min'] * 60
                                                  if typ in ('video', 'audio') else None),
                       probe, 'registered')
    db.audit('media.register', sid, 'admin', {'asset_id': asset_id, 'type': typ, 'slot': slot})
    out = _common.media_public(db.q1('SELECT * FROM media_assets WHERE id=?', (asset_id,)))
    out.update({'asset_id': asset_id, 'duplicate': False})
    return out


def _register_local(sid, session, body):
    """只登记盘上已有的文件：不搬字节，但 sha256、探针、规格校验一个都不少。

    与 multipart 直传的唯一差别是文件位置：这里保留原路径（可能是外挂盘），
    直传则复制进 data/media/。销毁时按源文件路径删——所以登记前要确认这个路径
    是"系统可以删的"，别把采集机上的唯一副本登记进来又执行销毁。
    """
    typ, slot = _check_type_slot(body)
    raw_path = str(body.get('path')).strip().strip('"')
    path = os.path.abspath(raw_path)
    if not os.path.isfile(path):
        raise errors.ApiError('VALIDATION_FAILED', '文件不存在或不是普通文件：%s' % path, 'path')

    size = os.path.getsize(path)
    info = probes.probe(path, typ)
    ok, problems = probes.check_spec(typ, info, session)
    if not ok:
        raise errors.ApiError('SPEC_MISMATCH', '规格不符：' + '；'.join(problems), 'path',
                              {'problems': problems, 'probe': info})

    sha = util.sha256_file(path)
    dup = _by_sha(sha, sid)
    if dup:
        db.audit('media.duplicate', sid, 'admin', {'sha256': sha[:12], 'asset_id': dup['id']})
        out = _common.media_public(dup)
        out.update({'duplicate': True})
        return out

    _guard_slot(sid, slot, body.get('replace'))
    asset_id = _insert(sid, typ, slot, os.path.basename(path), path, size, sha,
                       info.get('duration_s') or (session['duration_min'] * 60
                                                  if typ in ('video', 'audio') else None),
                       info, 'ok')
    db.audit('media.register_local', sid, 'admin',
             {'asset_id': asset_id, 'type': typ, 'slot': slot, 'bytes': size,
              'sha256': sha[:12], 'in_place': True})
    out = _common.media_public(db.q1('SELECT * FROM media_assets WHERE id=?', (asset_id,)))
    out.update({'asset_id': asset_id, 'type': typ, 'slot': slot, 'duplicate': False})
    return out



def upload_multipart(sid, fields, filename, fileobj, content_length=0):
    session = _common.require_session(sid)
    body = {'type': fields.get('type'), 'slot': fields.get('slot')}
    typ, slot = _check_type_slot(body)

    dest_dir = os.path.join(config.MEDIA_DIR, sid)
    os.makedirs(dest_dir, exist_ok=True)
    safe_name = os.path.basename(filename or ('%s.bin' % slot))
    tmp_path = os.path.join(dest_dir, '.upload-%s' % util.new_id('tmp'))
    sha = _save(fileobj, tmp_path)

    size = os.path.getsize(tmp_path)
    info = probes.probe(tmp_path, typ, filename=safe_name)
    ok, problems = probes.check_spec(typ, info, session)

    dup = _by_sha(sha, sid)
    if dup:
        os.remove(tmp_path)
        db.audit('media.duplicate', sid, 'admin', {'sha256': sha[:12], 'asset_id': dup['id']})
        out = _common.media_public(dup)
        out['duplicate'] = True
        return out

    if not ok:
        os.remove(tmp_path)
        raise errors.ApiError('SPEC_MISMATCH', '规格不符：' + '；'.join(problems), 'file',
                              {'problems': problems, 'probe': info})

    # 同一 slot 重传视为更新：旧的那条软删，不能让两个 cam1 同时有效
    # （否则通道数会被算成 5/4，门禁结论直接失真）
    _guard_slot(sid, slot, True)

    final = os.path.join(dest_dir, '%s_%s' % (slot, safe_name))
    shutil.move(tmp_path, final)
    asset_id = _insert(sid, typ, slot, safe_name, final, size, sha,
                       info.get('duration_s') or (session['duration_min'] * 60
                                                  if typ in ('video', 'audio') else None),
                       info, 'ok')
    db.audit('media.upload', sid, 'admin',
             {'asset_id': asset_id, 'type': typ, 'slot': slot, 'bytes': size, 'sha256': sha[:12]})
    out = _common.media_public(db.q1('SELECT * FROM media_assets WHERE id=?', (asset_id,)))
    out.update({'asset_id': asset_id, 'type': typ, 'slot': slot, 'duplicate': False})
    return out


def _save(fileobj, path):
    import hashlib
    h = hashlib.sha256()
    total = 0
    with open(path, 'wb') as f:
        while True:
            chunk = fileobj.read(config.CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > config.MAX_UPLOAD_BYTES:
                f.close()
                os.remove(path)
                raise errors.ApiError('VALIDATION_FAILED',
                                      '超过 2 GiB 直传上限；大文件请在端侧就位后用 JSON 带 path 就地登记')
            h.update(chunk)
            f.write(chunk)
    return h.hexdigest()


def _owned_path(sid, path):
    """路径是否落在本场次的媒资目录内——只有系统自己拷进来的副本才允许顺手删盘。"""
    root = os.path.abspath(os.path.join(config.MEDIA_DIR, sid))
    p = os.path.abspath(path)
    try:
        return os.path.commonpath([root, p]) == root
    except ValueError:      # 跨盘符比较会抛 ValueError
        return False


def delete_asset(sid, asset_id, confirm, purge=None):
    """删除单条媒资（视频／音频／课件／目标），删完该 slot 立刻可以重新登记。

    与 delete_media 的分工：那条按 scope 批量销毁（整场清理），这条是逐条撤销登记。
    重复登记、传错文件、选错机位，都走这条。

    盘上文件默认只删**系统自有副本**（data/media/<sid>/ 下）；就地登记的外部文件
    只解除登记、不动原文件——那可能是采集机上的唯一一份，误删无法恢复。
    确实要连外部原文件一起删，显式带 purge=true。
    """
    session = _common.require_session(sid)
    if str(confirm).lower() not in ('true', '1', 'yes'):
        errors.fail('VALIDATION_FAILED', '删除媒资需带 confirm=true', 'confirm')

    row = db.q1('SELECT * FROM media_assets WHERE id=? AND session_id=?', (asset_id, sid))
    if not row:
        errors.not_found('媒资', asset_id)
    if row['deleted_at']:
        raise errors.ApiError('STATE_CONFLICT', '资产 %s 已删除' % asset_id, 'asset_id')

    path = row['path']
    freed = 0
    file_state = 'none'          # none = 仅登记、本来就没有字节
    if path and os.path.exists(path):
        if _owned_path(sid, path) or str(purge).lower() in ('true', '1', 'yes'):
            try:
                freed = os.path.getsize(path)
                os.remove(path)
                file_state = 'removed'
            except OSError:
                file_state = 'failed'
        else:
            file_state = 'kept'  # 外部就地登记的文件，系统不替用户删

    db.x('UPDATE media_assets SET deleted_at=? WHERE id=?', (util.iso(), asset_id))
    stage_before = session['stage']
    remaining = db.scalar('SELECT COUNT(*) FROM media_assets WHERE session_id=? AND deleted_at IS NULL',
                          (sid,)) or 0
    db.audit('media.delete_asset', sid, 'admin',
             {'asset_id': asset_id, 'type': row['type'], 'slot': row['slot'],
              'freed_bytes': freed, 'file': file_state, 'stage_before': stage_before})

    stale = stage_before != 'created'
    return {
        'deleted': [asset_id], 'type': row['type'], 'slot': row['slot'],
        'freed_bytes': freed, 'file': file_state, 'remaining': remaining,
        'stage': stage_before, 'stale': stale,
        'note': '观测与评价快照不随媒资删除；该场次已有处理结果，需重新预处理才会更新'
                if stale else '该 slot 已可重新登记',
    }


def delete_media(sid, scope, confirm):
    _common.require_session(sid)
    if str(confirm).lower() not in ('true', '1', 'yes'):
        errors.fail('VALIDATION_FAILED', '销毁媒资需带 confirm=true', 'confirm')
    if scope not in ('raw', 'derived', 'all'):
        errors.fail('VALIDATION_FAILED', 'scope 需为 raw／derived／all', 'scope')

    rows = _common.media_rows(sid)
    if scope == 'raw':
        targets = [r for r in rows if r['type'] in ('video', 'audio')]
    elif scope == 'all':
        targets = rows
    else:
        targets = []

    freed = 0
    deleted = []
    for r in targets:
        if r.get('path') and os.path.exists(r['path']):
            try:
                freed += os.path.getsize(r['path'])
                os.remove(r['path'])
            except OSError:
                pass
        db.x('UPDATE media_assets SET deleted_at=? WHERE id=?', (util.iso(), r['id']))
        deleted.append(r['id'])

    if scope in ('derived', 'all'):
        d = os.path.join(config.MEDIA_DIR, sid, 'derived')
        if os.path.isdir(d):
            for root, _dirs, files in os.walk(d):
                for f in files:
                    try:
                        freed += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            shutil.rmtree(d, ignore_errors=True)

    db.audit('media.delete', sid, 'admin', {'scope': scope, 'count': len(deleted), 'freed_bytes': freed})
    if scope == 'all':
        db.x("UPDATE sessions SET stage='created' WHERE id=?", (sid,))
    return {'deleted': deleted, 'freed_bytes': freed,
            'note': '观测与评价快照不随媒资删除，报告仍可复核'}
