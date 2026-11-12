# -*- coding: utf-8 -*-
"""网络工具包：网页搜索（DuckDuckGo）/ 网页正文读取"""
import re

import requests
from bs4 import BeautifulSoup

from core.agent.tools import tool

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/124.0 Safari/537.36"}


@tool("web_search", "联网搜索：用 DuckDuckGo 搜索并返回标题 / 链接 / 摘要",
      {"type": "object",
       "properties": {
           "query": {"type": "string", "description": "搜索关键词"},
           "max_results": {"type": "integer", "description": "结果数量，默认 5"},
       },
       "required": ["query"]})
def web_search(query, max_results=5):
    q = str(query or "").strip()
    if not q:
        return "错误：搜索关键词为空"
    try:
        r = requests.post("https://html.duckduckgo.com/html/",
                          data={"q": q}, headers=_UA, timeout=20)
    except requests.RequestException as e:
        return "搜索失败（网络错误）：%s" % e
    if r.status_code != 200:
        return "搜索失败：HTTP %d" % r.status_code
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select(".result")[:max(1, int(max_results or 5))]:
        a = res.select_one(".result__a")
        sn = res.select_one(".result__snippet")
        link = res.select_one(".result__a")
        if not a:
            continue
        href = ""
        if link is not None:
            href = link.get("href", "")
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                from urllib.parse import unquote
                href = unquote(m.group(1))
        out.append("· %s\n  %s\n  %s"
                   % (a.get_text(" ", strip=True), href,
                      (sn.get_text(" ", strip=True) if sn else "")))
    if not out:
        return "未找到相关结果（搜索引擎可能有限流，可稍后重试）"
    return "\n".join(out)


@tool("fetch_webpage", "读取一个网页的正文内容（自动去除脚本样式，截断返回）",
      {"type": "object",
       "properties": {
           "url": {"type": "string", "description": "网页链接"},
           "max_chars": {"type": "integer", "description": "最多返回字符数，默认 4000"},
       },
       "required": ["url"]})
def fetch_webpage(url, max_chars=4000):
    u = str(url or "")
    if not u.startswith(("http://", "https://")):
        return "错误：仅支持 http/https 链接"
    try:
        r = requests.get(u, headers=_UA, timeout=20)
    except requests.RequestException as e:
        return "读取失败（网络错误）：%s" % e
    if r.status_code != 200:
        return "读取失败：HTTP %d" % r.status_code
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    limit = max(500, int(max_chars or 4000))
    if len(text) > limit:
        text = text[:limit] + "\n……（内容已截断）"
    return text or "页面没有可提取的正文"
