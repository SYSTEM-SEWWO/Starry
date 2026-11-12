# -*- coding: utf-8 -*-
"""文件工具包：读取文本文件 / 浏览目录（带路径安全提示）"""
import os

from core.agent.tools import tool

_TEXT_EXTS = {".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml",
              ".html", ".htm", ".css", ".js", ".ts", ".java", ".c", ".cpp",
              ".h", ".go", ".rs", ".sh", ".sql", ".xml", ".toml", ".ini", ".cfg"}


@tool("read_text_file", "读取本地文本文件内容（自动识别编码，超长截断）",
      {"type": "object",
       "properties": {
           "path": {"type": "string", "description": "文件路径"},
           "max_chars": {"type": "integer", "description": "最多返回字符数，默认 6000"},
       },
       "required": ["path"]})
def read_text_file(path, max_chars=6000):
    p = os.path.expanduser(str(path or ""))
    if not os.path.isfile(p):
        return "错误：文件不存在：%s" % p
    if os.path.getsize(p) > 5 * 1024 * 1024:
        return "错误：文件过大（>5MB）"
    data = None
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            with open(p, "r", encoding=enc) as f:
                data = f.read()
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if data is None:
        return "错误：无法解码文件内容"
    limit = max(500, int(max_chars or 6000))
    if len(data) > limit:
        data = data[:limit] + "\n……（内容已截断，共 %d 字符）" % len(data)
    return data


@tool("list_directory", "列出目录下的文件与文件夹",
      {"type": "object",
       "properties": {"path": {"type": "string", "description": "目录路径，默认当前目录"}},
       })
def list_directory(path="."):
    p = os.path.expanduser(str(path or "."))
    if not os.path.isdir(p):
        return "错误：目录不存在：%s" % p
    try:
        entries = sorted(os.listdir(p))
    except OSError as e:
        return "错误：%s" % e
    lines = []
    for name in entries[:100]:
        full = os.path.join(p, name)
        kind = "📁" if os.path.isdir(full) else "📄"
        lines.append("%s %s" % (kind, name))
    if len(entries) > 100:
        lines.append("……（共 %d 项，已截断）" % len(entries))
    return "\n".join(lines) or "（空目录）"
