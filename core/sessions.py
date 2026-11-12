# -*- coding: utf-8 -*-
"""多会话管理：本地持久化多个对话，支持新建 / 重命名 / 删除 / 切换 / 搜索。

存储：配置目录下 sessions.json
    {"current": "<id>", "sessions": [{"id", "title", "created", "updated",
                                      "messages": [...]}]}

- 每个会话保存完整 messages（含系统提示与工具消息），切回后可继续对话
- 标题默认取首条用户消息前 20 字，可重命名
- 超出上限时自动淘汰最旧的未固定会话
"""
import json
import os
import re
import time

from core import storage

from core.config import get_config_dir
from core.insights import merge_messages

SESSIONS_FILE = "sessions.json"
MAX_SESSIONS = 50
TITLE_MAX = 24

# V11.4 消息引用：引用片段最大字符数（防止把整段长回答塞进输入上下文）
QUOTE_MAX_CHARS = 300


def _now():
    return int(time.time())


def message_text(message):
    """从消息中提取可显示文本（多模态 content 取文本部分）"""
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content
                 if isinstance(p, dict) and p.get("type") == "text"]
        has_media = any(isinstance(p, dict)
                        and p.get("type") in ("image_url",)
                        for p in content)
        text = "\n".join(t for t in parts if t)
        if has_media and not text:
            return "（图片消息）"
        return text
    return str(content or "")


def trim_history(history, limit):
    """按上限裁剪历史（保留系统提示，返回新列表）"""
    system = history[0] if history and history[0].get("role") == "system" else None
    msgs = history[1:] if system else list(history)
    if len(msgs) > limit:
        msgs = msgs[-limit:]
    return ([system] if system else []) + msgs


