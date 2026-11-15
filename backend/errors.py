"""errors.py — 统一错误

错误码与 HTTP 状态码的映射严格照 docs/接口约定.md，前端按 code 分支，不解析 message。
"""
import uuid

# code -> (HTTP status, 默认中文说明)
CODES = {
    'VALIDATION_FAILED':   (400, '字段校验失败'),
    'CONSENT_REQUIRED':    (400, '未确认知情同意，场次不得入库'),
    'PII_DETECTED':        (400, '文本含手机号／身份证／邮箱等直接标识'),
    'UNAUTHORIZED':        (401, '缺少或无效的访问令牌'),
    'FORBIDDEN':           (403, '无权访问该对象'),
    'NOT_FOUND':           (404, '对象不存在'),
    'METHOD_NOT_ALLOWED':  (405, '方法不允许'),
    'GATE_NOT_PASSED':     (409, '门禁未通过，相关分项不得计分'),
    'MISSING_GOALS':       (409, '缺课程目标文本，目标匹配域不可计算'),
    'TASK_CONFLICT':       (409, '同一场次已有运行中的任务'),
    'STATE_CONFLICT':      (409, '当前状态不允许该操作'),
    'SPEC_MISMATCH':       (422, '媒资规格不符'),
    'QUOTA_EXCEEDED':      (429, '模型调用配额耗尽'),
    'INTERNAL':            (500, '服务内部错误'),
    'NOT_IMPLEMENTED':     (501, '该能力在本版本留空，接口已就位'),
    'PROVIDER_UNAVAILABLE': (503, '模型服务不可用'),
}


class ApiError(Exception):
    def __init__(self, code, message=None, field=None, detail=None):
        status, default = CODES.get(code, (500, '服务内部错误'))
        self.code = code
        self.status = status
        self.message = message or default
        self.field = field
        self.detail = detail
        super(ApiError, self).__init__(self.message)

    def payload(self, trace_id=None):
        err = {
            'code': self.code,
            'message': self.message,
            'trace_id': trace_id or uuid.uuid4().hex[:8],
        }
        if self.field:
            err['field'] = self.field
        if self.detail:
            err['detail'] = self.detail
        return {'error': err}


def fail(code, message=None, field=None, detail=None):
    raise ApiError(code, message, field, detail)


def not_found(what, ident=None):
    msg = '%s不存在' % what
    if ident:
        msg = '%s %s 不存在' % (what, ident)
    raise ApiError('NOT_FOUND', msg)
