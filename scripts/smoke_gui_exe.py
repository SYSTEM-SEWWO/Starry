# -*- coding: utf-8 -*-
"""星语 Starry · GUI 版 EXE 子进程冒烟（v13.1，本机与 CI 共用）。

为什么需要独立脚本：
    GUI EXE 是 PyInstaller `console=False` 的窗口程序，sys.stdout 可能为 None，
    且双击运行时看不到任何输出。因此 main.py 的 --version / --selftest 会把
    结果**写入 --out 指定的文件**；本脚本启动子进程后读取该文件来判定，
    避免因「拿不到 stdout」而误判为成功或失败。

用法：
    python scripts/smoke_gui_exe.py --exe dist/星语Starry.exe \
        --expect-version 13.1.0
退出码 0 = 全通过。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeError):
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, help="GUI EXE 路径")
    ap.add_argument("--expect-version", default="", help="期望版本号（可选）")
    ap.add_argument("--timeout", type=int, default=180,
                    help="单步子进程超时秒数（onefile 解压较慢）")
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    if not os.path.isfile(exe):
        print("GUI EXE 不存在：%s" % exe)
        return 2

    tmp = tempfile.mkdtemp(prefix="starry_gui_smoke_")
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"        # 无显示器也能建 QApplication
    env["STARRY_DATA_DIR"] = os.path.join(tmp, ".starry")
    env["PYTHONUTF8"] = "1"

    def run(flags):
        return subprocess.run([exe] + flags, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=env, timeout=args.timeout)

    # ---- 1) --version ----
    vout = os.path.join(tmp, "version.txt")
    try:
        p = run(["--version", "--out", vout])
        rc_version = p.returncode
    except subprocess.TimeoutExpired as exc:
        rc_version = -1
        check("--version 未超时", False, str(exc))
    else:
        check("--version 未超时", True)
    vtext = _read(vout)
    check("--version RC=0", rc_version == 0, "rc=%s" % rc_version)
    check("--version 结果已落盘", bool(vtext.strip()))
    check("--version 输出含产品名", "星语 Starry" in vtext)
    if args.expect_version:
        check("--version 版本号一致", args.expect_version in vtext)

    # ---- 2) --selftest ----
    sout = os.path.join(tmp, "selftest.json")
    try:
        p = run(["--selftest", "--out", sout])
        rc_selftest = p.returncode
    except subprocess.TimeoutExpired as exc:
        rc_selftest = -1
        check("--selftest 未超时", False, str(exc))
    else:
        check("--selftest 未超时", True)
    stext = _read(sout)
    check("--selftest RC=0", rc_selftest == 0, "rc=%s" % rc_selftest)
    data = None
    try:
        data = json.loads(stext)
    except (ValueError, TypeError):
        pass
    check("--selftest 输出合法 JSON", isinstance(data, dict))
    if isinstance(data, dict):
        check("--selftest 全项通过",
              data.get("total", 0) > 0 and data.get("passed") == data.get("total"),
              "%s/%s" % (data.get("passed"), data.get("total")))
        names = [c.get("name", "") for c in data.get("checks", [])]
        check("自检覆盖随包 skills/", any("随包 skills" in n for n in names))
        check("自检覆盖 HubDialog", any("HubDialog" in n for n in names))
        check("自检覆盖 WorkbenchDialog",
              any("WorkbenchDialog" in n for n in names))
        check("自检覆盖 DeepSeek 来源",
              any("deepseek" in n.lower() for n in names))
        check("自检覆盖 401 分类与脱敏",
              any("401 归为鉴权类" in n for n in names)
              and any("脱敏" in n for n in names))
        check("自检覆盖配置隔离",
              any("STARRY_DATA_DIR" in n for n in names))
        check("自检覆盖 API 诊断面板",
              any("ApiDiag" in n for n in names))
        if args.expect_version:
            check("自检版本一致", data.get("version") == args.expect_version)
        for c in data.get("checks", []):
            if not c.get("ok"):
                print("  x 失败项：", c.get("name"))

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n==== GUI EXE 冒烟：%d/%d 通过 ====" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
