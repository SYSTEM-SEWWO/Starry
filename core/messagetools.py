# -*- coding: utf-8 -*-
"""v13.8 对话工具箱（纯逻辑、零 Qt、三端同源）。

把「消息级操作」从 UI 里抽出来，方便测试与桌面/安卓/CLI 复用：

* ``rendered_indices``  —— UI 气泡序号 -> history 真实索引
* ``search_messages``    —— 会话内查找（大小写不敏感，返回命中摘要）
* ``edit_message_text``  —— 编辑某条消息文本（多模态 content 只改文本段）
* ``message_stats``      —— 条数 / 字数 / 估算 token / 角色分布
* ``export_messages``    —— 导出所选消息为 Markdown
* ``backup_sessions`` / ``list_backups`` / ``restore_sessions``
* ``parse_slash_command``—— 输入框斜杠命令解析
"""
import json
import os
import shutil
import time

from core.sessions import message_text

# 斜杠命令表：(命令, 说明)
SLASH_COMMANDS = (
    ("/new", "新建一个会话"),
    ("/clear", "清空当前对话记录"),
    ("/select", "进入消息勾选模式"),
    ("/find", "在当前对话中查找"),
    ("/sessions", "打开会话管理"),
    ("/settings", "打开设置"),
    ("/export", "导出当前对话"),
    ("/help", "查看全部斜杠命令"),
)


def rendered_indices(history):
    """返回会被渲染成气泡的 history 索引（用户消息 + 有内容的助手消息）。"""
    out = []
    for i, m in enumerate(history or []):
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "user" or (role == "assistant" and m.get("content")):
            out.append(i)
    return out


def map_ordinals(history, ordinals):
    """UI 气泡序号 -> history 真实索引；越界忽略，返回降序去重结果。"""
    idx = rendered_indices(history)
    return sorted({idx[int(o)] for o in (ordinals or [])
                   if isinstance(o, int) and 0 <= int(o) < len(idx)},
                  reverse=True)


def search_messages(history, query, limit=50):
    """会话内查找，返回 [{index, ordinal, role, snippet}]。"""
    q = (query or "").strip().lower()
    if not q:
        return []
    idx = rendered_indices(history)
    hits = []
    for ordinal, i in enumerate(idx):
        m = history[i]
        text = message_text(m)
        pos = text.lower().find(q)
        if pos < 0:
            continue
        start = max(0, pos - 24)
        end = min(len(text), pos + len(q) + 36)
        snippet = ("…" if start else "") + text[start:end].replace("\n", " ") \
                  + ("…" if end < len(text) else "")
        hits.append({"index": i, "ordinal": ordinal, "role": m.get("role"),
                     "snippet": snippet})
        if len(hits) >= max(1, int(limit)):
            break
    return hits


def edit_message_text(message, new_text):
    """编辑消息文本，返回新消息 dict（不改原对象）。多模态只替换文本段。"""
    m = dict(message or {})
    content = m.get("content")
    if isinstance(content, list):
        parts = []
        replaced = False
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text" and not replaced:
                parts.append({"type": "text", "text": new_text})
                replaced = True
            else:
                parts.append(p)
        if not replaced:
            parts.insert(0, {"type": "text", "text": new_text})
        m["content"] = parts
    else:
        m["content"] = new_text
    return m


def message_stats(history):
    """消息统计：总条数 / 可见条数 / 字数 / 估算 token / 角色分布。"""
    msgs = [m for m in (history or []) if isinstance(m, dict)]
    chars = sum(len(message_text(m)) for m in msgs
                if m.get("role") in ("user", "assistant"))
    roles = {}
    for m in msgs:
        r = m.get("role", "unknown")
        roles[r] = roles.get(r, 0) + 1
    cjk = sum(1 for m in msgs for c in message_text(m) if "\u4e00" <= c <= "\u9fff")
    return {
        "total": len(msgs),
        "visible": len(rendered_indices(msgs)),
        "chars": chars,
        "tokens_estimate": int(cjk + (chars - cjk) / 4.0) + len(msgs) * 4,
        "roles": roles,
    }


def export_messages(history, ordinals=None, title="对话"):
    """导出所选（或全部）消息为 Markdown。"""
    idx = rendered_indices(history)
    chosen = idx if not ordinals else [idx[int(o)] for o in ordinals
                                       if isinstance(o, int) and 0 <= int(o) < len(idx)]
    lines = ["# %s" % (title or "对话"), ""]
    for i in sorted(chosen):
        m = history[i]
        role = "🧑 用户" if m.get("role") == "user" else "✦ 星语"
        lines.append("**%s**" % role)
        lines.append("")
        lines.append(message_text(m))
        lines.append("")
    return "\n".join(lines)


def parse_slash_command(text):
    """解析斜杠命令，返回 (command, args) 或 (None, text)。"""
    t = (text or "").strip()
    if not t.startswith("/"):
        return None, text
    head, _, rest = t.partition(" ")
    cmd = head.lower()
    if cmd == "/?":
        cmd = "/help"
    known = {c for c, _d in SLASH_COMMANDS}
    if cmd not in known:
        return None, text
    return cmd, rest.strip()


def format_slash_help():
    return "可用斜杠命令：\n" + "\n".join(
        "  %-12s %s" % (c, d) for c, d in SLASH_COMMANDS)


def backup_sessions(path, keep=10):
    """备份 sessions.json 到同目录 backups/，返回备份路径；文件不存在返回 ''。"""
    if not path or not os.path.isfile(path):
        return ""
    d = os.path.join(os.path.dirname(os.path.abspath(path)), "backups")
    os.makedirs(d, exist_ok=True)
    name = "sessions-%s.json" % time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(d, name)
    shutil.copy2(path, dst)
    files = sorted(f for f in os.listdir(d) if f.startswith("sessions-")
                   and f.endswith(".json"))
    for f in files[:-max(1, int(keep))]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass
    return dst


def list_backups(path):
    """列出备份文件（新->旧）。"""
    d = os.path.join(os.path.dirname(os.path.abspath(path or "")), "backups")
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(
        (f for f in os.listdir(d) if f.startswith("sessions-")
         and f.endswith(".json")), reverse=True)]


def restore_sessions(path, backup):
    """从备份恢复 sessions.json；先校验 JSON 结构，失败抛 ValueError。"""
    if not backup or not os.path.isfile(backup):
        raise ValueError("备份文件不存在")
    with open(backup, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        raise ValueError("备份格式不正确")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # 先备份当前，再覆盖，避免误操作无法回退
    if os.path.isfile(path):
        backup_sessions(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return len(data["sessions"])
