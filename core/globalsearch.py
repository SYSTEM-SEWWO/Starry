# -*- coding: utf-8 -*-
"""跨数据源全局搜索（v13.3）。

借鉴 Cherry Studio「find content across your conversations and knowledge
bases」：把散落在会话、资料库、提示词库、长期记忆、收藏夹里的内容用一把
搜索框统一召回，而不是让用户分别打开五个窗口去找。

设计原则：
- 纯逻辑、零第三方依赖，桌面端 / CLI / 安卓可同源复用；
- 各数据源以「鸭子类型」注入（只要有对应方法即可），缺哪个跳过哪个，
  单个数据源异常不影响整体结果，搜索永不抛错；
- 不同数据源的评分量纲不同（会话是词频整数、资料库是 tf-idf 小数），
  因此先在各数据源内部按排名归一化，再全局混排，避免某一源刷屏。
"""
import re

SOURCE_LABELS = {
    "session": "会话",
    "library": "资料库",
    "prompt": "提示词",
    "memory": "长期记忆",
    "starred": "收藏",
}
SOURCE_ICONS = {
    "session": "🗂",
    "library": "📚",
    "prompt": "📖",
    "memory": "🧠",
    "starred": "⭐",
}
ALL_SOURCES = tuple(SOURCE_LABELS)

_WORD_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")
_SAFE_QUERY_MAX = 200


def tokenize(text):
    """中英文分词：英文按词、中文按单字，并补上中文二元组提升精度。"""
    s = (text or "").lower().strip()[:_SAFE_QUERY_MAX]
    if not s:
        return []
    parts = _WORD_RE.findall(s)
    tokens = list(parts)
    # 中文相邻字组成 bigram，减少「人工智能」被「人工」「智能」误召回
    for i in range(len(parts) - 1):
        a, b = parts[i], parts[i + 1]
        if "\u4e00" <= a <= "\u9fff" and "\u4e00" <= b <= "\u9fff":
            tokens.append(a + b)
    return tokens


def score_text(text, tokens, qlow):
    """对一段文本打分：整串命中 > 词频；标题由调用方另行加权。"""
    s = (text or "").lower()
    if not s or not tokens:
        return 0.0
    score = 0.0
    for t in set(tokens):
        w = 0.25 if (len(t) == 1 and "\u4e00" <= t <= "\u9fff") else 1.0
        score += s.count(t) * (2.0 if len(t) > 1 else 1.0) * w
    if qlow and qlow in s:
        score += 8.0
    return score