def _auto_title(messages):
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, list):
            text = " ".join(p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type") == "text")
        else:
            text = str(content or "")
        text = " ".join(text.split())
        if text:
            return text[:TITLE_MAX] + ("…" if len(text) > TITLE_MAX else "")
    return "新会话"


# ----------------------------------------------------------------------
# 标签（V11.2 新增）：以 # 组织的会话分类，跨桌面 / 安卓共用
# ----------------------------------------------------------------------
def _normalize_tags(tags):
    """把 list / 逗号·空格分隔字符串归一化为去重、截断的标签列表。

    保留首次出现顺序；忽略空白项；单标签最长 20 字符。
    """
    if isinstance(tags, str):
        parts = re.split(r"[,，、;；\s]+", tags)
    else:
        parts = list(tags or [])
    out, seen = [], set()
    for p in parts:
        t = (p or "").strip()
        if not t:
            continue
        t = t[:24]
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out[:12]                        # 单会话最多 12 个标签


# ----------------------------------------------------------------------
# 相关性检索辅助（V11.1 新增）
# ----------------------------------------------------------------------
def _tokenize(text):
    """中英文混合分词：英文/数字按词，中文按连续片段 + 相邻二元组。

    返回小写 token 列表，兼顾英文整词与中文子串/短语匹配。

    V11.5 精度修正：**不再把单个汉字作为 token**。旧实现把中文拆成单字，
    导致搜「不存在的关键词xyz」时，标题里出现「的」之类的高频虚词也会得分，
    无关会话被误召回（全量自测「搜索无结果」用例暴露）。改为按连续 CJK
    片段切分：片段长度 ≥2 时整体入 token，并保留片段内相邻二元组。
    这样「重命名」仍能命中「重命名后的会话」，虚词噪音被消除。
    """
    text = (text or "").lower()
    tokens = list(re.findall(r"[a-z0-9]+", text))      # 英文 / 数字词
    for run in re.findall(r"[一-鿿]+", text):           # 连续中文片段
        if len(run) >= 2:
            tokens.append(run)                         # 整段短语
        for i in range(len(run) - 1):                  # 片段内二元组
            tokens.append(run[i] + run[i + 1])
    # 单字中文（片段长度为 1）刻意丢弃，避免高频虚词误命中
    return tokens


def _snippet(text, query, width=48):
    """定位 query 在 text 中首次出现，返回带 ⚡ 标记的摘要片段。

    找不到整串时退化为取前 width 字；用于检索结果预览。
    """
    text = text or ""
    q = (query or "").strip()
    if not text:
        return ""
    if not q:
        return text[:width] + ("…" if len(text) > width else "")
    low, qlow = text.lower(), q.lower()
    idx = low.find(qlow)
    if idx < 0:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, idx - width // 2)
    end = min(len(text), idx + len(q) + width // 2)
    frag = text[start:end]
    if start > 0:
        frag = "…" + frag
    if end < len(text):
        frag = frag + "…"
    m = frag.lower().find(qlow)
    if m >= 0:
        frag = frag[:m] + "⚡" + frag[m:m + len(q)] + "⚡" + frag[m + len(q):]
    return frag


class SessionStore:
    """会话存储（线程不安全，仅在 UI 线程使用）"""

    def __init__(self, path=None):
        self.path = path or os.path.join(get_config_dir(), SESSIONS_FILE)
        self.data = {"current": "", "sessions": []}
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("sessions"), list):
                self.data = data
        except Exception:
            self.data = {"current": "", "sessions": []}
        if not self.data["sessions"]:
            self.create()

    def save(self):
        # 统一走 core.storage 的原子写入（v7.2 去重）
        return storage.save_json(self.path, self.data)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def _sessions(self):
        return self.data.get("sessions") or []

    def list(self, tag=None):
        """会话摘要列表（不含 messages），按更新时间倒序。

        tag：按标签过滤（不区分大小写）；为空则返回全部。
        V11.2 起每条摘要携带 tags 字段。
        """
        out = []
        qtag = (tag or "").strip().lower()
        for s in self._sessions():
            tags = s.get("tags") or []
            if qtag and qtag not in [t.lower() for t in tags]:
                continue
            out.append({
                "id": s.get("id", ""),
                "title": s.get("title", "未命名"),
                "created": s.get("created", 0),
                "updated": s.get("updated", 0),
                "count": len([m for m in (s.get("messages") or [])
                              if m.get("role") in ("user", "assistant")]),
                "pinned": bool(s.get("pinned")),
                "tags": list(tags),
            })
        out.sort(key=lambda x: (not x["pinned"], -x["updated"]))
        return out

    def list_tags(self):
        """聚合全部标签及出现次数，按次数降序、名称升序返回 [(tag, count)]。"""
        counter = {}
        for s in self._sessions():
            for t in (s.get("tags") or []):
                counter[t] = counter.get(t, 0) + 1
        items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return items

    def get(self, session_id):
        for s in self._sessions():
            if s.get("id") == session_id:
                return s
        return None

    def current(self):
        sid = self.data.get("current") or ""
        session = self.get(sid)
        if session is None:
            session = self._sessions()[0] if self._sessions() else None
            if session is not None:
                self.data["current"] = session["id"]
        return session

    def current_id(self):
        cur = self.current()
        return cur.get("id", "") if cur else ""

    def search_ranked(self, query, top_k=20, tag=None):
        """相关性检索（V11.1 新增）：中英文分词 + 词频/标题加权排序。

        返回带 score 与 snippet（高亮摘要）的结果列表；空查询返回全部。
        tag：按标签过滤（V11.2）。桌面检索框与安卓共用。
        """
        q = (query or "").strip()
        qtag = (tag or "").strip().lower()
        if not q:
            return self.list(tag=tag)
        qtokens = _tokenize(q)
        if not qtokens:
            # V11.5：纯单字 / 无有效 token 时不再「返回全部会话」，
            # 否则搜一个含高频虚词的无关词会把整个会话列表都召回。
            return []
        qlow = q.lower()
        results = []
        for s in self._sessions():
            tags = s.get("tags") or []
            if qtag and qtag not in [t.lower() for t in tags]:
                continue
            title = s.get("title") or ""
            messages = s.get("messages") or []
            title_low = title.lower()
            bodies = [message_text(m) for m in messages]
            body_low = " ".join(bodies).lower()
            score = 0
            for t in qtokens:
                score += title_low.count(t) * 5      # 标题命中加权
                score += body_low.count(t)            # 正文词频
            if qlow in title_low:
                score += 10                           # 标题整串命中
            if qlow in body_low:
                score += 3                            # 正文整串命中
            if score <= 0:
                continue
            snippet = ""
            for m in messages:
                mt = message_text(m)
                if qlow in mt.lower():
                    snippet = _snippet(mt, q)
                    break
            if not snippet and title:
                snippet = _snippet(title, q)
            results.append({
                "id": s.get("id", ""),
                "title": title or "未命名",
                "created": s.get("created", 0),
                "updated": s.get("updated", 0),
                "count": len([m for m in messages
                              if m.get("role") in ("user", "assistant")]),
                "pinned": bool(s.get("pinned")),
                "tags": list(tags),
                "score": score,
                "snippet": snippet,
            })
        results.sort(key=lambda x: (-x["score"], not x["pinned"], -x["updated"]))
        return results[:top_k]

    def search(self, query, tag=None):
        """按标题 / 消息内容检索（V11.1 起委托 search_ranked 做相关性排序）。

        返回结构与旧版兼容（id/title/created/updated/count/pinned/tags），
        并额外携带 score 与 snippet 供 UI 展示。
        """
        return self.search_ranked(query, tag=tag)

    # ------------------------------------------------------------------
    # 变更
    # ------------------------------------------------------------------
    def create(self, title=None):
        session = {"id": "s_%d_%s" % (_now(), os.urandom(3).hex()),
                   "title": title or "新会话",
                   "created": _now(), "updated": _now(),
                   "messages": [], "tags": [],
                   "starred": [], "summary": ""}
        self.data.setdefault("sessions", []).append(session)
        self.data["current"] = session["id"]
        self._trim()
        self.save()
        return session

    def _trim(self):
        sessions = self._sessions()
        if len(sessions) <= MAX_SESSIONS:
            return
        # 淘汰最旧的未固定会话（保留当前会话）
        cur = self.data.get("current")
        removable = [s for s in sessions
                     if not s.get("pinned") and s.get("id") != cur]
        removable.sort(key=lambda s: s.get("updated", 0))
        drop = {s["id"] for s in removable[:len(sessions) - MAX_SESSIONS]}
        self.data["sessions"] = [s for s in sessions
                                 if s.get("id") not in drop]

    def rename(self, session_id, title):
        session = self.get(session_id)
        if session is None:
            return False
        title = (title or "").strip()
        if not title:
            return False
        session["title"] = title[:TITLE_MAX]
        session["updated"] = _now()
        self.save()
        return True

    def set_pinned(self, session_id, pinned):
        session = self.get(session_id)
        if session is None:
            return False
        session["pinned"] = bool(pinned)
        self.save()
        return True

    def set_tags(self, session_id, tags):
        """V11.2：为会话设置标签（list / 逗号分隔字符串均可）。"""
        session = self.get(session_id)
        if session is None:
            return False
        session["tags"] = _normalize_tags(tags)
        session["updated"] = _now()
        self.save()
        return True

    def edit_message(self, session_id, index, content):
        """V11.2：修改某条消息的内容（保留 role / 系统提示），返回更新后历史。

        index 越界或会话不存在返回 False。
        """
        session = self.get(session_id)
        if session is None:
            return False
        msgs = session.get("messages") or []
        if not (0 <= index < len(msgs)):
            return False
        if msgs[index].get("role") == "system":
            return False            # 不允许改系统提示
        msgs[index]["content"] = content
        session["updated"] = _now()
        self.save()
        return list(msgs)

    def delete_message(self, session_id, index):
        """V11.2：删除某条消息，返回更新后历史；越界 / 不存在返回 False。"""
        session = self.get(session_id)
        if session is None:
            return False
        msgs = session.get("messages") or []
        if not (0 <= index < len(msgs)):
            return False
        del msgs[index]
        session["updated"] = _now()
        self.save()
        return list(msgs)

    # ------------------------------------------------------------------
    # V11.3：消息收藏（Star）+ AI 摘要缓存
    # ------------------------------------------------------------------
    def toggle_star(self, session_id, index):
        """收藏 / 取消收藏某条消息（按消息在会话中的位置 index）。

        返回切换后的收藏状态（bool）；会话/索引非法返回 None。
        注意：编辑或删除消息会改变索引，收藏以 index 为准（与 edit/delete 一致）。
        """
        session = self.get(session_id)
        if session is None:
            return None
        msgs = session.get("messages") or []
        if not (0 <= index < len(msgs)):
            return None
        starred = session.setdefault("starred", [])
        if index in starred:
            starred.remove(index)
            now = False
        else:
            starred.append(index)
            now = True
        session["updated"] = _now()
        self.save()
        return now

    def is_starred(self, session_id, index):
        session = self.get(session_id)
        if session is None:
            return False
        return index in (session.get("starred") or [])

    def list_starred(self):
        """跨全部会话返回收藏消息列表，按更新时间倒序。

        每项：{session_id, title, index, role, content, snippet}
        """
        out = []
        for s in self._sessions():
            starred = s.get("starred") or []
            msgs = s.get("messages") or []
            for idx in starred:
                if 0 <= idx < len(msgs):
                    m = msgs[idx]
                    text = message_text(m)
                    out.append({
                        "session_id": s.get("id", ""),
                        "title": s.get("title", "未命名"),
                        "index": idx,
                        "role": m.get("role", ""),
                        "content": text,
                        "snippet": (text or "")[:120],
                        "updated": s.get("updated", 0),
                    })
        out.sort(key=lambda x: -x["updated"])
        return out

    def set_summary(self, session_id, text):
        """缓存 AI 生成的会话摘要（空字符串表示清除）。"""
        session = self.get(session_id)
        if session is None:
            return False
        session["summary"] = (text or "")[:8000]
        session["updated"] = _now()
        self.save()
        return True

    def get_summary(self, session_id):
        session = self.get(session_id)
        if session is None:
            return ""
        return session.get("summary") or ""

    # ------------------------------------------------------------------
    # V11.4：消息引用（Quote）+ 分支对话（Branch）
    #   —— 纯逻辑，零 Qt / 零安卓依赖，桌面与安卓同源共用
    # ------------------------------------------------------------------
    def get_message(self, session_id, index):
        """返回第 index 条消息（dict）；会话不存在 / 索引越界返回 None。"""
        session = self.get(session_id)
        if session is None:
            return None
        msgs = session.get("messages") or []
        if not (0 <= index < len(msgs)):
            return None
        return msgs[index]

    def quote_block(self, session_id, index, max_chars=QUOTE_MAX_CHARS):
        """生成第 index 条消息的引用块文本；非法索引返回空串。"""
        message = self.get_message(session_id, index)
        if message is None:
            return ""
        return format_quote(message, index=index, max_chars=max_chars)

    def branch_from(self, session_id, index, title=None):
        """从会话第 index 条消息（含）处分支出一个新会话。

        - 复制 messages[:index+1]（含前置系统提示）到新会话，逐条浅拷贝
        - 继承 tags；starred 仅保留下标 <= index 的收藏
        - 记录 branched_from={session_id, index} 便于溯源（旧会话无此字段，兼容）
        - 新会话自动置为 current 并落库；返回新会话 dict
        - index 越界 / 会话不存在返回 None
        """
        src = self.get(session_id)
        if src is None:
            return None
        msgs = src.get("messages") or []
        if not (0 <= index < len(msgs)):
            return None
        head = [dict(m) for m in msgs[:index + 1]]
        base = src.get("title") or "会话"
        new = {
            "id": "s_%d_%s" % (_now(), os.urandom(3).hex()),
            "title": (title or ("分支 · " + base))[:TITLE_MAX],
            "created": _now(), "updated": _now(),
            "messages": head,
            "tags": list(src.get("tags") or []),
            "starred": [i for i in (src.get("starred") or []) if i <= index],
            "summary": "",
            "branched_from": {"session_id": session_id, "index": index},
        }
        self.data.setdefault("sessions", []).append(new)
        self.data["current"] = new["id"]
        self._trim()
        self.save()
        return new

    def list_branches(self, session_id=None):
        """列出由某会话派生的分支摘要；session_id 为空则列出全部分支。

        每项：{id, title, from, index, updated}，按更新时间倒序。
        """
        out = []
        for s in self._sessions():
            bf = s.get("branched_from")
            if not bf:
                continue
            if session_id and bf.get("session_id") != session_id:
                continue
            out.append({
                "id": s.get("id", ""),
                "title": s.get("title", "未命名"),
                "from": bf.get("session_id", ""),
                "index": bf.get("index", 0),
                "updated": s.get("updated", 0),
            })
        out.sort(key=lambda x: -x["updated"])
        return out

    def merge_into(self, target_id, source_id, dedup=True):
        """V11.5：把 source 会话的消息合并进 target，返回 (bool, report)。

        - 复用 :func:`core.insights.merge_messages`：自动识别最长共同前缀，
          因此把「由 target 分出去的分支」合并回来时不会重复追加前缀消息
        - ``source.starred`` 的下标按 ``report["mapping"]`` 重映射后并入
          target（去重、排序），收藏不会因下标变化而错位
        - tags 合并去重；source 本身**不删除**，保留可回溯性
        - target 置为 current 并落库；会话不存在 / 自合并返回 (False, {})
        """
        target = self.get(target_id)
        source = self.get(source_id)
        if target is None or source is None or target_id == source_id:
            return False, {}

        merged, report = merge_messages(
            target.get("messages") or [],
            source.get("messages") or [],
            dedup=dedup)
        mapping = report.get("mapping") or {}

        stars = {int(i) for i in (target.get("starred") or [])}
        for old in source.get("starred") or []:
            new_index = mapping.get(int(old))
            if new_index is not None:
                stars.add(int(new_index))

        tags = list(target.get("tags") or [])
        for tag in source.get("tags") or []:
            if tag not in tags:
                tags.append(tag)

        target["messages"] = merged
        target["starred"] = sorted(stars)
        target["tags"] = tags
        target["updated"] = _now()
        self.data["current"] = target_id
        self.save()

        report["tags_merged"] = len(tags)
        report["starred_total"] = len(stars)
        return True, report

    def delete(self, session_id):
        sessions = self._sessions()
        self.data["sessions"] = [s for s in sessions
                                 if s.get("id") != session_id]
        if self.data.get("current") == session_id:
            self.data["current"] = ""
            if not self.current():
                self.create()
        self.save()
        return True

    def set_current(self, session_id):
        if self.get(session_id) is None:
            return False
        self.data["current"] = session_id
        self.save()
        return True

    def touch(self, session_id=None):
        session = self.get(session_id or self.current_id())
        if session is not None:
            session["updated"] = _now()
            self.save()

    def set_messages(self, messages, session_id=None):
        """整体替换消息（切换 / 保存时调用）"""
        session = self.get(session_id or self.current_id())
        if session is None:
            return False
        session["messages"] = messages
        session["updated"] = _now()
        if session["title"] in ("", "新会话"):
            session["title"] = _auto_title(messages)
        self.save()
        return True

    def append(self, message, session_id=None):
        session = self.get(session_id or self.current_id())
        if session is None:
            return False
        msgs = session.setdefault("messages", [])
        msgs.append(message)
        session["updated"] = _now()
        # 首条用户消息 → 自动命名
        if message.get("role") == "user" and \
                session["title"] in ("", "新会话"):
            session["title"] = _auto_title(msgs)
        self.save()
        return True

    def messages(self, session_id=None):
        session = self.get(session_id or self.current_id())
        if session is None:
            return []
        return session.get("messages") or []


def build_summary_prompt(messages):
    """V11.3：根据会话历史构造「总结」提示词（纯函数，便于测试 / 复用）。

    返回 (system, user) 两段提示：让模型用中文提炼 3-5 条要点 + 关键结论。
    自动过滤系统提示与空内容。
    """
    dialog = []
    for m in messages or []:
        role = m.get("role")
        text = message_text(m)
        if not text.strip() or role == "system":
            continue
        if role == "user":
            dialog.append("用户：%s" % text)
        elif role == "assistant":
            dialog.append("助手：%s" % text)
    if not dialog:
        return ("你是摘要助手。", "（对话为空，无需总结。）")
    body = "\n".join(dialog)
    system = ("你是星语 Starry 的总结助手。请用简体中文，从下面的对话中提取"
              "关键信息，输出 3-5 条要点（每条一行，以「- 」开头），并在末尾用"
              "一句话概括核心结论。不要复述原文，只保留实质内容。")
    user = "请总结以下对话：\n\n%s" % body
    return system, user


# ----------------------------------------------------------------------
# V11.4 消息引用 / 分支对话：模块级纯函数（便于单测与跨端复用）
# ----------------------------------------------------------------------
_ROLE_LABEL = {
    "user": "我",
    "assistant": "助手",
    "system": "系统",
    "tool": "工具",
}


def format_quote(message, index=0, max_chars=QUOTE_MAX_CHARS):
    """把一条消息格式化为 Markdown 引用块（纯函数）。

    形如：
        > 【引用 #2 · 助手】
        > 这是被引用的历史内容…
        > （多行内容逐行加 > 前缀）

    - 过滤系统提示与空内容（返回空串）
    - 超长文本按 max_chars 截断并追加省略号
    - 多模态 content 取文本部分（复用 message_text）
    """
    if not isinstance(message, dict):
        return ""
    role = message.get("role", "")
    if role == "system":
        return ""
    text = message_text(message).strip()
    if not text:
        return ""
    truncated = False
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    if truncated:
        text += "…"
    label = _ROLE_LABEL.get(role, role or "消息")
    lines = text.splitlines() or [text]
    body = "\n".join("> " + ln for ln in lines)
    return "> 【引用 #%d · %s】\n%s" % (index, label, body)


def build_quoted_prompt(quote_text, user_text):
    """把引用块与用户新输入拼成一条带上下文的 user 消息（纯函数）。

    - 空引用或空输入均安全处理，不产生多余空行
    - 结果为可直接放进 messages 的 content 字符串，让模型明确"针对引用作答"
    """
    q = (quote_text or "").strip()
    u = (user_text or "").strip()
    if not q and not u:
        return ""
    if not q:
        return u
    if not u:
        return "%s\n\n（以上是引用的历史消息，请针对它进行说明或续写。）" % q
    return ("%s\n\n---\n（以上是引用的历史消息，下面是我基于它的新问题，"
            "请结合引用内容作答）\n\n%s") % (q, u)
