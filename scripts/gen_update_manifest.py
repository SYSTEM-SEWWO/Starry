#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成星语 Starry 的 update.json 更新清单（v13.0 大版本新增）。

只从**真实存在的文件**计算 SHA-256 与大小，绝不编造资产：
    Windows  *.exe                 → windows
    Linux    *.deb / *.AppImage   → linux
    Android  *.apk                → android
    macOS    *.dmg / *.pkg        → macos

两种使用场景：
  1) 本地发版：扫描 releases/assets/vX.Y.Z/，产出带真实哈希的离线清单，
     由 make_release.py 一起收进版本快照与 SHA256SUMS。
  2) GitHub Actions：先把 Release 资产 gh release download 到本地目录，
     再用同一脚本生成含真实下载 URL 的清单并回传（见 update-manifest.yml）。

URL 说明：默认拼 ``https://github.com/<repo>/releases/download/v<ver>/<name>``。
repo 优先取 --repo，其次 GITHUB_REPOSITORY，最后用项目既有占位
``yourname/ai-assistant``（fork 后必须替换，文档已标注）。未发布前生成的
本地清单会在 notes 中显式声明「离线自检用」，避免被误当成线上权威清单。

用法：
    python scripts/gen_update_manifest.py --version 13.0.0
    python scripts/gen_update_manifest.py --version 13.0.0 \
        --assets-dir release-assets --repo owner/starry --out update.json
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import updatecheck as uc                        # noqa: E402

DEFAULT_REPO = "yourname/ai-assistant"     # 与 android/pyproject.toml 一致的占位
_SUFFIX_PLATFORM = (
    (".exe", "windows"),
    (".deb", "linux"), (".appimage", "linux"),
    (".apk", "android"),
    (".dmg", "macos"), (".pkg", "macos"),
)


def platform_of(rel):
    """**只按二进制扩展名**判定平台。

    刻意不按目录名推断：apk/ 目录下会放 README.md（说明为何没有 APK），
    若按目录推断会把说明文档误当成 android 资产写进清单，属于伪造资产。
    无法判定的文件（README / 校验和 / json / 文本）一律跳过。
    """
    low = rel.replace("\\", "/").lower()
    for suffix, plat in _SUFFIX_PLATFORM:
        if low.endswith(suffix):
            return plat
    return ""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# 明显非正式的文件名（debug / 临时 / 未签名），不进更新清单
_NON_RELEASE_MARKERS = ("-debug", "-test", "-unsigned", ".tmp", ".part", ".bak")


def collect(assets_dir, version, repo, released_at):
    """扫描目录，返回 (assets, skipped, base)。

    v13.1 修正：同一平台允许**多个正式资产**。此前「同平台取体积最大者」
    是为了排除 debug 包，但 v13.1 起 windows 同时发布 CLI EXE 与 GUI EXE，
    两者都是正式产物，取最大者会把 CLI EXE 悄悄丢掉。现改为按文件名
    排除明显的非正式包，其余全部收录，并按「平台顺序 + 文件名」稳定排序。
    """
    base = "https://github.com/%s/releases/download/v%s" % (repo, version)
    found = []
    skipped = []
    if not os.path.isdir(assets_dir):
        raise SystemExit("资产目录不存在：%s" % assets_dir)
    for cur, _, files in os.walk(assets_dir):
        for fn in files:
            full = os.path.join(cur, fn)
            rel = os.path.relpath(full, assets_dir)
            plat = platform_of(rel)
            low = fn.lower()
            if not plat or any(m in low for m in _NON_RELEASE_MARKERS):
                skipped.append(rel)
                continue
            found.append({
                "platform": plat,
                "name": fn,
                "url": base + "/" + quote(fn),
                "sha256": sha256(full),
                "size": os.path.getsize(full),
            })
    order = {p: i for i, p in enumerate(uc.PLATFORMS)}
    found.sort(key=lambda a: (order.get(a["platform"], 99), a["name"]))
    return found, skipped, base


def main():
    ap = argparse.ArgumentParser(description="生成 Starry update.json 更新清单")
    ap.add_argument("--version", required=True, help="不带 v 前缀，如 13.0.0")
    ap.add_argument("--assets-dir",
                    help="资产目录（默认 releases/assets/v<version>）")
    ap.add_argument("--out", help="输出路径（默认 <资产目录>/update.json）")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""),
                    help="owner/name，用于拼接下载 URL")
    ap.add_argument("--notes", default="", help="附加发布说明")
    ap.add_argument("--min-assets", type=int, default=1,
                    help="至少需要的平台资产数（默认 1）")
    ap.add_argument("--online", action="store_true",
                    help="标记为 GitHub Release 正式清单（默认标为本地离线自检用）")
    args = ap.parse_args()

    assets_dir = args.assets_dir or os.path.join(
        ROOT, "releases", "assets", "v" + args.version)
    out = args.out or os.path.join(assets_dir, "update.json")
    repo = (args.repo or DEFAULT_REPO).strip().strip("/")
    released_at = datetime.date.today().isoformat()

    assets, skipped, base = collect(assets_dir, args.version, repo, released_at)
    if len(assets) < args.min_assets:
        raise SystemExit(
            "可用平台资产 %d 个，少于要求的 %d 个；拒绝生成空/不全的更新清单。"
            % (len(assets), args.min_assets))
    if repo == DEFAULT_REPO and args.online:
        raise SystemExit(
            "正式清单必须指定真实仓库：--repo owner/name 或 GITHUB_REPOSITORY")

    note = args.notes or ("v%s 大版本更新" % args.version)
    if not args.online:
        note += ("\n[本地离线自检清单] 由 gen_update_manifest.py 从本地构建产物生成，"
                 "哈希与大小真实；下载 URL 为按仓库占位拼出的预期地址。"
                 "发布到 GitHub 后以 update-manifest.yml 重新生成的清单为准。")

    manifest = uc.build_manifest(
        args.version, assets=assets, notes=note,
        released_at=released_at, repo_url="https://github.com/" + repo)
    ok, reason = uc.validate_manifest(manifest)
    if not ok:
        raise SystemExit("生成的清单自校验失败：%s" % reason)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("已生成：%s" % out)
    print("  版本 %s · 资产 %d 个 · 模式 %s"
          % (args.version, len(assets), "正式" if args.online else "本地离线"))
    print("  URL 前缀：%s" % base)
    for a in assets:
        print("    - %-8s %-46s %10d B  %s"
              % (a["platform"], a["name"], a["size"], a["sha256"][:16] + "…"))
    if skipped:
        print("  跳过 %d 个非资产文件（README / 校验和 / 其它）" % len(skipped))
    print("  自校验：%s" % reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
