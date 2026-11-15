"""core/providers.py — 模型网关适配层

一个出口，五类能力。所有调用都走 call()，因此三件事不可能被绕过：
  1. 每次调用写 ai_calls（含 model_version / prompt_version，缺一即 400）
  2. 同一 input_hash 在 TTL 内命中缓存则不重复计费
  3. 失败重试 3 次后仍失败 → 503 PROVIDER_UNAVAILABLE，调用方按"该项记空值"处理

适配器只有两个真实实现 + 一个占位：

  stub  默认。不联网，按 input_hash 派生确定性结果，响应里 simulated=true。
        它存在的意义是让整条链路（网关→记账→观测→计分→报告）能够端到端跑通并自测，
        绝不是"假装模型已经能判课"。界面上但凡出现桩结果，报告里必须写"模拟数据"。
  openai  OpenAI 兼容端点。llm / embed 两类能力已接（chat/completions、embeddings）；
        asr / ocr / vlm 因各家协议差异过大，留空返回 501，接某一家时在这里补一个方法即可。
  none  不配任何 provider：调用直接 503，用来验证"降级后系统仍然可用"。

留空的地方都抛 NOT_IMPLEMENTED 并在 message 里写明要补什么，而不是偷偷回一个假结果。
"""
import hashlib
import json
import random
import time
import urllib.error
import urllib.request

import config
import db
import errors
import util

CAPABILITIES = ('asr', 'ocr', 'embed', 'llm', 'vlm')


def input_hash(capability, payload, model_version, prompt_version):
    raw = util.dumps({'c': capability, 'p': payload, 'm': model_version, 'v': prompt_version})
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def estimate_cost(capability, usage):
    p = config.PRICING.get(capability, {})
    if capability == 'asr':
        return round(p.get('per_minute', 0) * (usage.get('audio_minutes') or 0), 4)
    if capability == 'ocr':
        return round(p.get('per_page', 0) * (usage.get('pages') or 0), 4)
    if capability == 'embed':
        return round(p.get('per_1k_tokens', 0) * (usage.get('tokens_in') or 0) / 1000.0, 4)
    if capability == 'llm':
        return round(p.get('per_1k_in', 0) * (usage.get('tokens_in') or 0) / 1000.0
                     + p.get('per_1k_out', 0) * (usage.get('tokens_out') or 0) / 1000.0, 4)
    if capability == 'vlm':
        return round(p.get('per_image', 0) * (usage.get('images') or 0), 4)
    return 0.0


# ---------------------------------------------------------------- 桩

class StubProvider(object):
    """确定性占位：同一输入永远同一输出，便于回归测试对账。"""

    name = 'stub'

    def health(self):
        return {c: 'degraded' for c in CAPABILITIES}

    def call(self, capability, payload, model_version, prompt_version):
        seed = int(input_hash(capability, payload, model_version, prompt_version)[:12], 16)
        rnd = random.Random(seed)
        t0 = time.time()

        if capability == 'asr':
            minutes = float(payload.get('minutes') or 1.0)
            n = max(1, int(minutes / 8))
            segs = []
            for i in range(min(n, 12)):
                start = round(i * 8.0 + rnd.random() * 0.4, 1)
                segs.append({'start': start, 'end': round(start + 4.5, 1),
                             'text': '（桩转写片段 %d）' % (i + 1),
                             'speaker': 'teacher' if i % 3 else 'student',
                             'conf': round(0.80 + rnd.random() * 0.15, 2)})
            data = {'segments': segs, 'simulated': True}
            usage = {'audio_minutes': minutes, 'tokens_in': 0, 'tokens_out': 0}

        elif capability == 'ocr':
            pages = int(payload.get('pages') or len(payload.get('image_urls') or [1]))
            data = {'pages': [{'no': i + 1,
                               'blocks': [{'text': '（桩 OCR 文本块）', 'bbox': [120, 340, 860, 90],
                                           'conf': 0.9}]} for i in range(min(pages, 8))],
                    'simulated': True}
            usage = {'pages': pages, 'tokens_in': 0, 'tokens_out': 0}

        elif capability == 'embed':
            texts = payload.get('texts') or ['(empty)']
            dim = int(payload.get('dim') or 1024)
            vec = [0.0] * dim
            for i in range(min(dim, 16)):
                vec[i] = round(rnd.uniform(-0.3, 0.3), 4)
            data = {'vectors': [vec for _ in texts], 'dim': dim, 'simulated': True}
            usage = {'tokens_in': sum(len(t) for t in texts), 'tokens_out': 0}

        elif capability == 'llm':
            slices = payload.get('slices') or []
            code = payload.get('indicator') or 'A1'
            data = {'items': [{'code': code,
                               'value': round(rnd.uniform(0.45, 0.9), 2),
                               'confidence': round(rnd.uniform(0.65, 0.9), 2),
                               'evidence_t': float((slices[0] or {}).get('t0', 0)) if slices else 0.0,
                               'reason': '桩判定：未接入真实模型，此条不可用于评价'}],
                    'simulated': True}
            usage = {'tokens_in': sum(len((s or {}).get('text', '')) for s in slices) or 100,
                     'tokens_out': 60}

        elif capability == 'vlm':
            frames = payload.get('frame_urls') or []
            data = {'present': int(rnd.uniform(20, 45)),
                    'facing': round(rnd.uniform(0.4, 0.8), 2),
                    'confidence': round(rnd.uniform(0.6, 0.85), 2),
                    'note': '桩检测：未接入真实模型', 'simulated': True}
            usage = {'images': len(frames) or 8, 'tokens_in': 0, 'tokens_out': 0}

        else:
            raise errors.ApiError('VALIDATION_FAILED', '未知能力 %s' % capability, 'capability')

        data['model_version'] = model_version
        data['prompt_version'] = prompt_version
        return data, usage, int((time.time() - t0) * 1000) + 1, 0.11


