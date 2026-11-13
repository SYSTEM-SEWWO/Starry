#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包「后代版本后缀」GUI EXE 到项目根目录（v13.3 起固定约定）。

每次更新版本号后，只要执行一次：

    python scripts/build_root_exe.py

就会产出（版本号自动从 core/config.py::APP_VERSION 读取，无需手工同步）：

    ./星语Starry-GUI-v<版本>.exe
    ./星语Starry-GUI-v<版本>.exe.sha256

例：APP_VERSION = "13.6.5" → 星语Starry-GUI-v13.6.5.exe 放在项目根目录。
历史版本的 EXE 不会被覆盖，因此每代产物都会保留在根目录里，方便回溯。

可选参数：
    --skip-build   复用已有的 dist/星语Starry.exe，只做复制 + 校验和
    --no-clean     不执行 PyInstaller --clean（增量构建，更快）
    --python PATH  指定用于构建的解释器（默认当前解释器）
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = "starrystar.spec"
DIST_EXE = os.path.join(ROOT, "dist", "星语Starry.exe")
EXE_PREFIX = "星语Starry-GUI"


def read_version():
    """直接从源码文本读版本，避免 import core.config 拉起 Qt 等重依赖。"""
    path = os.path.join(ROOT, "core", "config.py")
    with open(path, "r", encoding="utf-8") as f:
        m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']',
                      f.read(), re.M)
    if not m:
        raise SystemExit("无法从 core/config.py 读取 APP_VERSION")
    return m.group(1)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(python_exe, clean=True):
    cmd = [python_exe, "-m", "PyInstaller", SPEC, "--noconfirm"]
    if clean:
        cmd.append("--clean")
    print("==> PyInstaller: %s" % " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser(description="打包带版本后缀的 GUI EXE 到项目根目录")
    ap.add_argument("--skip-build", action="store_true",
                    help="复用已有 dist/星语Starry.exe，只做复制与校验和")
    ap.add_argument("--no-clean", action="store_true",
                    help="不执行 --clean（增量构建）")
    ap.add_argument("--python", default=sys.executable,
                    help="构建用 Python 解释器路径")
    args = ap.parse_args()

    version = read_version()
    target = os.path.join(ROOT, "%s-v%s.exe" % (EXE_PREFIX, version))
    sum_path = target + ".sha256"
    print("==> 当前后代版本：v%s" % version)
    print("==> 目标产物：%s" % target)

    if not args.skip_build:
        build(args.python, clean=not args.no_clean)
    if not os.path.isfile(DIST_EXE):
        raise SystemExit("未找到构建产物：%s" % DIST_EXE)

    shutil.copy2(DIST_EXE, target)
    digest = sha256_file(target)
    with open(sum_path, "w", encoding="utf-8") as f:
        f.write("%s  %s\n" % (digest, os.path.basename(target)))

    size_mb = os.path.getsize(target) / (1024.0 * 1024.0)
    print("==> 完成：%s（%.1f MB）" % (os.path.basename(target), size_mb))
    print("    SHA-256：%s" % digest)
    print("    校验和：%s" % os.path.basename(sum_path))
    print("    提示：根目录会保留历代 EXE，历史版本不会被覆盖。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
