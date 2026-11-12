#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APK 静态鉴定器（v12.0）：不装手机、不跑模拟器，也能把包验个明白。

检查项（全部基于解包实证，不猜测）：
  1. ZIP / 签名：v1（META-INF/*.SF + *.RSA）、v2/v3（APK Signing Block）
  2. AndroidManifest.xml / resources.arsc / classes.dex 是否存在
  3. Chaquopy 资源：app.imy、build.json、requirements-common.imy、
     stdlib、bootstrap、各 ABI 的 libpython3.11.so
  4. build.json 里 app.imy 的 SHA1 是否与包内实际字节一致
  5. app.imy 内的 Python 模块清单与 .pyc magic（判断 CPython 版本）
  6. **依赖版本混装检测**：toga 0.2.x 元包与 toga_core 0.5.x 混装
     —— 这正是 v11.5 APK 实测到的构建链污染
  7. 版本一致性：APK 内 dist-info 版本 vs 期望版本
  8. 权限声明（INTERNET 等）

用法：
    python scripts/verify_apk.py --apk "path/to/app.apk"
    python scripts/verify_apk.py --apk ... --expect-version 13.0.0 --json
退出码：0 = 全部通过；1 = 有 WARN 且 --strict；2 = 有 FAIL。
"""
import argparse
import hashlib
import io
import json
import re
import struct
import sys
import zipfile

CHECKS = []


def check(name, ok, detail="", level="FAIL"):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": str(detail),
                   "level": level if not ok else "PASS"})
    print("%-5s %-38s %s" % ("PASS" if ok else level, name, detail))
    return ok


def pyc_magic_version(magic):
    """常见 CPython magic -> 版本（前 2 字节小端）。"""
    table = {3495: "3.11", 3531: "3.12", 3571: "3.13", 3439: "3.10",
             3425: "3.9", 3413: "3.8"}
    n = magic[0] | (magic[1] << 8)
    return table.get(n, "未知(magic=%d)" % n)


def analyze(apk_path, expect_version=None):
    with open(apk_path, "rb") as f:
        raw = f.read()
    print("=== APK 鉴定：%s（%d 字节）===" % (apk_path, len(raw)))
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()

    # 1) 基本结构
    for required in ("AndroidManifest.xml", "resources.arsc", "classes.dex"):
        check("包含 " + required, required in names)
    check("包含 classes.dex 且非空",
          "classes.dex" in names and z.getinfo("classes.dex").file_size > 1000)

    # 2) 签名
    sf = [n for n in names if n.startswith("META-INF/") and n.upper().endswith(".SF")]
    rsa = [n for n in names if n.startswith("META-INF/")
           and (n.upper().endswith(".RSA") or n.upper().endswith(".DSA")
                or n.upper().endswith(".EC"))]
    check("v1 (JAR) 签名", bool(sf) and bool(rsa),
          "SF=%d RSA/DSA=%d" % (len(sf), len(rsa)))
    v2 = raw.rfind(b"APK Sig Block 42")
    check("v2/v3 (APK Signing Block) 签名", v2 != -1,
          "偏移 %d" % v2)
    if v2 != -1:
        # 正确结构：[8B size][pairs][8B size][16B magic "APK Sig Block 42"]
        # v2 指向 magic 起点，因此尾部 size 在 v2-8，块起点 = v2+8-tail_size
        try:
            tail_size = struct.unpack("<Q", raw[v2 - 8:v2])[0]
            start = v2 + 8 - tail_size
            head_size = struct.unpack("<Q", raw[start:start + 8])[0]
            check("APK Signing Block 长度自洽",
                  head_size == tail_size and start >= 0,
                  "head=%d tail=%d start=%d" % (head_size, tail_size, start))
        except Exception as exc:                         # noqa: BLE001
            check("APK Signing Block 长度自洽", False, repr(exc))

    # 3) Chaquopy 资源
    for key in ("assets/chaquopy/app.imy", "assets/chaquopy/build.json",
                "assets/chaquopy/requirements-common.imy",
                "assets/chaquopy/stdlib-common.imy",
                "assets/chaquopy/cacert.pem"):
        check("包含 " + key.split("/")[-1], key in names)
    libs = [n for n in names if re.search(r"lib/[^/]+/libpython3\.11\.so", n)]
    check("含 CPython 3.11 原生库", len(libs) >= 1, "%d 个 ABI" % len(libs))

    # 4) build.json SHA1 一致性
    app_imy = None
    if "assets/chaquopy/app.imy" in names:
        app_imy = z.read("assets/chaquopy/app.imy")
    if "assets/chaquopy/build.json" in names and app_imy is not None:
        bj = json.loads(z.read("assets/chaquopy/build.json").decode("utf-8"))
        recorded = bj.get("assets", {}).get("app.imy", "")
        actual = hashlib.sha1(app_imy).hexdigest()
        check("build.json 中 app.imy 的 SHA1 匹配", recorded == actual,
              "记录=%s 实际=%s" % (recorded[:12], actual[:12]))
        pv = bj.get("python_version")
        if pv:
            check("build.json Python 版本为 3.11", str(pv).startswith("3.11"), str(pv))

    # 5) app.imy 模块与 pyc magic
    if app_imy is not None:
        try:
            az = zipfile.ZipFile(io.BytesIO(app_imy))
            mods = [n for n in az.namelist() if n.endswith(".pyc")]
            check("app.imy 含 starryandroid/app.pyc",
                  "starryandroid/app.pyc" in mods)
            check("app.imy 含 core 包", any(n.startswith("core/") for n in mods),
                  "%d 个模块" % len(mods))
            check("app.imy 含 v12 星尘模块 core/stardust.pyc",
                  "core/stardust.pyc" in mods,
                  "（v11.5 包不含，属预期差异）", level="WARN")
            sample = az.read("core/__init__.pyc")[:4]
            check("pyc magic 对应 CPython 3.11",
                  pyc_magic_version(sample).startswith("3.11"),
                  pyc_magic_version(sample))
        except Exception as exc:                         # noqa: BLE001
            check("app.imy 可解析", False, repr(exc))

    # 6) 依赖版本混装检测（v12.0 新增，v11.5 实测命中）
    req = "assets/chaquopy/requirements-common.imy"
    if req in names:
        rz = zipfile.ZipFile(io.BytesIO(z.read(req)))
        metas = [n for n in rz.namelist() if n.endswith(".dist-info/METADATA")]
        toga_versions = {}
        for m in metas:
            text = rz.read(m).decode("utf-8", "replace")
            nm = re.search(r"^Name:\s*(.+)$", text, re.M)
            ver = re.search(r"^Version:\s*(.+)$", text, re.M)
            if nm and ver and nm.group(1).strip().lower().startswith("toga"):
                toga_versions[nm.group(1).strip()] = ver.group(1).strip()
        print("     toga 系依赖：%s" % json.dumps(toga_versions, ensure_ascii=False))
        core_v = toga_versions.get("toga-core", "")
        meta_v = toga_versions.get("toga", "")
        mixed = bool(core_v and meta_v
                     and core_v.split(".")[:2] != meta_v.split(".")[:2])
        check("toga 元包与 toga-core 主版本一致（无 0.2/0.5 混装）",
              not mixed,
              "toga=%s, toga-core=%s" % (meta_v or "未装", core_v or "未装"))
        check("未混入 toga_gtk 旧后端",
              not any(k.lower() == "toga-gtk" and not v.startswith("0.5")
                      for k, v in toga_versions.items()),
              str({k: v for k, v in toga_versions.items()
                   if "gtk" in k.lower()}), level="WARN")
        # 后端 entry_points
        eps = [n for n in rz.namelist() if n.endswith("entry_points.txt")]
        backends = []
        for e in eps:
            t = rz.read(e).decode("utf-8", "replace")
            section = None
            for line in t.splitlines():
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                elif section == "toga.backends" and "=" in line:
                    backends.append(line.split("=", 1)[0].strip())
        check("存在 Android 后端注册", "android" in backends, str(backends))
    if expect_version and app_imy is not None:
        # 应用自身的 dist-info 在 app.imy 里（不是 requirements-common.imy）
        az = zipfile.ZipFile(io.BytesIO(app_imy))
        app_versions = set()
        for n in az.namelist():
            m = re.search(r"starryandroid-([0-9][^-]*)\.dist-info", n)
            if m:
                app_versions.add(m.group(1))
        check("APK 内应用版本 = %s" % expect_version,
              app_versions == {expect_version},
              "实测 %s" % (app_versions or "未找到 dist-info"))

    # 7) 权限（二进制 AXML 里做字符串探测，仅作提示）
    manifest = z.read("AndroidManifest.xml") if "AndroidManifest.xml" in names else b""
    # AXML 的字符串池以 UTF-16LE 存放，ASCII 直接搜会漏报
    needle = "android.permission.INTERNET"
    has_internet = (needle.encode("utf-16-le") in manifest
                    or needle.encode("ascii") in manifest)
    check("声明 INTERNET 权限", has_internet,
          "（AXML UTF-16LE 字符串探测，非完整解析）", level="WARN")

    # 汇总
    fails = [c for c in CHECKS if not c["ok"] and c["level"] == "FAIL"]
    warns = [c for c in CHECKS if not c["ok"] and c["level"] == "WARN"]
    print("\n==== 鉴定汇总：%d 项通过 / %d 项失败 / %d 项提示 ===="
          % (sum(1 for c in CHECKS if c["ok"]), len(fails), len(warns)))
    for c in fails:
        print("  FAIL", c["name"], c["detail"])
    for c in warns:
        print("  WARN", c["name"], c["detail"])
    return CHECKS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", required=True)
    ap.add_argument("--expect-version", default=None)
    ap.add_argument("--json", action="store_true", help="额外输出 JSON 报告到 stdout")
    ap.add_argument("--strict", action="store_true", help="WARN 也视为失败")
    args = ap.parse_args()
    checks = analyze(args.apk, args.expect_version)
    if args.json:
        print("\nJSON_REPORT=" + json.dumps(checks, ensure_ascii=False))
    fails = [c for c in checks if not c["ok"] and c["level"] == "FAIL"]
    warns = [c for c in checks if not c["ok"] and c["level"] == "WARN"]
    if fails:
        return 2
    if warns and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