# ---------------------------------------------------------------- OpenAI 兼容

class OpenAIProvider(object):
    """只实现协议稳定的两类：chat/completions 与 embeddings。
    其余三类留空——宁可 501，也不猜别家的字段。"""

    name = 'openai'

    def __init__(self, base_url, api_key, model_names):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.models = model_names

    def health(self):
        base = {c: 'unavailable' for c in CAPABILITIES}
        base['llm'] = 'ok'
        base['embed'] = 'ok'
        return base

    def _post(self, path, body):
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'Authorization': 'Bearer %s' % self.api_key},
            method='POST')
        try:
            with urllib.request.urlopen(req, timeout=config.MODEL_TIMEOUT) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:300]
            raise errors.ApiError('PROVIDER_UNAVAILABLE', '模型服务返回 %d：%s' % (exc.code, detail))
        except Exception as exc:
            raise errors.ApiError('PROVIDER_UNAVAILABLE', '调用模型服务失败：%s' % exc)

    def call(self, capability, payload, model_version, prompt_version):
        t0 = time.time()
        if capability == 'llm':
            body = {
                'model': model_version,
                'temperature': 0,
                'response_format': {'type': 'json_object'},
                'messages': [
                    {'role': 'system', 'content': payload.get('system') or
                     '你是课堂话语分析器。只输出 JSON，字段严格按 schema，不要解释。'},
                    {'role': 'user', 'content': json.dumps(
                        {'indicator': payload.get('indicator'),
                         'schema': payload.get('schema'),
                         'slices': payload.get('slices')}, ensure_ascii=False)},
                ],
            }
            resp = self._post('/chat/completions', body)
            text = (resp.get('choices') or [{}])[0].get('message', {}).get('content', '{}')
            try:
                data = json.loads(text)
            except ValueError:
                raise errors.ApiError('PROVIDER_UNAVAILABLE', '模型未按 JSON 返回，已丢弃该次结果')
            data.setdefault('model_version', model_version)
            data.setdefault('prompt_version', prompt_version)
            usage = resp.get('usage') or {}
            u = {'tokens_in': usage.get('prompt_tokens', 0), 'tokens_out': usage.get('completion_tokens', 0)}
            return data, u, int((time.time() - t0) * 1000), 0

        if capability == 'embed':
            resp = self._post('/embeddings', {'model': model_version, 'input': payload.get('texts') or []})
            vecs = [d.get('embedding') for d in resp.get('data') or []]
            data = {'vectors': vecs, 'dim': len(vecs[0]) if vecs else 0,
                    'model_version': model_version, 'prompt_version': prompt_version}
            usage = {'tokens_in': (resp.get('usage') or {}).get('prompt_tokens', 0), 'tokens_out': 0}
            return data, usage, int((time.time() - t0) * 1000), 0

        raise errors.ApiError(
            'NOT_IMPLEMENTED',
            'provider=openai 尚未实现 %s：各家 ASR／OCR／VLM 协议差异大，'
            '接具体厂商时在 core/providers.py 补一个方法即可，接口与记账逻辑不需改。' % capability)