def snippet(text, query, width=64):
    """截取命中词附近的上下文，两端用 … 标记。"""
    s = " ".join((text or "").split())
    if not s:
        return ""
    q = (query or "").strip().lower()
    pos = s.lower().find(q) if q else -1
    if pos < 0:
        toks = tokenize(query)
        for t in toks:
            pos = s.lower().find(t)
            if pos >= 0:
                break
    if pos < 0:
        return s[:width] + ("…" if len(s) > width else "")
    start = max(0, pos - width // 3)
    end = min(len(s), start + width)
    return ("…" if start > 0 else "") + s[start:end] + ("…" if end < len(s) else "")


def _rank_normalize(rows, key="score"):
    """把同一数据源内按名次映射到 100→60，保留原始分的相对次序。"""
    if not rows:
        return rows
    for i, row in enumerate(rows):
        row["_rank_score"] = max(60.0, 100.0 - i * 3.0)
    return rows


def _mk(source, title, text, score, ref, icon=None, label=None):
    return {
        "source": source,
        "label": label or SOURCE_LABELS.get(source, source),
        "icon": icon or SOURCE_ICONS.get(source, "•"),
        "title": title or "未命名",
        "snippet": text or "",
        "score": round(float(score or 0.0), 4),
        "ref": dict(ref or {}),
    }


# ---------------------------------------------------------------------------
# 各数据源适配器：只依赖对象方法，失败一律返回空列表
# ---------------------------------------------------------------------------
def _search_sessions(store, query, tokens, qlow, per_source):
    if store is None or not hasattr(store, "search_ranked"):
        return []
    try:
        hits = store.search_ranked(query, top_k=per_source) or []
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    for h in hits:
        out.append(_mk(
            "session", h.get("title", "未命名"),
            h.get("snippet") or snippet(h.get("title", ""), query),
            h.get("score", 0),
            {"type": "session", "id": h.get("id", ""),
             "tags": h.get("tags") or []},
        ))
    return out


def _search_library(kb, query, tokens, qlow, per_source):
    if kb is None or not hasattr(kb, "search"):
        return []
    try:
        hits = kb.search(query, top_k=per_source) or []
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    seen = set()
    for h in hits:
        doc = h.get("doc") or "资料"
        key = h.get("doc_id") or doc
        if key in seen:            # 同一文档多片段命中只展示最相关的一条
            continue
        seen.add(key)
        out.append(_mk(
            "library", doc, snippet(h.get("text", ""), query),
            h.get("score", 0),
            {"type": "library", "doc_id": h.get("doc_id", ""), "doc": doc},
        ))
    return out


def _search_prompts(pl, query, tokens, qlow, per_source):
    if pl is None or not hasattr(pl, "search"):
        return []
    try:
        hits = pl.search(query) or []
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    for p in hits[:per_source]:
        title = p.get("title") or "未命名提示词"
        content = p.get("content") or ""
        sc = score_text(title, tokens, qlow) * 3 + score_text(content, tokens, qlow)
        out.append(_mk(
            "prompt", title, snippet(content, query), sc,
            {"type": "prompt", "id": p.get("id", "")},
        ))
    out.sort(key=lambda x: -x["score"])
    return out


def _search_memory(mem, query, tokens, qlow, per_source):
    if mem is None or not hasattr(mem, "relevant"):
        return []
    try:
        hits = mem.relevant(query, top_k=per_source) or []
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    for e in hits:
        text = e.get("text") or ""
        sc = score_text(text, tokens, qlow)
        if sc <= 0:
            continue
        out.append(_mk("memory", text[:40], snippet(text, query), sc,
                       {"type": "memory", "ref": e.get("ref", "")}))
    return out


def _search_starred(store, query, tokens, qlow, per_source):
    if store is None or not hasattr(store, "list_starred"):
        return []
    try:
        all_starred = store.list_starred() or []
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    for m in all_starred:
        text = m.get("content") or ""
        sc = (score_text(text, tokens, qlow)
              + score_text(m.get("title", ""), tokens, qlow) * 2)
        if sc <= 0:
            continue
        out.append(_mk(
            "starred", m.get("title") or "收藏消息",
            snippet(text, query), sc,
            {"type": "starred", "session_id": m.get("session_id", ""),
             "index": m.get("index", 0)},
        ))
    out.sort(key=lambda x: -x["score"])
    return out[:per_source]


_ADAPTERS = {
    "session": _search_sessions,
    "library": _search_library,
    "prompt": _search_prompts,
    "memory": _search_memory,
    "starred": _search_starred,
}


def search_all(query, sessions=None, library=None, prompts=None, memory=None,
               sources=None, top_k=60, per_source=20):
    """统一检索入口。

    query      : 用户输入的关键词（为空返回 []）
    sessions   : core.sessions.SessionStore（同时用于「收藏」源）
    library    : core.library.KnowledgeBase
    prompts    : core.prompts.PromptLibrary
    memory     : core.memory.MemoryStore
    sources    : 只搜这些数据源（None = 全部）
    top_k      : 全局返回上限
    per_source : 每个数据源最多取多少条

    返回 [{source, label, icon, title, snippet, score, ref}]，按相关性降序。
    """
    q = (query or "").strip()
    if not q:
        return []
    tokens = tokenize(q)
    if not tokens:
        return []
    qlow = q.lower()
    wanted = [s for s in ALL_SOURCES
              if sources is None or s in (sources or ())]
    stores = {
        "session": sessions, "library": library, "prompt": prompts,
        "memory": memory, "starred": sessions,
    }
    results = []
    for src in wanted:
        try:
            rows = _ADAPTERS[src](stores.get(src), q, tokens, qlow,
                                  max(1, int(per_source)))
        except Exception:                               # noqa: BLE001
            rows = []
        _rank_normalize(rows)
        results.extend(rows)
    for r in results:
        r["score"] = round(r.pop("_rank_score", r["score"])
                           + min(20.0, r.get("score", 0) * 0.1), 4)
    results.sort(key=lambda x: (-x["score"], x["source"], x["title"]))
    return results[:max(1, int(top_k))]


def grouped(results):
    """把结果按数据源分组（UI 分组展示用），保持组内原排序。"""
    groups = {}
    for r in results or []:
        groups.setdefault(r.get("source", "other"), []).append(r)
    return groups


def source_counts(results):
    """各数据源命中数，用于 UI 角标。"""
    counts = {s: 0 for s in ALL_SOURCES}
    for r in results or []:
        src = r.get("source")
        if src in counts:
            counts[src] += 1
    return counts


def format_results(results, limit=20):
    """纯文本渲染（CLI / 复制 / 无障碍场景）。"""
    if not results:
        return "未找到匹配内容。"
    lines = []
    for r in results[:max(1, int(limit))]:
        lines.append("%s [%s] %s" % (r["icon"], r["label"], r["title"]))
        if r.get("snippet"):
            lines.append("    %s" % r["snippet"])
    return "\n".join(lines)
