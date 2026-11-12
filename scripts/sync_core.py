#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三端同源同步器（v12.0）。

把桌面 ``core/`` 的纯逻辑文件同步到 ``android/core/``，让 Android 与 PC
永远跑同一份代码，替代 v11.5 及之前「人工 diff -q + 手动拷贝」的做法
（历史复审指出：一次 sessions.py 改动就要手工同步四端，且曾因漏拷贝
导致「分发旧构建、闪退持续」）。

白名单：以下 4 个文件是 **桌面专属**（依赖 PyQt5 或桌面专属能力），
不进入 Android 包；它们在 android/core/__init__.py 中仅作懒导出登记，
只要运行时不访问就不会被导入。

    DESKTOP_ONLY = {attachment.py, hotkey.py, models.py, workers.py}

用法（仓库根目录）：
    python scripts/sync_core.py            # 同步
    python scripts/sync_core.py --check   # 只校验，不同步（CI 门禁用）

返回值：0 = 成功/一致；1 = --check 发现漂移；2 = 目录结构错误。
"""
import argparse
import filecmp
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "core")
DST = os.path.join(ROOT, "android", "core")

# 桌面专属：这些模块依赖 PyQt5 / pynput，Android/Chaquopy 环境没有
DESKTOP_ONLY = {"attachment.py", "hotkey.py", "models.py", "workers.py"}
# 不参与同步的生成物
SKIP = {"__pycache__"}


def collect(base):
    out = {}
    for cur, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in files:
            if not f.endswith(".py") or f in DESKTOP_ONLY:
                continue
            rel = os.path.relpath(os.path.join(cur, f), base).replace("\\", "/")
            out[rel] = os.path.join(cur, f)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只校验一致性，不写文件；发现漂移返回 1")
    args = ap.parse_args()

    if not os.path.isdir(SRC) or not os.path.isdir(DST):
        print("FAIL: core/ 或 android/core/ 不存在", file=sys.stderr)
        return 2

    src = collect(SRC)
    dst = collect(DST)
    drift = []
    for rel, sp in sorted(src.items()):
        dp = dst.get(rel)
        if dp is None:
            drift.append(("MISSING", rel))
        elif not filecmp.cmp(sp, dp, shallow=False):
            drift.append(("DIFFER", rel))
    for rel in sorted(set(dst) - set(src)):
        drift.append(("EXTRA", rel))

    if args.check:
        if drift:
            print("FAIL: core/ 与 android/core/ 存在 %d 处漂移：" % len(drift))
            for kind, rel in drift:
                print("  %-8s %s" % (kind, rel))
            print("修复：python scripts/sync_core.py")
            return 1
        print("OK: core/ 与 android/core/ 完全一致（%d 个文件，"
              "桌面专属 %d 个已按白名单排除）" % (len(src), len(DESKTOP_ONLY)))
        return 0

    changed = 0
    for rel, sp in sorted(src.items()):
        dp = os.path.join(DST, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        if not os.path.exists(dp) or not filecmp.cmp(sp, dp, shallow=False):
            shutil.copy2(sp, dp)
            changed += 1
    for rel in sorted(set(dst) - set(src)):
        dp = os.path.join(DST, rel.replace("/", os.sep))
        try:
            os.remove(dp)
            changed += 1
        except OSError:
            pass
    print("同步完成：%d 个文件一致，%d 个文件被更新；桌面专属白名单：%s"
          % (len(src), changed, ", ".join(sorted(DESKTOP_ONLY))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
