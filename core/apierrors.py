# -*- coding: utf-8 -*-
"""星语 Starry · 企业级 API 错误治理（v13.2，纯标准库 / 三端同源）。

真实 GUI 测评暴露的问题（有截图与 mock 请求日志为证）：
  1. 启动 1.2s 后自动拉 /models，Key 失效即 HTTP 401，错误以 toast 一闪而过；
  2. `core/api.py::list_models` 直接抛 ``HTTP 401：<上游原始响应体>``，
     既没有中文可操作建议，也可能把上游敏感内容原样展示；
  3. 401 / 429 / 5xx / 超时一视同仁，没有分类、重试策略与退避；
  4. 用户事后无法查看「刚才到底错在哪」，排查只能靠猜。

本模块提供**唯一的错误语义层**：分类判定、可操作建议、重试策略、脱敏。
所有对外文本都经过 `redact()`，绝不输出 API Key / Bearer Token / 上游原始响应体。

设计约束：
  * 只用标准库，不依赖 requests / PyQt5，EXE / deb / Android 可同源分发；
  * 纯函数优先，`classify_*()` 永不抛异常（任何输入都返回合法结构）；
  * 返回普通 dict，便于 JSON 序列化（诊断面板 / 日志 / 上报）。
"""
import re

# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------
KIND_AUTH = "auth"                 # 401：Key 无效 / 未授权
KIND_FORBIDDEN = "forbidden"       # 403：无权限
KIND_QUOTA = "quota"               # 402：余额不足
KIND_RATE_LIMIT = "rate_limit"     # 429：限流
KIND_NOT_FOUND = "not_found"       # 404：地址 / 模型不存在
KIND_SERVER = "server"             # 5xx：服务端故障
KIND_NETWORK = "network"           # 连接失败 / 超时 / DNS
KIND_PARSE = "parse"               # 响应不是合法 JSON
KIND_CONFIG = "config"             # 本地配置缺失
KIND_UNKNOWN = "unknown"

KINDS = (KIND_AUTH, KIND_FORBIDDEN, KIND_QUOTA, KIND_RATE_LIMIT,
         KIND_NOT_FOUND, KIND_SERVER, KIND_NETWORK, KIND_PARSE,
         KIND_CONFIG, KIND_UNKNOWN)

