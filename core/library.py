# -*- coding: utf-8 -*-
"""资料库（知识库）：本地文档导入 + 分块 + TF-IDF 检索。

复刻 WorkBuddy 资料库能力（本地优先，零外部依赖）：
- 导入 txt / md / py / js / json / csv 等文本文件，或直接粘贴文本
- 自动分块（按空行/长度切分，保留可读粒度）
- 纯本地 TF-IDF 检索（中文按字符二元组 + 英文按词，无需嵌入模型）
- 命中片段可注入对话上下文，或经 library_search 工具按需检索

存储：配置目录下 library.json
    {"docs": [{"id", "name", "kind", "size", "created", "chunks": [{"text", "tf"}]}]}
"""
import json

from core import storage
import math
import os
import re
import time

from core.config import get_config_dir

LIBRARY_FILE = "library.json"

# 支持导入的文本类文件扩展名（.pdf/.docx 等二进制格式不在本地解析范围）
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".json", ".csv",
    ".html", ".htm", ".css", ".xml", ".yaml", ".yml", ".ini", ".cfg",
    ".log", ".sql", ".sh", ".bat", ".java", ".c", ".cpp", ".h", ".go",
    ".rs", ".rb", ".php", ".toml",
}

MAX_FILE_SIZE = 2 * 1024 * 1024      # 单文件上限 2MB
CHUNK_TARGET = 600                   # 目标块长（字符）
CHUNK_MAX = 900                      # 块长硬上限
TOP_K_DEFAULT = 3
MIN_SCORE = 0.08                     # 相关性下限（归一化前）

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _tokenize(text):
    """中英混合分词：英文/数字按词，中文按相邻字符二元组。"""
    tokens = []
    for w in _WORD_RE.findall(text or ""):
        tokens.append(w.lower())
    cjk = "".join(_CJK_RE.findall(text or ""))
    if len(cjk) == 1:
        tokens.append(cjk)
    else:
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i:i + 2])
    return tokens


def _split_chunks(text):
    """按空行优先、长度兜底的方式分块。"""
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = re.split(r"\n\s*\n|\r\n\s*\r\n", text)
    chunks, buf = [], ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if buf and len(buf) + len(para) + 2 > CHUNK_TARGET:
            chunks.append(buf)
            buf = ""
        candidate = (buf + "\n\n" + para) if buf else para
        if len(candidate) > CHUNK_MAX:
            if buf:
                chunks.append(buf)
                buf = ""
            # 超长段落按行硬切
            line_buf = ""
            for line in candidate.splitlines():
                if line_buf and len(line_buf) + len(line) + 1 > CHUNK_MAX:
                    chunks.append(line_buf)
                    line_buf = ""
                line_buf = (line_buf + "\n" + line) if line_buf else line
            if line_buf:
                chunks.append(line_buf)
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return chunks


def _term_freq(tokens):
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


