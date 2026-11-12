# -*- coding: utf-8 -*-
"""星语 Starry · 发布快照终验（v13.1 新增，可复跑 / 可进 CI）。

把过去每次发版手写的临时校验固化成一条命令：

    python scripts/verify_release.py --version 13.1.0

检查项：
  1. 快照目录 / zip / SHA256SUMS / RELEASES 索引齐备；
  2. zip 与目录**文件名集合一致**且逐文件 SHA-256 一致（剥顶层前缀）；
  3. SHA256SUMS-vX.Y.Z.txt 每条都能对应到真实文件且哈希相符；
  4. 快照内无密钥 / 证书 / 配置等敏感文件；
  5. 快照内 RELEASE_NOTES.md 是完整发布说明，不是占位文本（v13.1 修复项）；
  6. 版本索引含本版 latest 与全部历史行；
  7. 本版关键文件（skills/ / core/hub.py / ui/hub_dialog.py / 两份 EXE）齐备。

退出码 0 = 全通过。
"""
import argparse
import fnmatch
import hashlib
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASES = os.path.join(ROOT, "releases")

SENSITIVE_PATTERNS = (
    "*.keystore", "*.jks", "*.p12", "*.pfx", "*.pem", "*.key",
    "*.p8", "*.der", "id_rsa*", ".env", "config.json",
    "credentials.json", "*_secret*", "*secret*.json",
)

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_stream(fp):
    h = hashlib.sha256()
    for chunk in iter(lambda: fp.read(65536), b""):
        h.update(chunk)
    return h.hexdigest()


def rel_files(directory):
    out = {}
    for base, _, files in os.walk(directory):
        for fn in files:
            full = os.path.join(base, fn)
            out[os.path.relpath(full, directory).replace("\\", "/")] = full
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="不带 v，如 13.1.0")
    ap.add_argument("--skip-history", action="store_true",
                    help="CI 首次发版时跳过「历史快照目录」检查"
                         "（全新 checkout 可能还没有历史目录）")
    args = ap.parse_args()
    v = args.version
    folder = "星语Starry-v%s" % v
    dest = os.path.join(RELEASES, folder)
    zip_path = os.path.join(RELEASES, folder + ".zip")
    sums_path = os.path.join(RELEASES, "SHA256SUMS-v%s.txt" % v)

    check("快照目录存在", os.path.isdir(dest))
    check("同名 zip 存在", os.path.isfile(zip_path))
    check("SHA256SUMS 存在", os.path.isfile(sums_path))
    if not os.path.isdir(dest):
        return _finish(v)

    disk = rel_files(dest)
    check("快照含 MANIFEST.md", "MANIFEST.md" in disk)
    check("快照含 checksums.txt", "checksums.txt" in disk)
    check("快照含 RELEASE_NOTES.md", "RELEASE_NOTES.md" in disk)
    check("快照含 RELEASES.md", "RELEASES.md" in disk)
    check("快照含主文件",
          all(k in disk for k in ("main.py", "starry_cli.py",
                                  "selftest.py", "README.md", "CHANGELOG.md")))
    check("快照含源码目录",
          all(any(k.startswith(d + "/") for k in disk)
              for d in ("core", "ui", "app", "android", "docs",
                        "scripts", "tests", ".github", "skills")))

    # v13.1 关键文件
    check("快照含 core/hub.py", "core/hub.py" in disk)
    check("快照含 ui/hub_dialog.py", "ui/hub_dialog.py" in disk)
    check("快照含 smoke_gui_exe.py", "scripts/smoke_gui_exe.py" in disk)
    check("快照含 smoke_cli_exe.py", "scripts/smoke_cli_exe.py" in disk)
    skills = [k for k in disk if k.startswith("skills/")]
    check("快照含至少 4 个 skills/ 文件", len(skills) >= 4,
          "count=%d" % len(skills))
    wins = [k for k in disk if k.startswith("assets/windows/")
            and k.endswith(".exe")]
    check("快照含两份 Windows EXE", len(wins) == 2, str(wins))
    check("快照含 linux deb",
          any(k.startswith("assets/linux/") and k.endswith(".deb")
              for k in disk))
    check("apk/ 不放伪造二进制",
          not any(k.startswith("assets/apk/") and k.endswith(".apk")
                  for k in disk))

    # 发布说明不能是占位（v13.1 修复的历史缺陷）
    notes = os.path.join(dest, "RELEASE_NOTES.md")
    if os.path.isfile(notes):
        text = open(notes, "r", encoding="utf-8").read()
        check("RELEASE_NOTES.md 是完整发布说明（非占位）",
              len(text) > 2000 and "v%s" % v in text,
              "len=%d" % len(text))
        check("RELEASE_NOTES.md 含本版主题", "Skills Hub" in text)

    # 敏感文件扫描
    leaks = [k for k in disk
             if any(fnmatch.fnmatch(os.path.basename(k).lower(), p.lower())
                    for p in SENSITIVE_PATTERNS)]
    check("快照内敏感文件为 0", not leaks, "; ".join(leaks[:5]))

    # zip 与目录一致性（含逐文件哈希）
    if os.path.isfile(zip_path):
        zf = zipfile.ZipFile(zip_path)
        check("zip CRC 全部通过", zf.testzip() is None)
        names = set()
        for info in zf.infolist():
            n = info.filename.replace("\\", "/")
            prefix = folder + "/"
            if n.startswith(prefix):
                names.add(n[len(prefix):])
        names.discard("")
        check("zip 与目录文件名集合一致", names == set(disk),
              "zip=%d disk=%d" % (len(names), len(disk)))
        mismatched = []
        for rel in sorted(names & set(disk)):
            with zf.open(folder + "/" + rel) as fp:
                if sha256_stream(fp) != sha256(disk[rel]):
                    mismatched.append(rel)
        check("zip 与目录逐文件哈希一致", not mismatched,
              "; ".join(mismatched[:3]))
        zf.close()

    # SHA256SUMS 逐条核验
    if os.path.isfile(sums_path):
        lines = [l.strip() for l in open(sums_path, "r", encoding="utf-8")
                 if l.strip()]
        bad = []
        for line in lines:
            parts = line.split(None, 1)
            if len(parts) != 2:
                bad.append(line[:60])
                continue
            want, rel = parts[0].lower(), parts[1].strip()
            target = (os.path.join(RELEASES, folder + ".zip")
                      if rel == folder + ".zip"
                      else os.path.join(RELEASES, rel))
            if not os.path.isfile(target) or sha256(target) != want:
                bad.append(rel)
        check("SHA256SUMS 全部条目通过", not bad,
              "%d 条 / 失败 %d" % (len(lines), len(bad)))

    # 版本索引
    for idx in ("RELEASES.md", os.path.join("releases", "RELEASES.md")):
        p = os.path.join(ROOT, idx)
        if os.path.isfile(p):
            t = open(p, "r", encoding="utf-8").read()
            check("%s 含本版 latest" % idx,
                  ("| %s |" % v) in t and "latest" in t)
            check("%s 保留历史三版" % idx,
                  all(("| %s |" % old) in t
                      for old in ("13.0.0", "12.0.0", "11.5.0")))
    if not args.skip_history:
        for old in ("11.5.0", "12.0.0", "13.0.0"):
            check("历史快照 v%s 保留" % old,
                  os.path.isdir(os.path.join(RELEASES, "星语Starry-v%s" % old)))

    return _finish(v)


def _finish(version=""):
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n==== 发布快照终验 v%s：%d/%d 通过 ====" % (
        version, passed, total))
    for name, ok, extra in RESULTS:
        if not ok:
            print("  x", name, extra)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
