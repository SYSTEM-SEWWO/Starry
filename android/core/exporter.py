# -*- coding: utf-8 -*-
"""对话导出：把消息历史转换为 Markdown 文本。

纯函数模块（无 Qt 依赖）：UI 层只负责弹保存框与写文件，
格式转换在此完成，便于测试与复用。
"""
import datetime
import json as _json
import io
import zipfile

from core.sessions import message_text


def _esc(s):
    """HTML 转义，防止导出的对话内容破坏页面结构。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def conversation_to_markdown(history, title="AI 对话记录",
                             model="", provider_name=""):
    """把 messages 列表渲染为 Markdown 文本。

    history: [{"role": "system"|"user"|"assistant", "content": str | list}, ...]
    返回完整 Markdown 字符串。
    """
    lines = [
        "# %s" % (title or "AI 对话记录"),
        "",
        "> 导出时间：%s ｜ 模型：%s ｜ 服务商：%s"
        % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           model or "未选择",
           provider_name or "未知"),
        "",
    ]
    for m in history:
        role = m.get("role")
        text = message_text(m)
        if role == "system":
            if text.strip():
                lines.append("> 系统提示：%s" % text.strip())
                lines.append("")
        elif role == "user":
            lines.append("## 🧑 我")
            lines.append("")
            lines.append(text or "（空）")
            lines.append("")
        elif role == "assistant" and text.strip():
            lines.append("## ✦ AI")
            lines.append("")
            lines.append(text)
            lines.append("")
    return "\n".join(lines)


def conversation_to_json(history, title="AI 对话记录",
                         model="", provider_name=""):
    """导出为结构化 JSON（便于二次处理 / 程序消费）。"""
    return _json.dumps({
        "title": title,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "provider": provider_name,
        "messages": [
            {"role": m.get("role"), "content": message_text(m)}
            for m in history
        ],
    }, ensure_ascii=False, indent=2)


def conversation_to_text(history, title="AI 对话记录",
                         model="", provider_name=""):
    """导出为纯文本 .txt（无格式，兼容所有编辑器）。"""
    lines = [
        title or "AI 对话记录",
        "导出时间：%s  模型：%s  服务商：%s"
        % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           model or "未选择", provider_name or "未知"),
        "=" * 40,
    ]
    for m in history:
        role = m.get("role")
        text = message_text(m)
        if role == "system":
            if text.strip():
                lines.append("[系统提示] %s" % text.strip())
        elif role == "user":
            lines.append("【我】%s" % (text or ""))
        elif role == "assistant" and text.strip():
            lines.append("【AI】%s" % text)
        lines.append("")
    return "\n".join(lines)


def conversation_to_html(history, title="AI 对话记录",
                         model="", provider_name=""):
    """导出为带样式的 HTML（可直接浏览器打开 / 分享）。"""
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s</title>" % _esc(title),
        "<style>",
        "body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
        "max-width:780px;margin:28px auto;padding:0 18px;color:#1f2329;"
        "line-height:1.75;background:#fafbfc}",
        ".meta{color:#8a9099;font-size:13px;border-bottom:1px solid #eef0f2;"
        "padding-bottom:10px;margin-bottom:18px}",
        ".sys{color:#8a9099;font-style:italic;background:#f3f5f7;"
        "padding:8px 12px;border-radius:8px;margin:10px 0}",
        ".user{font-weight:600;color:#1f6feb;margin-top:18px}",
        ".ai{background:#fff;border:1px solid #eef0f2;border-radius:10px;"
        "padding:12px 14px;margin:6px 0 14px;white-space:pre-wrap}",
        "h1{font-size:22px;margin:0 0 4px}",
        "</style></head><body>",
        "<h1>%s</h1>" % _esc(title),
        '<div class="meta">导出时间：%s ｜ 模型：%s ｜ 服务商：%s</div>'
        % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           _esc(model or "未选择"), _esc(provider_name or "未知")),
    ]
    for m in history:
        role = m.get("role")
        text = message_text(m)
        if role == "system":
            if text.strip():
                parts.append('<div class="sys">系统提示：%s</div>' % _esc(text.strip()))
        elif role == "user":
            parts.append('<div class="user">🧑 我</div>')
            parts.append('<div class="ai">%s</div>' % _esc(text or ""))
        elif role == "assistant" and text.strip():
            parts.append('<div class="user">✦ AI</div>')
            parts.append('<div class="ai">%s</div>' % _esc(text))
    parts.append("</body></html>")
    return "\n".join(parts)


def conversation_to_pdf(history, title="AI 对话记录",
                        model="", provider_name=""):
    """导出为 PDF（V11.2 新增）：复用 HTML 版式，由 WeasyPrint 渲染。

    返回 PDF 字节流（bytes），便于直接落盘或网络传输。
    需要可选依赖 weasyprint；未安装时抛出明确提示（安卓端默认不内置）。
    """
    try:
        import weasyprint
    except Exception:
        raise RuntimeError(
            "PDF 导出需要可选依赖 weasyprint：pip install weasyprint")
    html = conversation_to_html(history, title=title, model=model,
                               provider_name=provider_name)
    return weasyprint.HTML(string=html).write_pdf()


def _pdf_available():
    """环境是否支持 PDF 导出（决定 UI 是否展示该选项，避免安卓端误暴露）。"""
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


# 导出格式注册表（UI 下拉 / CLI 共用）
EXPORT_FORMATS = {
    "markdown": ("Markdown", ".md", conversation_to_markdown),
    "json": ("JSON", ".json", conversation_to_json),
    "text": ("纯文本", ".txt", conversation_to_text),
    "html": ("HTML", ".html", conversation_to_html),
}
if _pdf_available():
    EXPORT_FORMATS["pdf"] = ("PDF", ".pdf", conversation_to_pdf)


def available_formats():
    """当前环境可用的导出格式键列表（顺序稳定）。"""
    return list(EXPORT_FORMATS.keys())


def export_conversation(history, fmt="markdown", **kwargs):
    """统一导出入口：fmt ∈ {markdown,json,text,html,pdf}。

    pdf 返回字节流（bytes），其余返回字符串。
    """
    entry = EXPORT_FORMATS.get(fmt, EXPORT_FORMATS["markdown"])
    return entry[2](history, **kwargs)


# ----------------------------------------------------------------------
# V11.3：批量导出全部会话
# ----------------------------------------------------------------------
def session_block_markdown(session):
    """把单个会话渲染为 Markdown 章节（标题 + 元信息 + 正文）。"""
    title = session.get("title") or "未命名"
    tags = session.get("tags") or []
    tag_str = ("  ｜ 标签：" + "、".join(tags)) if tags else ""
    summary = (session.get("summary") or "").strip()
    lines = [
        "## %s" % title,
        "",
        "> 更新：%s%s" % (
            datetime.datetime.fromtimestamp(session.get("updated", 0)
                                             or _now0()).strftime("%Y-%m-%d %H:%M")
            if session.get("updated") else "—", tag_str),
        "",
    ]
    if summary:
        lines += ["> 摘要：%s" % summary, ""]
    for m in (session.get("messages") or []):
        role = m.get("role")
        text = message_text(m)
        if role == "system":
            if text.strip():
                lines.append("> 系统提示：%s" % text.strip())
                lines.append("")
        elif role == "user":
            lines.append("### 🧑 我")
            lines.append("")
            lines.append(text or "（空）")
            lines.append("")
        elif role == "assistant" and text.strip():
            lines.append("### ✦ AI")
            lines.append("")
            lines.append(text)
            lines.append("")
    return "\n".join(lines)


def _now0():
    return int(datetime.datetime.now().timestamp())


def export_all_sessions(store, fmt="markdown", title="星语 Starry · 全部会话"):
    """V11.3：把存储里的全部会话合并导出。

    fmt ∈ {markdown, json, text, html}：返回 (字符串, 扩展名)。
    fmt == "zip"：返回 (bytes, ".zip")，内含每会话一个独立文件 + index.md。
    """
    sessions = store._sessions() if hasattr(store, "_sessions") else \
        (store.data.get("sessions") if hasattr(store, "data") else [])
    sessions = list(sessions)

    if fmt == "zip":
        return _export_all_zip(sessions, title), ".zip"

    if fmt == "json":
        content = _json.dumps({
            "title": title,
            "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "sessions": [
                {"id": s.get("id"), "title": s.get("title"),
                 "tags": s.get("tags") or [], "summary": s.get("summary") or "",
                 "messages": [{"role": m.get("role"),
                               "content": message_text(m)}
                              for m in (s.get("messages") or [])]}
                for s in sessions
            ],
        }, ensure_ascii=False, indent=2)
        return content, ".json"

    # 逐会话渲染后拼接
    blocks = ["# %s" % title,
              "",
              "> 共 %d 个会话 ｜ 导出时间：%s"
              % (len(sessions),
                 datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
              ""]
    for s in sessions:
        blocks.append(session_block_markdown(s))
        blocks.append("")
        blocks.append("---")
        blocks.append("")
    combined = "\n".join(blocks)

    if fmt == "html":
        return _combined_to_html(combined, title), ".html"
    if fmt == "text":
        return _combined_to_text(combined, title), ".txt"
    return combined, ".md"


def _combined_to_html(md_like, title):
    """极简 Markdown→HTML（标题/引用/分隔线/段落），够导出阅读即可。"""
    esc = lambda s: (str(s).replace("&", "&amp;").replace("<", "&lt;")
                     .replace(">", "&gt;"))
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
             '<title>%s</title><style>body{font-family:-apple-system,'
             "'PingFang SC','Microsoft YaHei',sans-serif;max-width:820px;"
             "margin:28px auto;padding:0 18px;color:#1f2329;line-height:1.7}"
             "h1,h2,h3{line-height:1.3}.meta{color:#8a9099;font-size:13px}"
             "blockquote{color:#8a9099;border-left:3px solid #e3e6ea;"
             "margin:8px 0;padding:2px 12px}hr{border:none;border-top:1px "
             "solid #eef0f2}</style></head><body>"
             "<h1>%s</h1>" % (esc(title), esc(title))]
    for line in md_like.splitlines():
        if line.startswith("## "):
            parts.append("<h2>%s</h2>" % esc(line[3:]))
        elif line.startswith("### "):
            parts.append("<h3>%s</h3>" % esc(line[4:]))
        elif line.startswith("> "):
            parts.append("<blockquote>%s</blockquote>" % esc(line[2:]))
        elif line.strip() == "---":
            parts.append("<hr>")
        elif line.strip():
            parts.append("<p>%s</p>" % esc(line))
    parts.append("</body></html>")
    return "\n".join(parts)


def _combined_to_text(md_like, title):
    lines = [title, "=" * 40]
    for line in md_like.splitlines():
        if line.startswith("## "):
            lines.append("\n【%s】" % line[3:])
        elif line.startswith("### "):
            lines.append(line[4:])
        elif line.startswith("> "):
            lines.append(line[2:])
        elif line.strip() == "---":
            lines.append("-" * 40)
        elif line.strip():
            lines.append(line)
    return "\n".join(lines)


def _export_all_zip(sessions, title):
    """把每个会话导出为独立 .md，并附 index.md，打包成 zip 字节流。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        index = ["# %s —— 会话索引" % title, "",
                 "> 共 %d 个会话" % len(sessions), ""]
        for i, s in enumerate(sessions, 1):
            fname = "session_%02d_%s.md" % (i, (s.get("id") or "x")[:8])
            zf.writestr(fname, session_block_markdown(s))
            index.append("- [%s](%s)" % (s.get("title") or "未命名", fname))
        zf.writestr("index.md", "\n".join(index))
    return buf.getvalue()
