# -*- coding: utf-8 -*-
"""Markdown → Qt 富文本(HTML) 转换。

使用 markdown 库生成 HTML，再用 BeautifulSoup 做两件事：
1. 安全清洗（移除 script/style/iframe 等危险标签与 on* 事件属性）
2. 注入内联样式（Qt 富文本引擎对 CSS 支持有限，内联样式最可靠）
"""
import html as _html
import re

import markdown as _md
from bs4 import BeautifulSoup

_MD_EXTENSIONS = ["fenced_code", "tables", "nl2br", "sane_lists"]

# v13.3 · 代码块语言标签 / Mermaid 图表源码（借鉴 Cherry Studio）
_LANG_CLASS_RE = re.compile(r"^language-([A-Za-z0-9_+#.\-]{1,32})$")
_MERMAID_LANGS = {"mermaid", "mmd"}
_FENCE_RE = re.compile(r"(?P<fence>`{3}|~{3})([^\n]*)\n(.*?)(?P=fence)", re.S)


_DANGER_TAGS = ["script", "style", "iframe", "object", "embed",
                "form", "input", "button", "link", "meta", "video", "audio"]

_MONO = "Consolas,'JetBrains Mono','DejaVu Sans Mono','Courier New',monospace"


def _styles_for(theme, fs):
    s = int(fs)
    return {
        "p": "margin:4px 0;line-height:1.55;",
        "h1": "font-size:%dpx;margin:10px 0 6px;color:%s;font-weight:bold;" % (s + 6, theme["accent"]),
        "h2": "font-size:%dpx;margin:9px 0 5px;color:%s;font-weight:bold;" % (s + 4, theme["accent"]),
        "h3": "font-size:%dpx;margin:8px 0 4px;color:%s;font-weight:bold;" % (s + 2, theme["text"]),
        "h4": "font-size:%dpx;margin:8px 0 4px;color:%s;font-weight:bold;" % (s + 1, theme["text"]),
        "h5": "font-size:%dpx;margin:8px 0 4px;color:%s;font-weight:bold;" % (s, theme["text"]),
        "h6": "font-size:%dpx;margin:8px 0 4px;color:%s;font-weight:bold;" % (s, theme["muted"]),
        "ul": "margin:4px 0;",
        "ol": "margin:4px 0;",
        "li": "margin:2px 0;",
        "pre": ("background-color:%s;border:1px solid %s;border-radius:8px;"
                "padding:10px 12px;margin:6px 0;color:%s;font-family:%s;"
                % (theme["code_bg"], theme["border"], theme["code_text"], _MONO)),
        "code": ("background-color:%s;color:%s;border-radius:4px;padding:1px 5px;"
                 "font-family:%s;" % (theme["code_bg"], theme["code_text"], _MONO)),
        "blockquote": ("margin:6px 0;padding:2px 10px;border-left:3px solid %s;"
                       "color:%s;" % (theme["accent"], theme["muted"])),
        "table": "border-collapse:collapse;margin:6px 0;",
        "th": "border:1px solid %s;padding:4px 10px;background-color:%s;" % (theme["border"], theme["code_bg"]),
        "td": "border:1px solid %s;padding:4px 10px;" % theme["border"],
        "hr": "border:none;border-top:1px solid %s;margin:8px 0;" % theme["border"],
        "a": "color:%s;text-decoration:none;" % theme["link"],
    }


def _sanitize(soup):
    for tag in soup.find_all(_DANGER_TAGS):
        tag.decompose()
    for el in soup.find_all(True):
        for attr in list(el.attrs.keys()):
            if attr.lower().startswith("on"):
                del el[attr]
    return soup


