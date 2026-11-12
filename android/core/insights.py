# -*- coding: utf-8 -*-
"""星语 Starry · 对话洞察（V11.5）

纯函数层：分支对比（diff）/ 消息合并（merge）/ 会话统计（stats）。
零 GUI 框架依赖、零文件 IO —— 桌面与安卓同源共用，可直接单测。

设计约定
--------
1. 所有入参都是「会话 dict」或「消息 dict 列表」，返回值一律为新对象，
   **绝不修改入参**，避免副作用污染 SessionStore 的内存态。
2. 消息文本提取兼容 ``str`` / 多模态 ``list[dict]`` / ``None``，行为与
   :func:`core.sessions.message_text` 一致，但本模块 **不 import sessions**，
   以免与 ``SessionStore.merge_into`` 形成循环依赖。
3. 「共同前缀」是 V11.4 分支对话的自然延伸：分支会话复制了源会话的前 N
   条消息，对比与合并都以这段共同前缀为锚点，避免重复计数 / 重复追加。
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def message_content(message):
    """从一条消息中取出纯文本（兼容 str / 多模态 list / dict / None）。"""
    if isinstance(message, str):
        return message
    if message is None:
        return ""
    if not isinstance(message, dict):
        return str(message)
    content = message.get("content")
    if content is None:
        content = message.get("text") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(p for p in parts if p)
    return str(content) if content else ""


def _role(message):
    if isinstance(message, dict):
        return str(message.get("role") or "other")
    return "other"


def _fingerprint(message):
    """消息指纹 ``(role, 规范化文本)``，用于对比与去重。"""
    return (_role(message), " ".join(message_content(message).split()))


def estimate_tokens(text):
    """粗略估算 token 数：CJK 每字约 1 token，其余约 4 字符 ≈ 1 token。

    这是不依赖 tokenizer 的离线估算，用于统计面板的相对量级参考，
    不代表任何具体模型的精确计费值。
    """
    if not text:
        return 0
    cjk = other = 0
    for ch in str(text):
        code = ord(ch)
        if (0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF
                or 0x3000 <= code <= 0x303F):
            cjk += 1
        else:
            other += 1
    return cjk + (other + 3) // 4


def _brief(index, message, max_chars=140):
    text = " ".join(message_content(message).split())
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return {"index": index, "role": _role(message), "text": text}


# ---------------------------------------------------------------------------
# 分支对比
# ---------------------------------------------------------------------------
def common_prefix_len(a_messages, b_messages):
    """两条消息序列的最长共同前缀长度（按消息指纹判定）。"""
    common = 0
    for left, right in zip(a_messages or [], b_messages or []):
        if _fingerprint(left) == _fingerprint(right):
            common += 1
        else:
            break
    return common


def diff_sessions(session_a, session_b, max_chars=140):
    """对比两个会话，返回结构化差异 dict（不修改入参）。

    返回字段::

        a_id / b_id / a_title / b_title
        a_count / b_count            消息总数
        common_prefix                最长共同前缀长度（分支锚点）
        modified                     前缀之后同位置内容不同的项
                                     [{index, a_role, a_text, b_role, b_text}]
        a_only / b_only              各自多出来的尾部消息
        identical                    两序列是否完全一致
        similarity                   2*common/(a_count+b_count)，0~1

    算法：先求最长共同前缀（同源分支必有大段重合），前缀之后按位置对齐，
    同位置不同记 modified，多出的尾部记 a_only / b_only。对「从某点分叉后
    各自续写」这一真实场景，比通用 LCS 更直观且结果稳定。
    """
    a = list((session_a or {}).get("messages") or [])
    b = list((session_b or {}).get("messages") or [])
    common = common_prefix_len(a, b)

    a_tail, b_tail = a[common:], b[common:]
    paired = min(len(a_tail), len(b_tail))
    modified = []
    for offset in range(paired):
        if _fingerprint(a_tail[offset]) == _fingerprint(b_tail[offset]):
            continue
        ai = common + offset
        modified.append({
            "index": ai,
            "a_role": _role(a_tail[offset]),
            "a_text": _brief(ai, a_tail[offset], max_chars)["text"],
            "b_role": _role(b_tail[offset]),
            "b_text": _brief(ai, b_tail[offset], max_chars)["text"],
        })

    a_only = [_brief(common + paired + k, m, max_chars)
              for k, m in enumerate(a_tail[paired:])]
    b_only = [_brief(common + paired + k, m, max_chars)
              for k, m in enumerate(b_tail[paired:])]

    total = len(a) + len(b)
    similarity = (2.0 * common / total) if total else 1.0
    return {
        "a_id": (session_a or {}).get("id", ""),
        "b_id": (session_b or {}).get("id", ""),
        "a_title": (session_a or {}).get("title", "未命名"),
        "b_title": (session_b or {}).get("title", "未命名"),
        "a_count": len(a),
        "b_count": len(b),
        "common_prefix": common,
        "modified": modified,
        "a_only": a_only,
        "b_only": b_only,
        "identical": len(a) == len(b) and common == len(a) and not modified,
        "similarity": round(similarity, 4),
    }


# ---------------------------------------------------------------------------
# 会话合并
# ---------------------------------------------------------------------------
def merge_messages(a_messages, b_messages, dedup=True, common_prefix=None):
    """把 B 的消息合并到 A 之后，返回 ``(merged, report)``，不修改入参。

    - ``common_prefix`` 为 ``None`` 时自动求最长共同前缀，并**跳过 B 的前 N
      条**（分支会话复制了源会话前缀，不应重复追加）；显式传入可覆盖。
    - ``dedup=True``：B 中指纹已在最终序列里出现过的条目跳过。
    - ``report`` 字段::

        {"added", "skipped", "total", "common_prefix", "mapping"}

      其中 ``mapping`` 是 ``{B 中的原下标: 合并后新下标}``，供
      :meth:`SessionStore.merge_into` 重映射 ``starred`` 收藏下标。
    """
    a = [dict(m) if isinstance(m, dict) else {"role": "user", "content": m}
         for m in (a_messages or [])]
    b = list(b_messages or [])

    if common_prefix is None:
        common = common_prefix_len(a, b)
    else:
        common = max(0, min(int(common_prefix), len(b)))

    merged = list(a)
    seen = {_fingerprint(m) for m in a}
    mapping = {}

    # 共同前缀：B[j] 对应 A[j]（可能位于 A 中部，但前缀定义保证 j 有效）
    for j in range(min(common, len(a))):
        mapping[j] = j

    added = skipped = 0
    for j in range(common, len(b)):
        message = b[j]
        fingerprint = _fingerprint(message)
        if dedup and fingerprint in seen:
            skipped += 1
            continue
        new_index = len(merged)
        merged.append(dict(message) if isinstance(message, dict)
                      else {"role": "user", "content": message})
        seen.add(fingerprint)
        mapping[j] = new_index
        added += 1

    report = {
        "added": added,
        "skipped": skipped,
        "total": len(merged),
        "common_prefix": common,
        "mapping": mapping,
    }
    return merged, report


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def session_stats(session):
    """单会话统计 dict（不修改入参）。"""
    data = session or {}
    messages = list(data.get("messages") or [])
    roles = {}
    chars = tokens = 0
    for message in messages:
        roles[_role(message)] = roles.get(_role(message), 0) + 1
        text = message_content(message)
        chars += len(text)
        tokens += estimate_tokens(text)
    total = len(messages)
    return {
        "id": data.get("id", ""),
        "title": data.get("title", "未命名"),
        "messages": total,
        "roles": roles,
        "user": roles.get("user", 0),
        "assistant": roles.get("assistant", 0),
        "system": roles.get("system", 0),
        "other": total - roles.get("user", 0) - roles.get("assistant", 0)
                 - roles.get("system", 0),
        "chars": chars,
        "tokens": tokens,
        "avg_chars": round(chars / total, 1) if total else 0.0,
        "starred": len(data.get("starred") or []),
        "has_summary": bool(data.get("summary")),
        "tags": list(data.get("tags") or []),
        "is_branch": bool(data.get("branched_from")),
        "branched_from": dict(data.get("branched_from") or {}) or None,
        "pinned": bool(data.get("pinned")),
        "created": data.get("created", 0),
        "updated": data.get("updated", 0),
    }


def overview_stats(sessions):
    """全局聚合统计 dict（所有会话的汇总，不修改入参）。"""
    items = list(sessions or [])
    agg = {
        "sessions": len(items),
        "messages": 0, "user": 0, "assistant": 0, "system": 0, "other": 0,
        "chars": 0, "tokens": 0, "starred": 0,
        "with_summary": 0, "branches": 0, "tagged": 0,
        "unique_tags": 0, "pinned": 0,
        "avg_messages": 0.0,
        "busiest": None,
    }
    tag_set = set()
    busiest = None
    for session in items:
        st = session_stats(session)
        for key in ("messages", "user", "assistant", "system", "other",
                    "chars", "tokens", "starred"):
            agg[key] += st[key]
        agg["with_summary"] += 1 if st["has_summary"] else 0
        agg["branches"] += 1 if st["is_branch"] else 0
        agg["pinned"] += 1 if st["pinned"] else 0
        if st["tags"]:
            agg["tagged"] += 1
            tag_set.update(st["tags"])
        if busiest is None or st["messages"] > busiest["messages"]:
            busiest = {"id": st["id"], "title": st["title"],
                       "messages": st["messages"]}
    agg["unique_tags"] = len(tag_set)
    agg["avg_messages"] = (round(agg["messages"] / len(items), 2)
                           if items else 0.0)
    agg["busiest"] = busiest
    return agg


# ---------------------------------------------------------------------------
# Markdown 渲染（供 UI 面板 / 导出 / CLI 复用，纯字符串）
# ---------------------------------------------------------------------------
def format_diff_markdown(diff):
    """把 :func:`diff_sessions` 结果渲染为可读 Markdown。"""
    d = diff or {}
    lines = [
        "## 🔀 会话对比",
        "",
        "| | A | B |",
        "|---|---|---|",
        "| 会话 | %s | %s |" % (d.get("a_title", "—"), d.get("b_title", "—")),
        "| 消息数 | %s | %s |" % (d.get("a_count", 0), d.get("b_count", 0)),
        "",
        "- **共同前缀**：%d 条" % d.get("common_prefix", 0),
        "- **相似度**：%.0f%%" % (float(d.get("similarity", 0)) * 100),
        "- **完全一致**：%s" % ("是" if d.get("identical") else "否"),
        "",
    ]
    modified = d.get("modified") or []
    if modified:
        lines += ["### ✏️ 同位置内容不同（%d）" % len(modified), ""]
        for m in modified:
            lines += [
                "- **#%d**" % m["index"],
                "  - A（%s）：%s" % (m["a_role"], m["a_text"] or "（空）"),
                "  - B（%s）：%s" % (m["b_role"], m["b_text"] or "（空）"),
            ]
        lines.append("")
    for key, label in (("a_only", "仅 A 有"), ("b_only", "仅 B 有")):
        rows = d.get(key) or []
        if rows:
            lines += ["### %s（%d）" % (label, len(rows)), ""]
            for item in rows:
                lines.append("- **#%d** %s：%s" % (
                    item["index"], item["role"], item["text"] or "（空）"))
            lines.append("")
    if not modified and not (d.get("a_only") or []) and not (d.get("b_only") or []):
        lines += ["两个会话的消息序列一致，没有差异。", ""]
    return "\n".join(lines)


def format_stats_markdown(stats, overview=None):
    """把单会话 / 全局统计渲染为 Markdown 表格。"""
    s = stats or {}
    lines = [
        "## 📊 对话统计 · %s" % s.get("title", "未命名"),
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        "| 消息总数 | %d |" % s.get("messages", 0),
        "| 我的提问 | %d |" % s.get("user", 0),
        "| 助手回复 | %d |" % s.get("assistant", 0),
        "| 系统提示 | %d |" % s.get("system", 0),
        "| 字符数 | %d |" % s.get("chars", 0),
        "| 估算 tokens | %d |" % s.get("tokens", 0),
        "| 平均每条字符 | %s |" % s.get("avg_chars", 0),
        "| 收藏消息 | %d |" % s.get("starred", 0),
        "| 已生成摘要 | %s |" % ("是" if s.get("has_summary") else "否"),
        "| 标签 | %s |" % (", ".join(s.get("tags") or []) or "—"),
        "| 分支会话 | %s |" % ("是" if s.get("is_branch") else "否"),
    ]
    if overview:
        o = overview
        busiest = o.get("busiest") or {}
        lines += [
            "",
            "## 🌐 全局概览",
            "",
            "| 指标 | 数值 |",
            "|---|---|",
            "| 会话总数 | %d |" % o.get("sessions", 0),
            "| 消息总数 | %d |" % o.get("messages", 0),
            "| 平均每会话消息 | %s |" % o.get("avg_messages", 0),
            "| 累计字符 | %d |" % o.get("chars", 0),
            "| 累计估算 tokens | %d |" % o.get("tokens", 0),
            "| 收藏总数 | %d |" % o.get("starred", 0),
            "| 已总结会话 | %d |" % o.get("with_summary", 0),
            "| 分支会话 | %d |" % o.get("branches", 0),
            "| 不同标签 | %d |" % o.get("unique_tags", 0),
            "| 置顶会话 | %d |" % o.get("pinned", 0),
            "| 最活跃会话 | %s（%d 条） |" % (
                busiest.get("title", "—"), busiest.get("messages", 0)),
        ]
    lines.append("")
    return "\n".join(lines)