class NoneProvider(object):
    name = 'none'

    def health(self):
        return {c: 'unavailable' for c in CAPABILITIES}

    def call(self, capability, payload, model_version, prompt_version):
        raise errors.ApiError('PROVIDER_UNAVAILABLE',
                              '未配置模型服务（MODEL_PROVIDER=none），%s 不可用' % capability)


def get_provider():
    if config.MODEL_PROVIDER == 'openai' and config.MODEL_BASE_URL and config.MODEL_API_KEY:
        return OpenAIProvider(config.MODEL_BASE_URL, config.MODEL_API_KEY, config.MODEL_NAMES)
    if config.MODEL_PROVIDER == 'none':
        return NoneProvider()
    return StubProvider()


# ---------------------------------------------------------------- 统一入口

def call(capability, payload, session_id=None, model_version=None, prompt_version=None,
         use_cache=True):
    if capability not in CAPABILITIES:
        raise errors.ApiError('VALIDATION_FAILED', 'capability 需为 %s 之一' % '/'.join(CAPABILITIES),
                              'capability')
    model_version = model_version or config.MODEL_NAMES.get(capability)
    prompt_version = prompt_version or payload.get('prompt_version')
    if not model_version:
        raise errors.ApiError('VALIDATION_FAILED', 'model_version 必填', 'model_version')
    if not prompt_version:
        raise errors.ApiError('VALIDATION_FAILED', 'prompt_version 必填', 'prompt_version')

    ih = input_hash(capability, payload, model_version, prompt_version)

    if use_cache:
        row = db.q1("""SELECT * FROM ai_calls
                       WHERE input_hash = ? AND capability = ? AND model_version = ? AND prompt_version = ?
                       ORDER BY at DESC LIMIT 1""",
                    (ih, capability, model_version, prompt_version))
        if row and row.get('response_json'):
            fresh = _within_ttl(row['at'])
            if fresh:
                data = util.loads(row['response_json'], {})
                db.audit('ai.cache_hit', session_id, 'system', {'capability': capability, 'input_hash': ih[:12]})
                return {'data': data, 'cached': True, 'call_id': row['id'],
                        'cost': 0.0, 'simulated': bool(row.get('simulated'))}

    provider = get_provider()
    last_err = None
    for attempt in range(config.MODEL_RETRY):
        try:
            data, usage, latency, extra_cost = provider.call(capability, payload, model_version, prompt_version)
            break
        except errors.ApiError as exc:
            last_err = exc
            if exc.code == 'NOT_IMPLEMENTED':
                raise
            if attempt == config.MODEL_RETRY - 1:
                raise
            time.sleep(0.15 * (2 ** attempt))
    else:
        raise last_err or errors.ApiError('PROVIDER_UNAVAILABLE')

    cost = round(estimate_cost(capability, usage) + extra_cost, 4)
    call_id = util.new_id('A')
    db.x("""INSERT INTO ai_calls (id, session_id, capability, provider, model_version, prompt_version,
                                 input_hash, tokens_in, tokens_out, latency_ms, cost, cached, simulated,
                                 response_json, at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (call_id, session_id, capability, provider.name, model_version, prompt_version, ih,
          usage.get('tokens_in', 0), usage.get('tokens_out', 0), latency, cost, 0,
          1 if data.get('simulated') else 0, util.dumps(data), util.iso()))

    return {'data': data, 'cached': False, 'call_id': call_id, 'cost': cost,
            'simulated': bool(data.get('simulated'))}


def _within_ttl(at):
    try:
        import datetime
        t = datetime.datetime.fromisoformat(at)
        return (util.now() - t).days <= config.CACHE_TTL_DAYS
    except (ValueError, TypeError):
        return False


def health():
    p = get_provider()
    return p.health()
