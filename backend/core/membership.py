"""core/membership.py — 量尺计分

21 条指标的分项分只有一条算法：按 indicator_config 的梯形（岭形）隶属函数把原始量 μ 映射到 [0,1]，
再乘 100 得百分制分项分 s = 100μ。

四类取向：
  inc       递增型        μ = clip((x−a)/(b−a))
  reverse   反向型（越低越好） μ = 1 − clip((x−a)/(b−a))
  interval  区间型（梯形）  a–b 升、b–c 满、c–d 降，区间外为 0
  level     等级型／combo  原始量已是 0–1 的合成等级，直接 clip

**这个函数是评价的唯一出口**：客户端提交 raw_value，服务端算分；任何"给个分"的路径都不允许存在。
前端 mock.js 的 scale() 是它的同构 JS 版，两边改一处必须同时改另一处，否则界面与接口会打架。
"""


def clip01(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else float(v))


def mu(ind, raw):
    """返回隶属度 μ ∈ [0,1]；无法计算时返回 None（调用方据此记空值）"""
    if raw is None:
        return None
    direction = ind['direction']
    a, b, c, d = ind.get('a'), ind.get('b'), ind.get('c'), ind.get('d')

    if direction in ('level', 'combo'):
        return clip01(float(raw))

    if direction == 'inc':
        if a is None or b is None or float(b) == float(a):
            return None
        return clip01((float(raw) - a) / (b - a))

    if direction == 'reverse':
        if a is None or b is None or float(b) == float(a):
            return None
        return 1.0 - clip01((float(raw) - a) / (b - a))

    if direction == 'interval':
        if a is None or b is None or c is None or d is None:
            return None
        v = float(raw)
        if v < a or v > d:
            return 0.0
        if v < b:
            return clip01((v - a) / (b - a)) if b != a else 1.0
        if v <= c:
            return 1.0
        return clip01((d - v) / (d - c)) if d != c else 0.0

    return None


def score(ind, raw):
    """分项分 s = 100μ，保留一位小数；不计分项（C1／VC3）与空值一律返回 None"""
    if not ind.get('scored', True):
        return None
    m = mu(ind, raw)
    if m is None:
        return None
    return round(m * 1000) / 10


def band(ind, raw):
    """给报告用的可读解释：原始量落在量尺的哪一段"""
    if raw is None:
        return None
    direction = ind['direction']
    a, b, c, d = ind.get('a'), ind.get('b'), ind.get('c'), ind.get('d')
    v = float(raw)
    if direction == 'inc':
        if v < a:
            return '低于 a=%.4g，折 0 分' % a
        if v >= b:
            return '达到或超过 b=%.4g，折满分' % b
        return '在 a=%.4g 与 b=%.4g 之间线性折算' % (a, b)
    if direction == 'reverse':
        if v <= a:
            return '不高于 a=%.4g，折满分' % a
        if v >= b:
            return '达到或超过 b=%.4g，折 0 分' % b
        return '在 a=%.4g 与 b=%.4g 之间反向折算' % (a, b)
    if direction == 'interval':
        if v < a or v > d:
            return '落在阈值区间 [%.4g, %.4g] 之外，折 0 分' % (a, d)
        if b <= v <= c:
            return '落在满分区 [%.4g, %.4g]' % (b, c)
        return '落在过渡区，按梯形边折算'
    return '等级量，直接折算'


def default_confidence(s):
    """没有模型置信度时的兜底：分项分越高置信度略高。仅用于演示数据与补录，
    真实场景必须由模型给出 confidence，缺就是缺。"""
    if s is None:
        return None
    return round(0.72 + (s / 100.0) * 0.22, 2)