class KnowledgeBase:
    """资料库存储与检索（非线程安全：写操作仅在 UI 线程调用）"""

    def __init__(self, path=None):
        self.path = path or os.path.join(get_config_dir(), LIBRARY_FILE)
        self.data = {"docs": []}
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("docs"), list):
                self.data = data
        except Exception:
            self.data = {"docs": []}

    def save(self):
        # 统一走 core.storage 的原子写入（v7.2 去重）
        return storage.save_json(self.path, self.data)

    # ------------------------------------------------------------------
    # 文档管理
    # ------------------------------------------------------------------
    def docs(self):
        """文档摘要列表（不含分块内容）"""
        out = []
        for d in self.data.get("docs") or []:
            out.append({
                "id": d.get("id", ""),
                "name": d.get("name", "未命名"),
                "kind": d.get("kind", "text"),
                "size": int(d.get("size", 0)),
                "created": d.get("created", 0),
                "chunks": len(d.get("chunks") or []),
            })
        out.sort(key=lambda x: -int(x.get("created") or 0))
        return out

    def add_text(self, name, text):
        """粘贴文本导入；返回文档 id（内容为空返回 None）"""
        text = (text or "").strip()
        if not text:
            return None
        chunks = _split_chunks(text)
        if not chunks:
            return None
        doc = {"id": "d_%d_%s" % (int(time.time()), os.urandom(3).hex()),
               "name": (name or "未命名文档").strip()[:60] or "未命名文档",
               "kind": "text",
               "size": len(text),
               "created": int(time.time()),
               "chunks": [{"text": c, "tf": _term_freq(_tokenize(c))}
                          for c in chunks]}
        self.data.setdefault("docs", []).append(doc)
        self.save()
        return doc["id"]

    def add_file(self, path):
        """从文件导入；返回 (doc_id, error)。成功时 error 为 None。"""
        p = os.path.expanduser(str(path or ""))
        if not os.path.isfile(p):
            return None, "文件不存在：%s" % p
        ext = os.path.splitext(p)[1].lower()
        if ext not in TEXT_EXTENSIONS:
            return None, "不支持的格式 %s（仅文本类文件）" % ext
        try:
            if os.path.getsize(p) > MAX_FILE_SIZE:
                return None, "文件超过 2MB 上限"
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:  # noqa: BLE001
            return None, "读取失败：%s" % e
        doc_id = self.add_text(os.path.basename(p), text)
        if doc_id is None:
            return None, "文件内容为空"
        for d in self.data["docs"]:
            if d["id"] == doc_id:
                d["kind"] = "file"
        self.save()
        return doc_id, None

    def remove(self, doc_id):
        before = len(self.data.get("docs") or [])
        self.data["docs"] = [d for d in self.data.get("docs") or []
                             if d.get("id") != doc_id]
        if len(self.data["docs"]) != before:
            self.save()
            return True
        return False

    def clear(self):
        self.data["docs"] = []
        self.save()

    def total_chunks(self):
        return sum(len(d.get("chunks") or []) for d in self.data.get("docs") or [])

    # ------------------------------------------------------------------
    # 检索（TF-IDF，只读，可在工作线程调用）
    # ------------------------------------------------------------------
    def search(self, query, top_k=TOP_K_DEFAULT, min_score=MIN_SCORE):
        """返回 [{doc, text, score}]，按相关度降序。"""
        q_terms = set(_tokenize(query))
        if not q_terms or not self.data.get("docs"):
            return []
        # 文档频率
        df = {}
        for d in self.data["docs"]:
            terms = set()
            for c in d.get("chunks") or []:
                terms.update((c.get("tf") or {}).keys())
            for t in terms:
                df[t] = df.get(t, 0) + 1
        n_docs = max(1, len(self.data["docs"]))
        idf = {t: math.log((n_docs + 1) / (df.get(t, 0) + 1)) + 1.0
               for t in q_terms}

        scored = []
        for d in self.data["docs"]:
            for c in d.get("chunks") or []:
                tf = c.get("tf") or {}
                score = 0.0
                for t in q_terms:
                    f = tf.get(t, 0)
                    if f:
                        score += (1.0 + math.log(f)) * idf[t]
                if score >= min_score:
                    scored.append({"doc": d.get("name", ""),
                                   "doc_id": d.get("id", ""),
                                   "text": c.get("text", ""),
                                   "score": round(score, 4)})
        scored.sort(key=lambda x: -x["score"])
        return scored[:max(1, int(top_k))]

    def context_for(self, query, max_chars=1500, top_k=TOP_K_DEFAULT):
        """为对话生成「参考资料」上下文块（无命中返回空串）。"""
        hits = self.search(query, top_k=top_k)
        if not hits:
            return ""
        parts, used = [], 0
        for h in hits:
            snippet = h["text"]
            if used + len(snippet) > max_chars:
                snippet = snippet[:max(0, max_chars - used)]
            if not snippet:
                break
            parts.append("【%s】\n%s" % (h["doc"], snippet))
            used += len(snippet)
            if used >= max_chars:
                break
        if not parts:
            return ""
        return ("以下来自用户资料库的相关内容，回答时请优先参考"
                "（与问题无关时忽略）：\n\n" + "\n\n---\n\n".join(parts))

    def citations_for(self, query, top_k=None, max_sources=8, excerpt=120):
        """v13.3 · 来源引用清单（借鉴 AnythingLLM 的 source citations）。

        context_for 负责把资料内容塞进提示词，本方法负责把「到底引用了哪些
        文档」回显给用户，让回答可溯源、可核对。按 doc_id 去重，一个文档
        只出现一次（取最相关片段作为摘录）。
        返回 [{doc, doc_id, score, excerpt, chunks}]。
        """
        k = max(int(top_k or TOP_K_DEFAULT) * 2, 8)
        try:
            hits = self.search(query, top_k=k)
        except Exception:                               # noqa: BLE001
            return []
        merged = {}
        for h in hits or []:
            key = h.get("doc_id") or h.get("doc") or ""
            if not key:
                continue
            text = " ".join((h.get("text") or "").split())
            if key not in merged:
                merged[key] = {
                    "doc": h.get("doc") or "资料",
                    "doc_id": key,
                    "score": h.get("score", 0),
                    "excerpt": text[:max(0, int(excerpt))],
                    "chunks": 1,
                }
            else:
                merged[key]["chunks"] += 1
                merged[key]["score"] = max(merged[key]["score"],
                                           h.get("score", 0))
        out = list(merged.values())
        out.sort(key=lambda x: -x["score"])
        return out[:max(1, int(max_sources))]


def format_citations(citations, with_excerpt=False):
    """把来源清单渲染成可读文本（CLI / 对话框 / 复制到剪贴板）。"""
    rows = list(citations or [])
    if not rows:
        return "本轮回答没有引用资料库内容。"
    lines = ["本轮回答参考了 %d 份资料：" % len(rows)]
    for i, c in enumerate(rows, 1):
        lines.append("  %d. %s%s" % (
            i, c.get("doc", "资料"),
            ("（相关片段 %d 处）" % c.get("chunks", 1)
             if c.get("chunks", 1) > 1 else "")))
        if with_excerpt and c.get("excerpt"):
            lines.append("     %s%s" % (c["excerpt"][:100],
                                        "…" if len(c["excerpt"]) > 100 else ""))
    return "\n".join(lines)