# 每种分类的企业级处置策略
#   title       短标题（UI 一行展示）
#   advice      可操作建议（逐条，UI 逐行展示）
#   action      UI 应该提供的主操作
#   retryable   是否值得重试
#   backoff     基础退避秒数（配合 attempt 指数增长，上限由 MAX_BACKOFF 控制）
#   severity    info / warning / error
KIND_META = {
    KIND_AUTH: {
        "title": "API Key 无效或未授权（401）",
        "advice": [
            "打开「设置 → 服务商」，确认 API Key 与当前 Base URL 属于同一服务商。",
            "检查 Key 是否已过期、被轮换或复制时带入了多余空格。",
            "可改用「网页大模型」等免 Key 接入方式；离线功能不受影响。",
        ],
        "action": "open_settings", "retryable": False, "backoff": 0,
        "severity": "error",
    },
    KIND_FORBIDDEN: {
        "title": "没有访问权限（403）",
        "advice": [
            "确认账号是否已开通该模型 / 该接口权限。",
            "检查 Base URL 是否指向了需要额外授权的区域或专享端点。",
        ],
        "action": "open_settings", "retryable": False, "backoff": 0,
        "severity": "error",
    },
    KIND_QUOTA: {
        "title": "账户额度不足（402）",
        "advice": ["请充值或更换服务商 / 模型。", "可切换免费模型继续使用。"],
        "action": "open_settings", "retryable": False, "backoff": 0,
        "severity": "warning",
    },
    KIND_RATE_LIMIT: {
        "title": "请求过于频繁或额度用尽（429）",
        "advice": ["稍后重试，或降低自动刷新频率。", "可在设置中关闭「启动时自动刷新模型」。"],
        "action": "retry", "retryable": True, "backoff": 30,
        "severity": "warning",
    },
    KIND_NOT_FOUND: {
        "title": "接口或模型不存在（404）",
        "advice": ["核对 Base URL 是否以 /v1 结尾且路径正确。", "核对模型名是否已下线或改名。"],
        "action": "open_settings", "retryable": False, "backoff": 0,
        "severity": "error",
    },
    KIND_SERVER: {
        "title": "服务商暂时不可用（5xx）",
        "advice": ["这是服务端故障，稍后自动重试即可。", "持续失败时请查看服务商状态页。"],
        "action": "retry", "retryable": True, "backoff": 10,
        "severity": "warning",
    },
    KIND_NETWORK: {
        "title": "网络连接失败或超时",
        "advice": ["检查网络、代理与防火墙设置。", "确认 Base URL 可访问；离线功能不受影响。"],
        "action": "retry", "retryable": True, "backoff": 5,
        "severity": "warning",
    },
    KIND_PARSE: {
        "title": "服务商返回了非预期内容",
        "advice": ["确认 Base URL 指向的是 OpenAI 兼容接口，而不是网页登录页。"],
        "action": "open_settings", "retryable": False, "backoff": 0,
        "severity": "warning",
    },
    KIND_CONFIG: {
        "title": "本地配置不完整",
        "advice": ["打开设置填写 API Key 与 Base URL。", "不使用云端模型也可正常使用 Skills Hub 等离线功能。"],
        "action": "open_settings", "retryable": False, "backoff": 0,
        "severity": "info",
    },
    KIND_UNKNOWN: {
        "title": "请求未完成",
        "advice": ["打开「API 诊断」查看脱敏后的失败详情。"],
        "action": "open_diagnostics", "retryable": True, "backoff": 5,
        "severity": "warning",
    },
}

MAX_BACKOFF = 300                   # 退避上限（秒）
MAX_DETAIL = 160                    # 脱敏后保留的上游摘要长度

_REDACT_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"(?i)(sk-[A-Za-z0-9_\-]{6,})"), "sk-***"),
    (re.compile(r"(?i)(\"?(?:api[_-]?key|token|secret|authorization)\"?\s*[:=]\s*\"?)[^\"',\s}]+"),
     r"\1***"),
    (re.compile(r"(?i)([?&](?:key|token|api_key)=)[^&\s]+"), r"\1***"),
)


def redact(text, limit=MAX_DETAIL):
    """把任意上游文本转成**可安全展示**的脱敏摘要。

    绝不返回：完整响应体、Bearer Token、API Key、查询串里的密钥。
    任何异常都收敛为 "<无可用详情>"，不向调用方抛。
    """
    try:
        s = str(text or "").replace("\r", " ").replace("\n", " ").strip()
        for pat, repl in _REDACT_PATTERNS:
            s = pat.sub(repl, s)
        s = " ".join(s.split())
        if not s:
            return ""
        return s[:limit] + ("…" if len(s) > limit else "")
    except Exception:                                   # noqa: BLE001
        return "<无可用详情>"


def status_kind(status):
    """HTTP 状态码 → 分类；未知码归 UNKNOWN，永不抛异常。"""
    try:
        code = int(status)
    except (TypeError, ValueError):
        return KIND_UNKNOWN
    if code == 401:
        return KIND_AUTH
    if code == 402:
        return KIND_QUOTA
    if code == 403:
        return KIND_FORBIDDEN
    if code == 404:
        return KIND_NOT_FOUND
    if code == 429:
        return KIND_RATE_LIMIT
    if 500 <= code <= 599:
        return KIND_SERVER
    if 400 <= code <= 499:
        return KIND_UNKNOWN
    return KIND_UNKNOWN


