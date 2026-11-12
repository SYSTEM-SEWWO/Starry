#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「一个版本 = 一个完整自包含文件夹 + 同名 zip」的发布快照（v12.0）。

对应用户长期诉求：
  「每更新一个版本，把所有更新的全部的东西放到一个文件夹后面带后缀版本，
    确保每个文件夹打包出来都是完整的全部项目文档以及 md 文件，还有主文件」

产物（releases/ 下，**只追加、不覆盖历史**）：
    releases/
    ├── RELEASES.md                        # 发版索引（倒序，追加新行）
    ├── 星语Starry-v13.0.0/               # 完整自包含快照目录
    │   ├── README.md CHANGELOG.md LICENSE SECURITY.md CONTRIBUTING.md ...
    │   ├── main.py starry_cli.py requirements*.txt *.spec 启动.* selftest.py
    │   ├── core/ ui/ app/ android/ assets/ scripts/ tools/ tests/ .github/
    │   ├── docs/                          # 全部 md（含所有历史版本评审）
    │   ├── RELEASE_NOTES.md               # 本版发布说明（Release body）
    │   ├── MANIFEST.md                    # 文件清单 + sha256 + 构建信息
    │   └── checksums.txt                  # 逐文件校验和
    ├── 星语Starry-v13.0.0.zip            # 与文件夹同名同内容
    └── assets/v13.0.0/                   # 二进制资产（文件名带版本号）

白名单复制：显式排除私钥、本地配置、缓存与构建中间物，避免
``android/starry-release.keystore`` 之类的敏感文件随 zip 泄漏。

用法：
    python scripts/make_release.py --version 13.0.0
    python scripts/make_release.py --version 13.0.0 --no-zip   # 只生成目录
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import shutil
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASES = os.path.join(ROOT, "releases")

# 目录白名单：这些目录下的内容整棵复制
DIR_WHITELIST = [
    "core", "ui", "app", "android", "assets", "scripts", "tests",
    "docs", "tools", ".github",
    # v13.1：示例 Skills 必须随每个完整版本快照分发，否则 EXE / deb 里有、
    # 快照里却没有，用户拿到的「完整项目」其实是缺件的。
    "skills",
]
# 根级主文件 / 治理文档白名单
FILE_WHITELIST = [
    "README.md", "CHANGELOG.md", "RELEASES.md", "LICENSE", "SECURITY.md",
    "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", ".gitignore",
    "main.py", "starry_cli.py", "selftest.py",
    "requirements.txt", "requirements-optional.txt", "config.example.json",
    "starrystar.spec", "starry_cli.spec", "starry_cli.py",
    "config.hub.example.json", "RELEASE_NOTES.md",
    "启动.bat", "启动.sh", "命令行使用指南.md",
    "verify_v5.py", "verify_v6_browser.py", "fixture_deepseek.html",
    "test_search_export.py", "test_v11_2.py", "test_v11_3_pc.py",
    "test_v11_4_pc.py", "test_v11_5_pc.py",
]
# 明确排除（安全 + 体积）——精确文件名匹配
EXCLUDE_NAMES = {
    "config.json", "starry-release.keystore", ".env",
    "__pycache__", ".git", ".venv-cli", "build", "node_modules",
}
# 通配符排除（v12.0 代码安全性评估修复）：
# 旧版把 "*.keystore" 写进 EXCLUDE_NAMES 的**精确匹配集合**里，通配符永不生效，
# 且 copytree 的 ignore_patterns 只列了 starry-release.keystore 一个固定名。
# 结果是：任何其它名称的密钥 / 证书都可能被打进发布 zip。现统一走 fnmatch。
EXCLUDE_PATTERNS = {
    "*.keystore", "*.jks", "*.p12", "*.pfx", "*.pem", "*.key",
    "config.json", ".env", "*.bak",
}
EXCLUDE_EXTS = {".pyc", ".pyo", ".log", ".tmp", ".bak"}
# 大体积历史二进制不进源码快照（放进 assets/ 单独管理）
MAX_FILE_BYTES = 8 * 1024 * 1024


def is_sensitive(name):
    """文件名是否命中敏感模式（供 _skip / copytree / 发布前扫描共用）。"""
    return (name in EXCLUDE_NAMES
            or any(fnmatch.fnmatch(name, p) for p in EXCLUDE_PATTERNS))


