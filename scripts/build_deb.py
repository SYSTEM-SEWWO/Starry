#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 Linux / 统信 UOS 的 .deb 安装包（v13.0，纯标准库实现）。

为什么不用 dpkg-deb：本机是 Windows，没有 dpkg-deb。而 .deb 的格式是
公开且简单的 `ar` 归档，成员固定为：

    debian-binary   纯文本 "2.0\\n"
    control.tar.gz  ./control（+ ./md5sums）
    data.tar.gz     ./usr/bin/... ./opt/... ./usr/share/...

因此这里用 Python 标准库 ``tarfile`` + 手写 ar 头，**真实构造**一个
符合 Debian 规范、``dpkg -i`` 可安装的包，并自带结构自检。

与 v11.5 的差异（重要，避免误导）：
  v11.5 的 deb 内是一个 PyInstaller 编译的 20MB ELF 二进制（免 Python 依赖）。
  本版在 Windows 本机无法交叉编译 Linux ELF，因此改为「v13.0 真实源码 +
  系统 python3 启动器」，control 显式声明依赖。好处是包里跑的**确实是
  v13.0 修复后的代码**，而不是旧二进制；免依赖 ELF 版由 CI 的
  .github/workflows/release.yml 在 ubuntu-latest 上产出（见文档）。

用法（仓库根目录）：
    python scripts/build_deb.py
    python scripts/build_deb.py --out dist/Starry-v13.0.0.deb
"""
import argparse
import gzip
import hashlib
import io
import os
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "13.2.0"
PACKAGE = "starry-cli"

CONTROL = """Package: {pkg}
Version: {ver}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-requests, python3-bs4, python3-markdown
Maintainer: 星语 Starry <starry@example.com>
Homepage: https://github.com/yourname/ai-assistant
Description: 星语 Starry 命令行版（跨平台 AI 助手，v{ver}）
 无图形界面、复用桌面版同一套 core 引擎，支持流式对话、深度思考、
 长期记忆、智能体工具调用、星尘卡、上下文预算与 .starry 存档；
 v13 起支持整体项目、多线并行执行、离线更新检查与电脑端工作台。
 适用于 Debian / Ubuntu / 统信 UOS / 银河麒麟等 dpkg 系发行版。
