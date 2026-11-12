# -*- coding: utf-8 -*-
"""模型能力矩阵 / 自动路由 / 失败回退（v13.4 · 完善大模型能力）。

借鉴 AnythingLLM 的 Dynamic Model Routing：不再让用户手动在几十个模型里挑，
而是根据**这一轮请求的特征**（要不要看图、要不要调工具、要不要深度思考、
上下文有多长）自动选出最合适的模型；主模型失败时给出可执行的回退链。

纯逻辑、零依赖、零联网：能力判断复用 ``core.models`` 的既有规则，
能力矩阵是「尽力而为的启发式」，会明确标注置信度，不伪装成官方参数。
"""
from core import models as mr

# 已知不支持 function calling 的模型（避免把工具请求路由过去白跑一趟）
_TOOLS_UNSUPPORTED_HINTS = ("deepseek-reasoner", "o1-mini", "o1-preview",
                            "qwq", "deepseek-r1-distill")
# 长上下文能力（按模型名启发式，单位 token）
_CONTEXT_HINTS = (
    ("qwen-long", 10_000_000),
    ("glm-4-long", 1_000_000),
    ("gemini-1.5", 1_000_000),
    ("gemini-2", 1_000_000),
    ("128k", 131_072), ("gpt-4o", 128_000), ("claude-3", 200_000),
    ("qwen2.5", 131_072), ("glm-4", 128_000), ("deepseek", 64_000),
)
_DEFAULT_CONTEXT = 32_768
_DEFAULT_MAX_OUTPUT = 4_096


def capabilities(name, provider=None):
    """返回某模型的能力矩阵（启发式，confidence 字段说明其性质）。"""
    low = (name or "").lower()
    reasoning = mr.is_reasoning_model(name, provider)
    vision = mr.is_vision_model(name, provider)
    free = mr.is_free_model(name, provider)
    tools = not any(h in low for h in _TOOLS_UNSUPPORTED_HINTS)
    ctx = _DEFAULT_CONTEXT
    for hint, value in _CONTEXT_HINTS:
        if hint in low:
            ctx = value
            break
    return {
        "model": name,
        "provider": provider or "",
        "tools": tools,
        "vision": vision,
        "reasoning": reasoning,
        "json_mode": tools,          # 结构化输出通常需要 function calling 支持
        "streaming": True,
        "free": free,
        "context_window": ctx,
        "max_output": 8_192 if reasoning else _DEFAULT_MAX_OUTPUT,
        "confidence": "heuristic",  # 诚实标注：模型名推断，非官方 API 参数
    }


def estimate_tokens(messages):
    """粗估一段对话的 token 数（中文按字、其余按 4 字符 ≈ 1 token）。"""
    parts = []
    for m in messages or []:
        if isinstance(m, dict):
            parts.append(str(m.get("content") or ""))
        else:
            parts.append(str(m))
    text = "\n".join(parts)
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    rest = len(text) - cjk
    return int(cjk + rest / 4.0) + len(messages or []) * 4


def describe_request(query="", messages=None, has_images=False,
                     need_tools=False, deep_thinking=False):
    """把一轮请求归一化为特征字典（供路由与 CLI 共用）。"""
    return {
        "query": query or "",
        "has_images": bool(has_images),
        "need_tools": bool(need_tools),
        "deep_thinking": bool(deep_thinking),
        "context_tokens": estimate_tokens(messages or ([{"content": query}]
                                                       if query else [])),
    }


def _score(name, provider, req, current, prefer_free):
    cap = capabilities(name, provider)
    reasons = []
    score = 100.0
    if req.get("need_tools") and not cap["tools"]:
        return -1000.0, ["不支持工具调用"], cap
    if req.get("has_images") and not cap["vision"]:
        return -1000.0, ["不支持图片理解"], cap
    if req.get("context_tokens", 0) > cap["context_window"]:
        return -1000.0, ["上下文超出窗口"], cap
    if req.get("deep_thinking"):
        if cap["reasoning"]:
            score += 30
            reasons.append("推理模型匹配深度思考")
        else:
            score -= 8
    elif cap["reasoning"]:
        score -= 5
        reasons.append("普通对话无需推理模型（更慢更贵）")
    if req.get("need_tools") and cap["tools"]:
        score += 10
        reasons.append("支持工具调用")
    if req.get("has_images") and cap["vision"]:
        score += 25
        reasons.append("支持图片理解")
    if cap["free"] and prefer_free:
        score += 8
        reasons.append("免费模型")
    if current and name == current:
        score += 6
        reasons.append("保持当前模型（避免频繁切换）")
    if req.get("context_tokens", 0) > cap["context_window"] * 0.8:
        score -= 10
        reasons.append("上下文接近窗口上限")
    if not reasons:
        reasons.append("通用能力匹配")
    return score, reasons, cap