def _skip(path, name, size):
    if is_sensitive(name) or (name.startswith(".")
                              and name not in {".github", ".gitignore"}):
        return True
    if any(name.endswith(e) for e in EXCLUDE_EXTS):
        return True
    if os.path.splitext(name)[1].lower() in {".exe", ".deb", ".apk", ".zip"}:
        return True
    if size > MAX_FILE_BYTES:
        return True
    if "releases" in path.replace("\\", "/").split("/"):
        return True
    return False


def assert_no_secrets(dest):
    """发布前最后一道门禁：快照里若还有任何敏感文件，直接中止发版。

    白名单是「防呆」，这里是「验证」——两层都要有，才能避免规则改漏。
    """
    leaks = []
    for base, _, fs in os.walk(dest):
        for fn in fs:
            if any(fnmatch.fnmatch(fn, p) for p in EXCLUDE_PATTERNS):
                leaks.append(os.path.relpath(os.path.join(base, fn), dest))
    return sorted(leaks)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_snapshot(version, dest):
    os.makedirs(dest, exist_ok=True)
    copied = []
    for d in DIR_WHITELIST:
        src = os.path.join(ROOT, d)
        if not os.path.isdir(src):
            continue
        out = os.path.join(dest, d)
        # v13.1 修复：不再 rmtree 旧目录。覆盖写入是幂等且非破坏性的，
        # 重跑同一版本不会因批量删除被安全策略拦截，也不会误删用户放在
        # 快照目录里的东西。需要「干净重建」时用 --fresh（重命名旧目录，不删除）。
        shutil.copytree(
            src, out, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.log", "*.tmp", "*.exe", "*.deb",
                "*.apk", "*.zip", ".git", "build", "bin", "logs",
                "starry-release.keystore", "config.json", ".env", "*.bak",
                # v12.0 安全修复：任意名称的密钥 / 证书一律排除
                "*.keystore", "*.jks", "*.p12", "*.pfx", "*.pem", "*.key"))
        for base, _, files in os.walk(out):
            for f in files:
                copied.append(os.path.relpath(os.path.join(base, f), dest))
    for name in FILE_WHITELIST:
        src = os.path.join(ROOT, name)
        if os.path.isfile(src) and not _skip(src, name, os.path.getsize(src)):
            shutil.copy2(src, os.path.join(dest, name))
            copied.append(name)
    return sorted(set(copied))


