#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 v13.7.0 多平台 Release 资产（跨平台，纯标准库）。

在 Windows / Linux / macOS 任一主机都能运行，产出：

  releases/星语Starry-v<版本>-macOS.tar.gz   macOS 源码分发包（含 .command 启动器）
  releases/星语Starry-v<版本>-macOS.zip      同上，zip 形态
  releases/星语Starry-v<版本>-Linux.tar.gz   Linux / UOS 源码分发包（含启动器）
  releases/星语Starry-v<版本>-Android-Termux.zip  Termux 命令行分发包
  releases/星语Starry-CLI-v<版本>.deb       真实 Debian 包（复用 build_deb.py）
  releases/SHA256SUMS-<版本>.txt           全部资产校验和

诚实说明：本机为 Windows，无法交叉编译 macOS .app / Linux ELF 二进制，
因此 macOS / Linux / Android 包为「真实可运行的源码分发包」——内含完整
core/、启动脚本与依赖清单，在对应系统上执行安装脚本即可运行；原生
.app/.dmg、ELF 单文件、APK 由 .github/workflows 在对应 runner 上产出。
Windows GUI EXE 由 scripts/build_root_exe.py 真实编译。
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_RE = "core/config.py"

# 打包内容：真实源码 + 全部文档 + 启动器，排除构建产物 / 密钥 / 虚拟环境
INCLUDE_DIRS = ("core", "ui", "app", "android", "docs", "scripts", "assets",
                "skills", ".github")
INCLUDE_FILES = ("main.py", "starry_cli.py", "README.md", "CHANGELOG.md",
                 "RELEASE_NOTES.md", "RELEASES.md", "LICENSE",
                 "requirements.txt", "requirements-optional.txt",
                 "config.example.json", "命令行使用指南.md")
EXCLUDE_DIR_NAMES = {"__pycache__", ".git", ".venv", ".venv-build", "build",
                     "dist", "releases", "_build_tmp", "_build_gui",
                     "_build_cli", "node_modules"}


def read_version():
    import re
    with open(os.path.join(ROOT, VERSION_RE), encoding="utf-8") as f:
        m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)', f.read())
    if not m:
        raise SystemExit("无法读取 APP_VERSION")
    return m.group(1)


def collect(base):
    out = []
    for name in INCLUDE_DIRS:
        src = os.path.join(ROOT, name)
        if not os.path.isdir(src):
            continue
        for cur, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR_NAMES]
            for f in files:
                if f.endswith((".pyc", ".pyo", ".exe", ".deb", ".apk")):
                    continue
                p = os.path.join(cur, f)
                rel = os.path.relpath(p, ROOT)
                out.append((p, os.path.join(base, rel)))
    for name in INCLUDE_FILES:
        src = os.path.join(ROOT, name)
        if os.path.isfile(src):
            out.append((src, os.path.join(base, name)))
    return out


MAC_RUNNER = """#!/bin/bash
# 星语 Starry · macOS 一键启动（源码分发包）
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "请先安装 Python 3.10+：brew install python3"; exit 1
fi
if [ ! -d .venv-release ]; then
  python3 -m venv .venv-release
  ./.venv-release/bin/pip install -q --upgrade pip
  ./.venv-release/bin/pip install -q -r requirements.txt
fi
exec ./.venv-release/bin/python main.py "$@"
"""

LINUX_RUNNER = """#!/bin/bash
# 星语 Starry · Linux / UOS 一键启动（源码分发包）
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "请先安装 python3 / python3-venv"; exit 1
fi
if [ ! -d .venv-release ]; then
  python3 -m venv .venv-release || true
  ./.venv-release/bin/pip install -q --upgrade pip
  ./.venv-release/bin/pip install -q -r requirements.txt
fi
exec ./.venv-release/bin/python main.py "$@"
"""

TERMUX_RUNNER = """#!/data/data/com.termux/files/usr/bin/bash
# 星语 Starry · Android Termux 命令行版
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "请先执行：pkg install python"; exit 1
fi
python3 -m pip install -q -r requirements.txt
exec python3 starry_cli.py "$@"
"""

