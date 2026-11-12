#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 门禁：三端同源 + 版本单一真源 + Python 语法（v12.0）。

供 .github/workflows/release.yml 的 verify job 调用，任一不平即 exit 1，
阻断发版。对应历史事故：v11.3「APK METADATA 残留 11.0.0，用户拿到旧代码」。

用法：
    python scripts/check_core_parity.py
    python scripts/check_core_parity.py --expect-version 13.0.0   # 校验 tag
"""
import argparse
import ast
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_SOURCES = [
    ("core/config.py", r'APP_VERSION\s*=\s*"([^"]+)"'),
    ("core/mcp.py", r'"version"\s*:\s*"([^"]+)"'),
    ("android/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
]


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-version", default=None,
                    help='期望版本号（通常传 v13.0.0 去掉 v 前缀）')
    args = ap.parse_args()
    failures = []

    # 1) 版本单一真源：所有声明必须相同
    versions = {}
    for rel, pattern in VERSION_SOURCES:
        m = re.search(pattern, read(rel), re.M)
        if not m:
            failures.append("未找到版本声明：%s" % rel)
        else:
            versions[rel] = m.group(1)
    distinct = set(versions.values())
    if len(distinct) > 1:
        failures.append("版本号不一致：%r" % versions)
    elif distinct:
        v = distinct.pop()
        print("OK: 版本声明一致 = %s（%d 处）" % (v, len(versions)))
        if args.expect_version and v != args.expect_version:
            failures.append("tag 版本 %s 与源码版本 %s 不一致"
                            % (args.expect_version, v))

    # 2) 三端同源
    rc = subprocess.call(
        [sys.executable, os.path.join(ROOT, "scripts", "sync_core.py"), "--check"],
        cwd=ROOT)
    if rc != 0:
        failures.append("core/ 与 android/core/ 漂移（sync_core.py --check 返回 %d）" % rc)

    # 3) 全量 Python 语法编译
    bad = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs
                   if d not in {"__pycache__", ".git", ".venv-cli", "dist"}
                   and not d.startswith("星语Starry-v")]
        if os.sep + "releases" + os.sep in base:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(base, f)
            try:
                ast.parse(open(p, encoding="utf-8").read(), filename=p)
            except SyntaxError as exc:
                bad.append("%s: %s" % (os.path.relpath(p, ROOT), exc))
    if bad:
        failures.append("Python 语法错误：\n    " + "\n    ".join(bad))
    else:
        print("OK: 全量 Python 源码语法通过")

    if failures:
        print("\nFAIL: 门禁未通过：", file=sys.stderr)
        for f in failures:
            print("  - " + f, file=sys.stderr)
        return 1
    print("\nPASS: 发布门禁全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