def markdown_to_qt_html(text, theme, font_size=14):
    """把 Markdown 文本转换为 Qt 富文本可渲染的 HTML。

    theme: ui.theme.THEMES 中的主题字典（需包含 text/accent/code_bg 等键）
    """
    if not text or not text.strip():
        return ""
    html = _md.markdown(text, extensions=_MD_EXTENSIONS)
    soup = _sanitize(BeautifulSoup(html, "html.parser"))

    styles = _styles_for(theme, font_size)
    for tag_name, style in styles.items():
        if tag_name in ("code", "a"):
            continue
        for el in soup.find_all(tag_name):
            existing = el.get("style", "")
            el["style"] = (existing + ";" if existing else "") + style

    # 内联 code（跳过 pre 内的，由 pre 统一样式）
    for el in soup.find_all("code"):
        if el.parent is not None and el.parent.name == "pre":
            continue
        existing = el.get("style", "")
        el["style"] = (existing + ";" if existing else "") + styles["code"]

    for el in soup.find_all("a"):
        existing = el.get("style", "")
        el["style"] = (existing + ";" if existing else "") + styles["a"]
        el["target"] = "_blank"

    # v13.3：给围栏代码块加语言标签。Mermaid / mmd 单独标注为「图表源码」，
    # 让 AI 输出的流程图不再是一坨看不懂的纯文本（Cherry Studio 的做法）。
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        if code is None:
            continue
        lang = ""
        for cls in code.get("class") or []:
            m = _LANG_CLASS_RE.match(cls or "")
            if m:
                lang = m.group(1)
                break
        label = lang or "text"
        is_chart = label.lower() in _MERMAID_LANGS
        badge = soup.new_tag("div")
        badge["style"] = (
            "font-family:%s;font-size:%dpx;color:%s;opacity:0.85;"
            "padding:2px 2px 3px 10px;" % (
                _MONO, max(10, int(font_size) - 3),
                theme.get("muted", "#8b93a1")))
        badge.string = ("%s %s · 图表源码（可导出 .mmd 或粘贴到 Mermaid Live）"
                        % ("📊", _html.escape(label)) if is_chart
                        else _html.escape(label))
        pre.insert_before(badge)
        if is_chart:
            pre["style"] = (pre.get("style", "")
                            + "background-color:%s;" % theme.get("code_bg", "#f5f6f8"))

    body = str(soup)
    return ('<div style="font-size:%dpx;color:%s;">%s</div>'
            % (int(font_size), theme.get("text", "#e8e9ee"), body))


def strip_markdown(text):
    """把 Markdown 粗略转为纯文本（用于剪贴板等场景的兜底）"""
    if not text:
        return ""
    t = re.sub(r"```.*?```", lambda m: m.group(0).strip("`"), text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\*\*([^*]*)\*\*", r"\1", t)
    t = re.sub(r"__([^_]*)__", r"\1", t)
    t = re.sub(r"(?<!\w)\*([^*]*)\*(?!\w)", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    return t


# ---------------------------------------------------------------------------
# v13.3 · 代码块提取（复制 / 导出 / Mermaid 图表）
# ---------------------------------------------------------------------------
def extract_code_blocks(text):
    """从原始 Markdown 中提取围栏代码块。

    返回 [{index, lang, code, is_mermaid}]；lang 缺省为 "text"。
    供「复制代码」「导出 Mermaid .mmd」「产物预览」等功能复用。
    """
    out = []
    for i, m in enumerate(_FENCE_RE.finditer(text or "")):
        bits = (m.group(2) or "").strip().split()
        lang = bits[0] if bits else ""
        code = (m.group(3) or "").strip("\n")
        out.append({
            "index": i,
            "lang": lang or "text",
            "code": code,
            "is_mermaid": (lang or "").lower() in _MERMAID_LANGS,
        })
    return out


def mermaid_blocks(text):
    """只返回图表源码块（Mermaid / mmd），供导出或粘贴到 Mermaid Live。"""
    return [b for b in extract_code_blocks(text) if b["is_mermaid"]]


def code_block_languages(text):
    """统计各语言代码块数量，用于「本次回答含 3 个代码块」类提示。"""
    counts = {}
    for b in extract_code_blocks(text):
        counts[b["lang"]] = counts.get(b["lang"], 0) + 1
    return counts