def _build(kind, status=None, detail="", operation="", retry_after=None):
    meta = KIND_META.get(kind, KIND_META[KIND_UNKNOWN])
    return {
        "kind": kind,
        "status": status,
        "title": meta["title"],
        "advice": list(meta["advice"]),
        "action": meta["action"],
        "retryable": bool(meta["retryable"]),
        "backoff": int(meta["backoff"]),
        "severity": meta["severity"],
        "operation": str(operation or "api"),
        "detail": redact(detail),
        "retry_after": retry_after,
    }


def from_http(status, upstream_text="", operation="", retry_after=None):
    """由 HTTP 状态码构造结构化错误（上游原文只作脱敏摘要，不直接展示）。"""
    kind = status_kind(status)
    return _build(kind, status=status, detail=upstream_text,
                  operation=operation, retry_after=retry_after)


def from_exception(exc, operation=""):
    """由异常对象构造结构化错误；识别超时 / 连接 / 解析三类。"""
    text = redact(exc)
    low = text.lower()
    cls = type(exc).__name__.lower() if exc is not None else ""
    if "timeout" in low or "timed out" in low or "timeout" in cls:
        kind = KIND_NETWORK
    elif ("json" in low or "decode" in low or "parse" in low
          or "json" in cls):
        kind = KIND_PARSE
    elif ("connect" in low or "connection" in low or "dns" in low
          or "ssl" in low or "proxy" in low or "network" in low
          or "refused" in low or "10061" in low):
        kind = KIND_NETWORK
    else:
        kind = KIND_UNKNOWN
    return _build(kind, detail=text, operation=operation)


def config_error(message, operation=""):
    """本地配置缺失（未填 Key / Base URL 等）。"""
    return _build(KIND_CONFIG, detail=message, operation=operation)


def backoff_seconds(err, attempt=1):
    """指数退避秒数；不可重试的错误返回 0。"""
    if not isinstance(err, dict) or not err.get("retryable"):
        return 0
    base = int(err.get("backoff") or 0)
    try:
        n = max(1, int(attempt))
    except (TypeError, ValueError):
        n = 1
    return min(MAX_BACKOFF, base * (2 ** min(n - 1, 6)))


def one_line(err):
    """给 toast / 状态条用的一行文本（已脱敏、可操作）。"""
    if not isinstance(err, dict):
        return "请求未完成，请打开「API 诊断」查看详情。"
    advice = err.get("advice") or []
    tail = advice[0] if advice else "请打开「API 诊断」查看详情。"
    return "%s · %s" % (err.get("title", "请求未完成"), tail)


def full_text(err):
    """给对话框 / 诊断面板用的多行可操作文本（已脱敏）。"""
    if not isinstance(err, dict):
        return "请求未完成。\n请打开「API 诊断」查看详情。"
    lines = ["[%s] %s" % (err.get("kind", KIND_UNKNOWN),
                          err.get("title", "请求未完成")),
             "操作：%s" % err.get("operation", "api")]
    if err.get("status"):
        lines.append("HTTP 状态：%s" % err["status"])
    if err.get("detail"):
        lines.append("上游摘要（已脱敏）：%s" % err["detail"])
    lines.append("")
    lines.append("建议：")
    for i, item in enumerate(err.get("advice") or [], 1):
        lines.append("  %d. %s" % (i, item))
    lines.append("")
    lines.append("可重试：%s" % ("是（退避 %d 秒）" % backoff_seconds(err)
                                 if err.get("retryable") else "否（需先修改配置）"))
    return "\n".join(lines)


__all__ = [
    "KINDS", "KIND_AUTH", "KIND_FORBIDDEN", "KIND_QUOTA", "KIND_RATE_LIMIT",
    "KIND_NOT_FOUND", "KIND_SERVER", "KIND_NETWORK", "KIND_PARSE",
    "KIND_CONFIG", "KIND_UNKNOWN", "KIND_META", "MAX_BACKOFF",
    "redact", "status_kind", "from_http", "from_exception", "config_error",
    "backoff_seconds", "one_line", "full_text",
]
