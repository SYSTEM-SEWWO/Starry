#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""星语 Starry · 无界面命令行版入口（V10.0）。

无图形界面、跨平台（Windows / Linux / 统信 UOS / Android Termux），
复用桌面版相同的 API 客户端与智能体运行时。

用法：
    python3 starry_cli.py "你的问题"
    python3 starry_cli.py -f prompt.txt --json
    python3 starry_cli.py --platform
"""
import os
import sys

# 允许以脚本方式直接运行（无需安装包）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# V11.5 · Windows exe 实测修复：Windows 控制台默认编码（cp1252 / GBK）
# 可能无法编码部分中文字符，直接 print 会抛 UnicodeEncodeError 让 exe 秒退。
# 这里只放宽「不可编码字符」的处理策略（replace），不改变原编码，
# 对所有平台无副作用；打印层 core.cli._emit 另有一层兜底。
#
# v13.1：CI / 自动化管道常把 stdout 重定向到文件并按 UTF-8 读取，而
# PyInstaller onefile 在管道下仍可能沿用 locale（cp936），导致中文断言
# 全部乱码。显式尊重 PYTHONIOENCODING（形如 "utf-8" 或 "utf-8:replace"），
# 让自动化可强制 UTF-8；未设置时行为与 v11.5 完全一致。
_io_encoding = (os.environ.get("PYTHONIOENCODING") or "").split(":", 1)[0]
for _stream in (sys.stdout, sys.stderr):
    try:
        if _io_encoding:
            _stream.reconfigure(encoding=_io_encoding, errors="replace")
        else:
            _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError, LookupError):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

from core.cli import run_cli


if __name__ == "__main__":
    sys.exit(run_cli())
