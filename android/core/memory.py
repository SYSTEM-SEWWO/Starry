# -*- coding: utf-8 -*-
"""长期记忆系统（V8.0）：跨会话持久化「用户画像 / 偏好 / 事实 / 项目背景」。

设计要点：
- 持久化到 <config_dir>/memory.json，落盘权限 0o600（与 config 一致）。
- 仅以**纯文本**注入系统提示，绝不执行 —— 从根上规避提示注入（prompt
  injection）：记忆条目在写入前经过安全清洗，拒绝 HTML 标签与「忽略之前
  指令」类诱导文本，并约束长度与条数上限。
- 提供启发式学习（从用户发言抽取「我是 X / 我喜欢 X / 项目用 X」），
  以及基于词重叠的相关性检索，供回答时精准召回。

本模块不依赖 UI，可离线单测（见 selftest.py::test_v80_memory_reasoning）。
"""

import json
import os
import re
import time

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
CATEGORIES = ("profile", "preference", "fact", "project")
CATEGORY_LABELS = {
    "profile": "用户画像",
    "preference": "偏好",
    "fact": "事实",
    "project": "项目背景",
}
MAX_ENTRY_LEN = 240          # 单条记忆最大字符数
MAX_ENTRIES = 300            # 记忆总量上限（超出按命中率淘汰）

# 拒绝 HTML 注入：记忆里不允许出现标签字符
_TAG_RE = re.compile(r"[<>&]")
# 拒绝指令式诱导文本（提示注入护栏）
_INJECTION_RE = re.compile(
    r"(ignore\s+(previous|above|all|prior)|disregard|system\s*prompt"
    r"|忽略\s*(之前|以上|前面|所有|上文)|无视\s*(之前|以上|前面|所有))",
    re.I,
)

# 启发式学习：从用户发言抽取结构化记忆
_LEARN_PATTERNS = [
    (re.compile(r"^(?:我|俺|咱)\s*是\s*([^\n，。,.！!？?]{1,40})$"), "profile"),
    (re.compile(r"^(?:我|俺|咱)\s*(?:喜欢|爱|常用|主要用|习惯用|擅长)\s*"
                r"([^\n，。,.！!？?]{1,40})$"), "preference"),
    (re.compile(r"^(?:我们|我们团队|我们组|项目|这个产品|本项目|本产品)\s*"
                r"(?:用|使用|基于|是|采用)\s*([^\n，。,.！!？?]{1,60})$"),
     "project"),
]
# 中文无空格分词：ASCII 词作为整体，CJK 逐字（保证「我/是」类重叠可命中）
_WORD_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def is_safe_entry(text):
    """写入前安全清洗：非空 / 长度 / 无标签 / 无指令诱导。"""
    if not text or not isinstance(text, str):
        return False
    t = text.strip()
    if not t:
        return False
    if len(t) > MAX_ENTRY_LEN:
        return False
    if _TAG_RE.search(t):
        return False
    if _INJECTION_RE.search(t):
        return False
    return True


def _now():
    return int(time.time())


class MemoryStore:
    """长期记忆库：持久化、去重、分类、检索、启发式学习。"""

    def __init__(self, path=None):
        if path is None:
            from core.config import get_config_dir
            path = os.path.join(get_config_dir(), "memory.json")
        self.path = path
        self.enabled = True
        self._entries = []
        self._seq = 0
        self._load()

    # ----------------------------- 持久化 -----------------------------
    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                self.enabled = bool(data.get("enabled", True))
                # 加载时再过滤一遍，避免历史脏数据被复活
                self._entries = [
                    e for e in data.get("entries", [])
                    if isinstance(e, dict) and is_safe_entry(e.get("text", ""))
                ]
                self._seq = int(data.get("seq", 0))
        except Exception:                  # noqa: BLE001 - 损坏文件直接当空
            self._entries = []

    def save(self):
        try:
            data = {"enabled": self.enabled,
                    "seq": self._seq,
                    "entries": self._entries}
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 含用户记忆，限定仅本人可读写
            if os.name == "posix":
                try:
                    os.chmod(self.path, 0o600)
                except Exception:           # noqa: BLE001
                    pass
        except Exception:                  # noqa: BLE001
            pass

    # ----------------------------- 写入 -----------------------------
    def add(self, text, category="fact"):
        text = (text or "").strip()
        if not self.enabled or not is_safe_entry(text):
            return None
        if category not in CATEGORIES:
            category = "fact"
        # 去重：相同文本只更新权重，不重复存储
        for e in self._entries:
            if e.get("text") == text:
                e["last_used"] = _now()
                e["hits"] = int(e.get("hits", 0)) + 1
                self.save()
                return e.get("id")
        # 容量上限：淘汰命中率最低者
        if len(self._entries) >= MAX_ENTRIES:
            self._entries.sort(key=lambda e: int(e.get("hits", 0)))
            self._entries.pop(0)
        self._seq += 1
        eid = "m%d" % self._seq
        self._entries.append({
            "id": eid, "category": category, "text": text,
            "created": _now(), "last_used": _now(), "hits": 0,
        })
        self.save()
        return eid

    def forget(self, ref):
        """按 id 或文本删除一条记忆。"""
        before = len(self._entries)
        self._entries = [e for e in self._entries
                         if e.get("id") != ref and e.get("text") != ref]
        if len(self._entries) != before:
            self.save()
            return True
        return False

    def clear(self):
        self._entries = []
        self.save()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.save()

    # ----------------------------- 查询 -----------------------------
    def count(self):
        return len(self._entries)

    def list_all(self):
        return list(self._entries)

    def by_category(self, category):
        return [e for e in self._entries if e.get("category") == category]

    def category_counts(self):
        out = {c: 0 for c in CATEGORIES}
        for e in self._entries:
            c = e.get("category")
            if c in out:
                out[c] += 1
        return out

    def relevant(self, query, top_k=5):
        """按词重叠召回与 query 相关的记忆（命中率略加权）。"""
        q = (query or "").lower()
        q_tokens = set(_WORD_RE.findall(q))
        scored = []
        for e in self._entries:
            t = (e.get("text") or "").lower()
            if not q_tokens:
                scored.append((0, e))
                continue
            t_tokens = set(_WORD_RE.findall(t))
            overlap = len(q_tokens & t_tokens)
            if overlap:
                score = overlap + 0.1 * int(e.get("hits", 0))
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:top_k]]

    def build_memory_block(self):
        """拼装为可直接注入系统提示的纯文本块；空库返回空串。"""
        if not self.enabled or not self._entries:
            return ""
        lines = []
        for c in CATEGORIES:
            items = self.by_category(c)
            if items:
                lines.append("%s：%s" % (
                    CATEGORY_LABELS[c],
                    "；".join(e.get("text", "") for e in items)))
        if not lines:
            return ""
        return "【长期记忆】\n" + "\n".join(lines)

    def learn_from_conversation(self, user_text, assistant_text=""):
        """从用户发言启发式抽取记忆，返回新学到的条数。

        assistant_text 仅作签名兼容（记忆只从用户侧学习，避免自我暗示）。
        """
        if not self.enabled or not user_text:
            return 0
        learned = 0
        for line in re.split(r"[\n。.!?！？]", user_text):
            line = line.strip().rstrip("，,;；")
            if not line:
                continue
            for pat, cat in _LEARN_PATTERNS:
                m = pat.match(line)
                if m:
                    if self.add(m.group(1).strip(), cat):
                        learned += 1
                    break
        return learned
