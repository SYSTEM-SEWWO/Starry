# -*- coding: utf-8 -*-
"""资料库工具包：检索用户导入的本地文档（知识库）。

工具经模块级存储钩子访问 KnowledgeBase 实例（由应用层启动时注入），
检索为只读操作，可在智能体工作线程中安全调用。
"""
from core.agent.tools import tool

_STORE = None          # 当前资料库实例（应用层注入）


def set_store(store):
    """注入 / 清除资料库实例（传 None 表示停用）"""
    global _STORE
    _STORE = store


@tool("search_library",
      "检索用户资料库中导入的文档，返回与问题最相关的片段。"
      "当用户提问涉及他导入的资料/文档/笔记时应优先使用",
      {"type": "object",
       "properties": {
           "query": {"type": "string",
                     "description": "检索关键词或问题（支持中英文）"},
           "top_k": {"type": "integer",
                     "description": "返回片段数量，默认 3，最大 5"}},
       "required": ["query"]})
def search_library(query, top_k=3):
    if _STORE is None:
        return "资料库未启用（用户尚未导入任何文档）"
    q = str(query or "").strip()
    if not q:
        return "错误：检索词不能为空"
    try:
        k = max(1, min(5, int(top_k)))
    except (TypeError, ValueError):
        k = 3
    hits = _STORE.search(q, top_k=k)
    if not hits:
        return "资料库中未找到与「%s」相关的内容" % q
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append("%d. 【%s】(相关度 %.2f)\n%s"
                     % (i, h.get("doc", ""), h.get("score", 0),
                        h.get("text", "")))
    return "\n\n".join(parts)