PLATFORM_README = """# 星语 Starry {v} · {plat} 源码分发包

这是**真实可运行的源码分发包**（非原生二进制安装包）。
包含完整 core/ / ui/ / app/ 源码、全部文档与一键启动脚本。

## 运行

    {cmd}

首次运行会自动创建 .venv-release 并安装 requirements.txt。
若需原生 .app / .dmg / ELF / APK，请在对应系统执行：

    bash scripts/build_macos.sh      # macOS 产出 星语Starry.app
    bash scripts/build_linux.sh      # Linux 产出单文件 ELF
    bash scripts/build_android.sh apk  # Android 产出 APK（需 SDK/NDK）

## 校验

    sha256sum -c ../SHA256SUMS-{v}.txt    # Linux
    shasum -a 256 -c ../SHA256SUMS-{v}.txt  # macOS

Windows 用户请直接下载 `星语Starry-GUI-v{v}.exe`（真实编译的 GUI 单文件）。
"""


def stage(version, plat, runner_name, runner_body, readme_cmd):
    d = tempfile.mkdtemp(prefix="starry_asset_")
    base = os.path.join(d, "星语Starry-v%s-%s" % (version, plat))
    os.makedirs(base, exist_ok=True)
    for src, dst in collect(base):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    runner = os.path.join(base, runner_name)
    with open(runner, "w", encoding="utf-8", newline="\n") as f:
        f.write(runner_body)
    os.chmod(runner, 0o755)
    with open(os.path.join(base, "README_%s.md" % plat), "w",
              encoding="utf-8") as f:
        f.write(PLATFORM_README.format(v=version, plat=plat, cmd=readme_cmd))
    return d, base


def make_tgz(base, out, version, plat):
    with tarfile.open(out, "w:gz") as tf:
        tf.add(base, arcname=os.path.basename(base))
    return out


def make_zip(base, out):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for cur, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR_NAMES]
            for f in files:
                p = os.path.join(cur, f)
                zf.write(p, os.path.relpath(p, os.path.dirname(base)))
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None)
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "releases"))
    args = ap.parse_args()
    v = args.version or read_version()
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    made = []

    specs = [
        ("macOS", "启动星语.command", MAC_RUNNER,
         "双击 启动星语.command，或终端执行 ./启动星语.command"),
        ("Linux", "start-starry.sh", LINUX_RUNNER,
         "bash start-starry.sh"),
        ("Android-Termux", "starry-termux.sh", TERMUX_RUNNER,
         "bash starry-termux.sh \"你好\""),
    ]
    for plat, runner_name, runner_body, cmd in specs:
        d, base = stage(v, plat, runner_name, runner_body, cmd)
        try:
            tgz = os.path.join(out_dir, "星语Starry-v%s-%s.tar.gz" % (v, plat))
            make_tgz(base, tgz, v, plat)
            made.append(tgz)
            if plat == "macOS":
                z = os.path.join(out_dir, "星语Starry-v%s-macOS.zip" % v)
                make_zip(base, z)
                made.append(z)
            if plat == "Android-Termux":
                z = os.path.join(out_dir, "星语Starry-v%s-Android-Termux.zip" % v)
                make_zip(base, z)
                made.append(z)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # 真实 DEB（复用纯标准库实现，Windows 亦可生成）
    deb = os.path.join(out_dir, "星语Starry-CLI-v%s.deb" % v)
    try:
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "scripts", "build_deb.py"),
                        "--out", deb], cwd=ROOT, check=True,
                       stdout=subprocess.DEVNULL)
        if os.path.isfile(deb):
            made.append(deb)
    except Exception as e:                  # noqa: BLE001
        print("WARN: DEB 生成失败：%s" % e, file=sys.stderr)

    # 把根目录已有的 Windows EXE 也纳入校验和（若存在）
    exe = os.path.join(ROOT, "星语Starry-GUI-v%s.exe" % v)
    if os.path.isfile(exe):
        made.append(exe)

    sums = os.path.join(out_dir, "SHA256SUMS-%s.txt" % v)
    with open(sums, "w", encoding="utf-8") as f:
        for p in made:
            f.write("%s  %s\n" % (sha256(p), os.path.basename(p)))
    print("==> 多平台资产 %d 个，版本 v%s" % (len(made), v))
    for p in made:
        print("    %-58s %8.1f KB" % (os.path.basename(p),
                                      os.path.getsize(p) / 1024.0))
    print("    SHA256SUMS-%s.txt" % v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
