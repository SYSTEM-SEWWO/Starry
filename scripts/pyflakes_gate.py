# -*- coding: utf-8 -*-
"""CI 静态检查门禁（v13.7）：只把「会导致运行失败」的问题判失败。

背景：直接 `python -m pyflakes .` 会把 .venv 副本、历史版本快照、旧测试里
大量 `imported but unused` 风格警告也算成失败，长期卡住发版；而其中若干
"unused" 其实是 try 块里的条件导入（删掉会破坏功能）。

策略（明确、可复现、不掩盖真问题）：
  * 扫描仓库内的 Python 源码，排除 .venv / build / dist / releases / 历史快照；
  * **致命**：undefined name / 语法错误 / expected an indented block /
    duplicate argument / invalid syntax → exit 1；
  * **风格**：imported but unused / redefinition of unused / assigned to but
    never used → 打印但不阻断（历史遗留，逐版清理）。

用法： python scripts/pyflakes_gate.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {".git", ".venv", ".venv-build", ".venv-cli", "__pycache__",
                "build", "dist", "releases", "node_modules", "_build_gui",
                "_build_cli", "_build_tmp"}
FATAL = ("undefined name", "invalid syntax", "expected an indented block",
         "duplicate argument", "unexpected indent", "unindent does not match",
         "f-string", "cannot assign to", "syntax error")
STYLE = ("imported but unused", "redefinition of unused",
         "assigned to but never used", "unable to detect undefined names")


def collect():
    paths = []
    for cur, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs
                   if d not in EXCLUDE_DIRS and not d.startswith("星语Starry-v")]
        for f in files:
            if f.endswith(".py"):
                paths.append(os.path.join(cur, f))
    return sorted(paths)


def main():
    paths = collect()
    r = subprocess.run([sys.executable, "-m", "pyflakes"] + paths,
                       cwd=ROOT, capture_output=True, text=True)
    lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
    fatal, style = [], []
    for line in lines:
        low = line.lower()
        if any(k in low for k in FATAL):
            fatal.append(line)
        elif any(k in low for k in STYLE):
            style.append(line)
        else:
            fatal.append(line)               # 未知类别从严，按致命处理
    print("pyflakes 门禁：扫描 %d 个源码文件，致命 %d，风格 %d"
          % (len(paths), len(fatal), len(style)))
    for line in fatal[:40]:
        print("  [FATAL] " + line)
    if style:
        print("  风格告警（不阻断，示例）：")
        for line in style[:8]:
            print("    " + line)
    if fatal:
        print("FAIL: 存在会导致运行失败的静态问题", file=sys.stderr)
        return 1
    print("PASS: 无致命静态问题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