""".format(pkg=PACKAGE, ver=VERSION)

WRAPPER = """#!/bin/sh
# 星语 Starry CLI 启动器（.deb 安装后位于 /usr/bin/starry）
exec python3 /opt/starry/starry_cli.py "$@"
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=星语 Starry CLI
Comment=跨平台 AI 助手（命令行）
Exec=starry --version
Terminal=true
Categories=Utility;
Icon=starry
"""

POSTINST = """#!/bin/sh
set -e
chmod 755 /usr/bin/starry /opt/starry/starry_cli.py 2>/dev/null || true
exit 0
"""


def _add(tar, arcname, data, mode=0o644):
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mode = mode
    info.mtime = int(time.time())
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    tar.addfile(info, io.BytesIO(data))


def _targz(entries):
    """entries: [(arcname, bytes, mode)] -> gzip 压缩的 tar 字节串。"""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for arcname, data, mode in entries:
            _add(tar, arcname, data, mode)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def _ar_member(name, data):
    """手写 ar 成员头（16+12+6+6+8+10+2 = 60 字节）。"""
    header = "".join([
        name.ljust(16),
        str(int(time.time())).ljust(12),
        "0".ljust(6), "0".ljust(6),          # uid / gid
        "100644".ljust(8),                   # mode（八进制字符串）
        str(len(data)).ljust(10),
        "`\n",
    ]).encode("ascii")
    pad = b"\n" if len(data) % 2 else b""
    return header + data + pad


def _collect_sources():
    """把 v13.1 真实源码与示例 Skills 收进 /opt/starry。"""
    entries = []
    # 入口
    p = os.path.join(ROOT, "starry_cli.py")
    entries.append(("./opt/starry/starry_cli.py",
                    open(p, "rb").read(), 0o755))
    # core 全量（含 agent 子包）
    core = os.path.join(ROOT, "core")
    for base, dirs, files in os.walk(core):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            full = os.path.join(base, f)
            rel = os.path.relpath(full, core).replace("\\", "/")
            entries.append(("./opt/starry/core/" + rel,
                            open(full, "rb").read(), 0o644))
    # 根级文档
    for name in ("README.md", "CHANGELOG.md", "LICENSE", "命令行使用指南.md",
                 "config.hub.example.json"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            entries.append(("./opt/starry/" + name,
                            open(p, "rb").read(), 0o644))
    # v13.1：示例 Skills（SKILL.md / hub 清单）随 deb 分发，
    # 装完执行 `starry --hub` 就能看到 3 个技能，不需要额外下载。
    skills = os.path.join(ROOT, "skills")
    if os.path.isdir(skills):
        for base, dirs, files in os.walk(skills):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not (f.endswith(".md") or f.endswith(".json")):
                    continue
                full = os.path.join(base, f)
                rel = os.path.relpath(full, skills).replace("\\", "/")
                entries.append(("./opt/starry/skills/" + rel,
                                open(full, "rb").read(), 0o644))
    # 使用指南
    docs = os.path.join(ROOT, "docs")
    if os.path.isdir(docs):
        for name in ("使用指南_Linux_CLI.md", "使用指南_UOS.md",
                     "使用指南_v12_0.md", "使用指南_v13_0.md",
                     "使用指南_v13_1.md"):
            p = os.path.join(docs, name)
            if os.path.exists(p):
                entries.append(("./opt/starry/docs/" + name,
                                open(p, "rb").read(), 0o644))
    # 图标
    icon = os.path.join(ROOT, "assets", "icon.png")
    if os.path.exists(icon):
        entries.append(("./usr/share/icons/hicolor/128x128/apps/starry.png",
                        open(icon, "rb").read(), 0o644))
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        ROOT, "dist", "星语Starry-CLI-v%s.deb" % VERSION))
    args = ap.parse_args()

    data_entries = _collect_sources()
    data_entries += [
        ("./usr/bin/starry", WRAPPER.encode("utf-8"), 0o755),
        ("./usr/share/applications/starry-cli.desktop",
         DESKTOP.encode("utf-8"), 0o644),
    ]

    # md5sums（Debian 规范：路径不带 ./ 前缀）
    md5_lines = []
    for arc, data, _ in data_entries:
        if arc.startswith("./opt") or arc.startswith("./usr"):
            md5_lines.append("%s  %s" % (
                hashlib.md5(data).hexdigest(), arc[2:]))
    control_entries = [
        ("./control", CONTROL.encode("utf-8"), 0o644),
        ("./md5sums", ("\n".join(md5_lines) + "\n").encode("utf-8"), 0o644),
        ("./postinst", POSTINST.encode("utf-8"), 0o755),
    ]

    ar = b"!<arch>\n"
    ar += _ar_member("debian-binary", b"2.0\n")
    ar += _ar_member("control.tar.gz", _targz(control_entries))
    ar += _ar_member("data.tar.gz", _targz(data_entries))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(ar)

    # ---- 结构自检：重新解析 ar 与 tar，确保不是「看起来像 deb」 ----
    assert ar.startswith(b"!<arch>\n"), "ar 魔数错误"
    pos = 8
    members = {}
    while pos < len(ar):
        head = ar[pos:pos + 60]
        if len(head) < 60:
            break
        name = head[:16].decode("ascii").strip()
        size = int(head[48:58].decode("ascii").strip())
        body = ar[pos + 60:pos + 60 + size]
        members[name] = body
        pos += 60 + size + (size % 2)
    for required in ("debian-binary", "control.tar.gz", "data.tar.gz"):
        assert required in members, "缺少成员 " + required
    assert members["debian-binary"] == b"2.0\n", "debian-binary 内容错误"
    for member in ("control.tar.gz", "data.tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(members[member]), mode="r:gz") as tf:
            assert tf.getmembers(), member + " 为空"

    print("构建完成：%s" % args.out)
    print("  大小：%d 字节 · data 文件 %d 个 · ar 成员 %d 个"
          % (len(ar), len(data_entries), len(members)))
    print("  自检：ar 魔数 / debian-binary / control.tar.gz / data.tar.gz 全部通过")
    print("  安装：sudo dpkg -i %s && starry --version" % os.path.basename(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