def route_model(models, request, provider=None, current=None,
                prefer_free=True):
    """按本轮请求特征挑模型。

    返回 {ok, model, score, reasons, capability, alternatives, request}。
    没有任何可用模型时 ok=False 且 model 回落到 current，绝不强行乱切。
    """
    req = dict(request or {})
    names = [m for m in (models or []) if m]
    ranked = []
    for name in names:
        sc, why, cap = _score(name, provider, req, current, prefer_free)
        ranked.append({"model": name, "score": round(sc, 2),
                       "reasons": why, "capability": cap})
    ranked.sort(key=lambda x: (-x["score"], x["model"]))
    usable = [r for r in ranked if r["score"] > -1000]
    if not usable:
        return {"ok": False, "model": current or "", "score": 0,
                "reasons": ["当前模型列表里没有能满足该请求特征（工具/图片/上下文）的模型"],
                "capability": {},
                "alternatives": [r["model"] for r in ranked[:5]],
                "request": req}
    best = usable[0]
    return {
        "ok": True,
        "model": best["model"],
        "score": best["score"],
        "reasons": best["reasons"],
        "capability": best["capability"],
        "alternatives": [r["model"] for r in usable[1:6]],
        "request": req,
    }


def fallback_chain(models, primary, request, provider=None, limit=3):
    """主模型失败时的候选顺序（跳过主模型，优先同能力可替代项）。"""
    route = route_model([m for m in (models or []) if m != primary],
                        request, provider=provider)
    out = []
    if route["ok"]:
        out.append(route["model"])
        out.extend(route.get("alternatives") or [])
    seen, result = set(), []
    for m in out:
        if m and m != primary and m not in seen:
            seen.add(m)
            result.append(m)
        if len(result) >= max(1, int(limit)):
            break
    return result


def capability_table(models, provider=None):
    """能力矩阵（设置页 / CLI 用）。"""
    return [capabilities(m, provider) for m in (models or []) if m]


def format_capabilities(caps):
    """能力矩阵纯文本。"""
    if not caps:
        return "没有可用模型。"
    lines = ["模型能力矩阵（按模型名启发式推断，非官方参数）：",
             "  %-34s %-6s %-6s %-6s %-6s %s" % (
                 "模型", "工具", "视觉", "推理", "免费", "上下文")]
    for c in caps:
        lines.append("  %-34s %-6s %-6s %-6s %-6s %s" % (
            (c["model"] or "")[:34],
            "✓" if c["tools"] else "✗",
            "✓" if c["vision"] else "✗",
            "✓" if c["reasoning"] else "✗",
            "✓" if c["free"] else "✗",
            c["context_window"]))
    return "\n".join(lines)


def format_route(route):
    """路由建议纯文本。"""
    r = route or {}
    if not r.get("ok"):
        return "⚠️ %s" % "；".join(r.get("reasons") or ["无法选模型"])
    lines = ["🧠 推荐模型：%s（匹配分 %s）" % (r["model"], r.get("score", 0))]
    for why in r.get("reasons") or []:
        lines.append("   · %s" % why)
    cap = r.get("capability") or {}
    if cap:
        lines.append("   上下文窗口：%s tokens · 最大输出：%s" % (
            cap.get("context_window"), cap.get("max_output")))
    if r.get("alternatives"):
        lines.append("   回退链：%s" % " → ".join(r["alternatives"][:3]))
    lines.append("   注：能力由模型名启发式推断，实际支持情况以服务商为准。")
    return "\n".join(lines)
