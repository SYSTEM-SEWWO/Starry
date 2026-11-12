# -*- coding: utf-8 -*-
"""上下文管理（纯函数，无 Qt 依赖）。

对标主流 AI 客户端（WorkBuddy / Cherry Studio 等）的「上下文大小」能力：
- estimate_tokens    粗略估算一段文本的 token 数（中英文混合）
- messages_tokens    估算整条消息列表的 token 占用
- trim_to_context    按 token 上限裁剪历史：保留系统消息与最近若干条

估算规则（刻意从简，误差 ±20% 可接受）：
- CJK 字符（中日韩）约 1 字 = 1 token
- 其余按 4 字符 ≈ 1 token（英文/数字/符号的经验值）
"""
import json


def _text_of(message):
    """提取消息的纯文本（兼容多模态 content 列表）"""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                if p.get("type") == "text":
                    parts.append(p.get("text") or "")
                elif p.get("type") == "image_url":
                    parts.append("[图片]")
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def estimate_tokens(text):
    """粗略估算 token 数"""
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if "\u2e80" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af" \
                or "\uff00" <= ch <= "\uffef" or "\u3000" <= ch <= "\u303f":
            cjk += 1
        else:
            other += 1
    return cjk + (other + 3) // 4


def messages_tokens(messages):
    """整条消息列表的 token 估算（含每条 4 token 的结构开销）"""
    total = 0
    for m in messages or []:
        total += estimate_tokens(_text_of(m)) + 4
        if m.get("tool_calls"):
            total += estimate_tokens(json.dumps(m["tool_calls"],
                                                ensure_ascii=False)) + 4
    return total


def trim_to_context(messages, max_tokens, keep_system=True):
    """按 token 上限从旧到新裁剪，保留系统消息与最近的对话。

    返回 (trimmed_messages, used_tokens, dropped_count)。
    任何情况下至少保留最后一条用户消息（宁可超限也不丢当前问题）。
    """
    msgs = list(messages or [])
    if max_tokens and max_tokens > 0:
        system = []
        if keep_system and msgs and msgs[0].get("role") == "system":
            system = [msgs[0]]
            msgs = msgs[1:]
        used = messages_tokens(system)
        kept = []
        for m in reversed(msgs):
            cost = estimate_tokens(_text_of(m)) + 4
            if kept and used + cost > max_tokens:
                break
            kept.append(m)
            used += cost
        kept.reverse()
        out = system + kept
        return out, messages_tokens(out), len(msgs) - len(kept)
    return msgs, messages_tokens(msgs), 0


def context_usage_str(used, limit):
    """状态栏展示：'1.2K / 32K'"""
    def fmt(n):
        if n >= 1024:
            return "%.1fK" % (n / 1024.0)
        return str(int(n))
    return "%s / %s" % (fmt(used), fmt(limit or 0))