def write_manifest(dest, version, files):
    lines = [
        "# 发布清单 · 星语 Starry v%s" % version, "",
        "生成时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "文件总数：%d" % len(files),
        "说明：本文件夹为**完整自包含快照**，含全部源码、主文件、",
        "全部 docs/*.md、治理文档、.github 工作流与构建脚本。",
        "敏感文件（config.json / *.keystore / .env）与构建中间物已按白名单排除。",
        "本清单与 checksums.txt 自身不列入校验条目（避免自引用），",
        "故校验条目数比目录文件数少 2。",
        "", "| 文件 | SHA-256 |", "| --- | --- |",
    ]
    checksums = []
    for rel in files:
        p = os.path.join(dest, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            continue
        h = sha256(p)
        checksums.append("%s  %s" % (h, rel.replace("\\", "/")))
        lines.append("| `%s` | `%s` |" % (rel.replace("\\", "/"), h[:16] + "…"))
    with open(os.path.join(dest, "MANIFEST.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(dest, "checksums.txt"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write("\n".join(checksums) + "\n")
    return checksums


def _index_row(version, date, folder, zip_name, asset_count, notes, status):
    """生成一行索引；历史版本没有同名 zip 时用 — 占位。"""
    zip_cell = "[%s](%s)" % (zip_name, zip_name) if zip_name else "—"
    return ("| %s | %s | `v%s` | [%s](%s/) | %s | %s | %s | %s |"
            % (version, date, version, folder, folder,
               zip_cell, asset_count, notes, status))


def update_index(version, folder, zip_path, notes_line, asset_count,
                 zip_expected=True):
    """维护 RELEASES.md：幂等更新本版行 + 自动补录历史版本文件夹。

    v12.0 收尾修复：
      1. 旧实现重跑同一版本会产生两行（旧行降级为 superseded 后又插入新行）；
         现在先删除本版已有行再插入，重复执行结果不变。
      2. 旧实现只记录本次生成的版本，历史文件夹（如 v11.5.0）不会出现在索引里；
         现在扫描 releases/ 下所有 星语Starry-vX.Y.Z 目录自动补录。
    v13.0 修复：
      3. 本函数改在 MANIFEST/checksums/zip **之前**调用，因此 zip 此刻还没落盘。
         用 zip_expected 显式声明「本次会产出 zip」，避免索引里 zip 列变成 —。
    """
    path = os.path.join(RELEASES, "RELEASES.md")
    today = datetime.date.today().isoformat()
    zip_name = (os.path.basename(zip_path)
                if (zip_expected or os.path.exists(zip_path)) else "")
    new_row = _index_row(version, today, folder, zip_name,
                         asset_count, notes_line, "latest")
    header = (
        "# 星语 Starry · Releases 索引\n\n"
        "> 一个版本一个完整自包含文件夹 + 同名 zip，历史版本只追加、不覆盖、不删除。\n"
        "> 每个文件夹都含全部源码、主文件、全部 md 文档与构建脚本。\n\n"
        "| 版本 | 日期 | tag | 完整文件夹 | zip | 资产数 | 主要变更 | 状态 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else header

    # 幂等：先移除本版已有行（无论状态是 latest 还是 superseded）
    lines = [ln for ln in text.splitlines()
             if not (ln.startswith("|") and ("| `v%s` |" % version) in ln)]
    text = "\n".join(lines).rstrip() + "\n"
    text = text.replace("| latest |", "| superseded |")

    # 自动补录未收录的历史版本文件夹（按版本号数值倒序，避免 v9 排在 v11 前）
    known = set(re.findall(r"\| `v([0-9]+\.[0-9]+\.[0-9]+)` \|", text))
    candidates = []
    for name in os.listdir(RELEASES):
        m = re.match(r"^星语Starry-v(\d+\.\d+\.\d+)$", name)
        if m and os.path.isdir(os.path.join(RELEASES, name)):
            key = tuple(int(x) for x in m.group(1).split("."))
            candidates.append((key, m.group(1), name))
    historical = []
    for _, old_ver, name in sorted(candidates, reverse=True):
        if old_ver == version or old_ver in known:
            continue
        old_zip = name + ".zip"
        old_zip_name = old_zip if os.path.isfile(os.path.join(RELEASES, old_zip)) else ""
        old_date = datetime.date.fromtimestamp(
            os.path.getmtime(os.path.join(RELEASES, name))).isoformat()
        historical.append(_index_row(old_ver, old_date, name, old_zip_name,
                                     "—", "历史版本（完整快照保留）", "superseded"))
        known.add(old_ver)

    marker = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    rows = "\n".join([new_row] + historical)
    if marker in text:
        text = text.replace(marker, marker + "\n" + rows, 1)
    else:
        text += rows + "\n"
    if not text.endswith("\n"):
        text += "\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    # 根目录也放一份，方便从仓库首页发现
    with open(os.path.join(ROOT, "RELEASES.md"), "w", encoding="utf-8") as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="不带 v 前缀，如 13.0.0")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--summary", default="大版本更新")
    ap.add_argument("--fresh", action="store_true",
                    help="干净重建：把旧快照重命名为 *.prev-<时间戳> 后从空目录生成"
                         "（重命名而非删除，避免破坏性操作）")
    args = ap.parse_args()

    folder = "星语Starry-v%s" % args.version
    dest = os.path.join(RELEASES, folder)
    os.makedirs(RELEASES, exist_ok=True)
    if args.fresh and os.path.isdir(dest):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = dest + ".prev-" + stamp
        os.rename(dest, backup)
        print("旧快照已保留为：%s（未删除）" % os.path.basename(backup))
    files = build_snapshot(args.version, dest)

    # v12.0 安全门禁：白名单是「防呆」，这里是「验证」。
    # 复制完成后再扫一遍快照，任何密钥 / 证书残留都直接中止发版。
    leaks = assert_no_secrets(dest)
    if leaks:
        raise SystemExit("发布快照含敏感文件，已中止发版：\n  "
                         + "\n  ".join(leaks))

    # 本版发布说明：从 docs 复制，缺失时才给最小占位。
    # v13.1 修复：旧逻辑只拼 "v13_1_0"，而项目实际命名为
    # docs/RELEASE_NOTES_v13_1.md（两位版本，v12/v13 都如此）。名字对不上时
    # 会静默退化成一行占位文本，且 release.yml 用这个 RELEASE_NOTES.md 作为
    # GitHub Release 正文 —— 结果「完整发布说明」根本没进产物。
    # 现按「三位版本 → 两位版本 → 根目录当前版说明」依次回退，并让终验检查
    # 快照内该文件不是占位（长度与结构）。
    short_ver = "_".join(args.version.split(".")[:2])
    notes_candidates = [
        os.path.join(ROOT, "docs", "RELEASE_NOTES_v%s.md"
                     % args.version.replace(".", "_")),
        os.path.join(ROOT, "docs", "RELEASE_NOTES_v%s.md" % short_ver),
        os.path.join(ROOT, "RELEASE_NOTES.md"),
    ]
    src_notes = next((p for p in notes_candidates if os.path.isfile(p)), "")
    notes_dst = os.path.join(dest, "RELEASE_NOTES.md")
    if src_notes:
        shutil.copy2(src_notes, notes_dst)
        print("发布说明来源：%s" % os.path.relpath(src_notes, ROOT))
    else:
        with open(notes_dst, "w", encoding="utf-8") as f:
            f.write("# 星语 Starry v%s 发布说明\n\n%s\n"
                    % (args.version, args.summary))

    # 资产目录（apk 单独拎出来，便于分发与成本核算）
    assets_dst = os.path.join(dest, "assets")
    os.makedirs(os.path.join(assets_dst, "apk"), exist_ok=True)
    os.makedirs(os.path.join(assets_dst, "windows"), exist_ok=True)
    os.makedirs(os.path.join(assets_dst, "linux"), exist_ok=True)
    src_assets = os.path.join(RELEASES, "assets", "v" + args.version)
    asset_count = 0
    if os.path.isdir(src_assets):
        for base, _, fs in os.walk(src_assets):
            for fn in fs:
                s = os.path.join(base, fn)
                rel = os.path.relpath(s, src_assets)
                t = os.path.join(assets_dst, rel)
                os.makedirs(os.path.dirname(t), exist_ok=True)
                shutil.copy2(s, t)
                asset_count += 1

    # v13.0 修复：索引必须先更新并回写进快照，再生成 MANIFEST / checksums / zip。
    # 旧顺序是「复制目录 → 生成清单和 zip → 最后更新索引」，
    # 导致快照内的 RELEASES.md 永远残留上一版（v12 的 latest），
    # 且 checksums.txt 里记录的也是旧索引的哈希。
    zip_path = os.path.join(RELEASES, folder + ".zip")
    update_index(args.version, folder, zip_path, args.summary, asset_count,
                 zip_expected=not args.no_zip)
    shutil.copy2(os.path.join(RELEASES, "RELEASES.md"),
                 os.path.join(dest, "RELEASES.md"))

    all_files = []
    for base, _, fs in os.walk(dest):
        for fn in fs:
            all_files.append(os.path.relpath(os.path.join(base, fn), dest))
    checksums = write_manifest(dest, args.version, sorted(all_files))

    if not args.no_zip:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as z:
            for base, _, fs in os.walk(dest):
                for fn in fs:
                    p = os.path.join(base, fn)
                    z.write(p, os.path.join(folder, os.path.relpath(p, dest)))

    # 顶层校验和文件（GitHub Release 资产常用）
    assets_root = os.path.join(RELEASES, "assets", "v" + args.version)
    with open(os.path.join(RELEASES, "SHA256SUMS-v%s.txt" % args.version),
              "w", encoding="utf-8", newline="\n") as f:
        if os.path.exists(zip_path):
            f.write("%s  %s.zip\n" % (sha256(zip_path), folder))
        for base, _, fs in os.walk(assets_root):
            for fn in fs:
                p = os.path.join(base, fn)
                # v12.0 修复：保留 apk/ windows/ linux/ 子目录，
                # 旧实现只写 fn，导致校验和对应的路径找不到文件。
                rel = os.path.relpath(p, assets_root).replace("\\", "/")
                f.write("%s  assets/v%s/%s\n" % (sha256(p), args.version, rel))

    print("发布快照生成完成")
    print("  文件夹：%s（%d 个文件）" % (dest, len(all_files)))
    if os.path.exists(zip_path):
        print("  zip：%s（%d 字节）" % (zip_path, os.path.getsize(zip_path)))
    print("  资产：%d 个 · 校验条目：%d 条" % (asset_count, len(checksums)))
    print("  索引：releases/RELEASES.md 已追加 v%s" % args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
