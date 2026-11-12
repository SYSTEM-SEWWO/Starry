# -*- coding: utf-8 -*-
"""工具按需选择（v13.3）。

借鉴 AnythingLLM「Intelligent Skill Selection」：让模型可以拥有无限多的
工具，但每次请求只把与本轮问题相关的少数工具描述放进提示词，官方宣称最高
可省约 80% 的工具 token。工具越多，收益越明显（尤其是接了一堆 MCP 服务器时）。

本模块是纯逻辑层，接受三种常见形态：
  1. OpenAI tools 数组元素 {"type":"function","function":{...}}
  2. 简单字典 {"name": ..., "description": ..., "parameters": ...}
  3. core.agent.tools.ToolSpec 对象（有 .name/.description/.parameters）

调用方完全向后兼容：不传 query 时 select_tools 原样返回全部工具。
"""
import json
import re

_WORD_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")

# 名称命中权重 > 描述命中；参数名也算弱信号（例如 query/path/url）
_W_NAME = 6.0
_W_DESC = 2.0
_W_PARAM = 0.8
_W_EXACT = 10.0


def tokenize(text):
    s = (text or "").lower()
    parts = _WORD_RE.findall(s)
    out = list(parts)
    for i in range(len(parts) - 1):
        a, b = parts[i], parts[i + 1]
        if "\u4e00" <= a <= "\u9fff" and "\u4e00" <= b <= "\u9fff":
            out.append(a + b)
    return out


def _parts(item):
    """统一取出 (name, description, parameters)。"""
    if item is None:
        return "", "", {}
    if isinstance(item, dict):
        fn = item.get("function") if item.get("type") == "function" else item
        fn = fn if isinstance(fn, dict) else {}
        name = fn.get("name") or item.get("name") or ""
        desc = fn.get("description") or item.get("description") or ""
        params = fn.get("parameters") or item.get("parameters") or {}
    else:
        name = getattr(item, "name", "") or ""
        desc = getattr(item, "description", "") or ""
        params = getattr(item, "parameters", {}) or {}
    return str(name), str(desc), params or {}


def _param_text(params):
    try:
        if isinstance(params, dict):
            props = params.get("properties") or {}
            return " ".join(str(k) + " " + str((v or {}).get("description", ""))
                            for k, v in props.items())
        return str(params)
    except Exception:                                   # noqa: BLE001
        return ""


def tool_score(item, query, tokens=None, qlow=None):
    """单个工具与问题的相关性分数（0 表示完全无关）。"""
    name, desc, params = _parts(item)
    q = (query or "").strip().lower()
    if not q:
        return 0.0
    toks = tokens if tokens is not None else tokenize(q)
    qlow = q if qlow is None else qlow
    if not toks:
        return 0.0
    name_l, desc_l = name.lower(), desc.lower()
    param_l = _param_text(params).lower()
    score = 0.0
    for t in set(toks):
        # 中文单字（「的」「文」「字」）噪声大，降权；二元组 / 英文词才是主信号
        w = 0.25 if (len(t) == 1 and "\u4e00" <= t <= "\u9fff") else 1.0
        if t in name_l:
            score += _W_NAME * (2.0 if len(t) > 1 else 1.0) * w
        if t in desc_l:
            score += _W_DESC * w
        if t in param_l:
            score += _W_PARAM * w
    if qlow and (qlow in name_l or qlow in desc_l):
        score += _W_EXACT
    # 工具名里以下划线/点分隔的单词整体命中再加权（read_file ↔ 读文件场景）
    for seg in re.split(r"[_\-.\s]+", name_l):
        if seg and seg in toks:
            score += _W_NAME * 0.5
    return round(score, 4)


def estimate_tokens(obj):
    """粗估 JSON 文本的 token 数：中文按字、其余按 4 字符 ≈ 1 token。"""
    try:
        text = obj if isinstance(obj, str) else json.dumps(
            obj, ensure_ascii=False, default=str)
    except Exception:                                   # noqa: BLE001
        text = str(obj)
    if not text:
        return 0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    rest = len(text) - cjk
    return int(cjk + rest / 4.0) + 1


def select_tools(tools, query=None, top_k=8, min_score=0.0,
                 always_include=None, enabled=None):
    """按问题筛选工具。

    返回 (selected, report)。selected 保持调用方传入的元素原对象，
    report 含 total / kept / dropped / tokens_before / tokens_after /
    saved_tokens / saved_pct，便于 UI 展示「本次省了多少」。

    - query 为空 或 top_k <= 0 或 top_k >= 工具数 → 不裁剪，原样返回；
    - always_include 里的工具名强制保留；
    - 未命中任何工具（min_score 过滤后为空）时自动回退到「分数最高的 1 个」，
      避免模型一个工具都拿不到。
    """
    items = list(tools or [])
    total = len(items)
    if enabled is not None:
        items = [t for t in items if _parts(t)[0] in enabled]
    before = estimate_tokens(items)
    if not query or not str(query).strip() or not items:
        return items, _report(total, len(items), before,
                              estimate_tokens(items), skipped=True)
    k = int(top_k or 0)
    if k <= 0 or k >= len(items):
        return items, _report(total, len(items), before, before, skipped=True)

    qlow = str(query).strip().lower()
    toks = tokenize(qlow)
    forced = set(always_include or [])
    scored = [(tool_score(t, qlow, toks, qlow), i, t)
              for i, t in enumerate(items)]
    ranked = sorted([s for s in scored if s[0] >= float(min_score or 0)],
                    key=lambda x: (-x[0], x[1]))
    keep_idx = set()
    for sc, i, t in ranked[:k]:
        keep_idx.add(i)
    for i, t in enumerate(items):
        if _parts(t)[0] in forced:
            keep_idx.add(i)
    if not keep_idx and ranked:
        keep_idx.add(ranked[0][1])
    # 按相关性降序输出（强制保留的追加在后面），让 Top-K 语义一目了然
    ordered_idx = [i for _, i, _ in ranked if i in keep_idx]
    for i in sorted(keep_idx):
        if i not in ordered_idx:
            ordered_idx.append(i)
    selected = [items[i] for i in ordered_idx]
    # 强制保留可能超过 top_k，此处不再截断，保证「强制」语义
    after = estimate_tokens(selected)
    return selected, _report(total, len(selected), before, after)


def _report(total, kept, before, after, skipped=False):
    saved = max(0, before - after)
    pct = round(saved * 100.0 / before, 1) if before else 0.0
    return {
        "total": total,
        "kept": kept,
        "dropped": max(0, total - kept),
        "tokens_before": before,
        "tokens_after": after,
        "saved_tokens": saved,
        "saved_pct": pct,
        "skipped": bool(skipped),
    }


def format_report(report):
    """一行人类可读摘要（CLI / 状态栏）。"""
    r = report or {}
    if r.get("skipped"):
        return "工具按需选择：未裁剪（%d 个工具全部注入）" % r.get("total", 0)
    return ("工具按需选择：%d → %d 个，工具提示词 %d → %d tokens，"
            "节省约 %s%%" % (r.get("total", 0), r.get("kept", 0),
                            r.get("tokens_before", 0), r.get("tokens_after", 0),
                            r.get("saved_pct", 0)))
