# -*- coding: utf-8 -*-
"""星语 Starry · CLI 版 EXE 子进程冒烟（v13.1，本机与 CI 共用）。

与 smoke_gui_exe.py 对称：直接启动真实 EXE，断言退出码与**输出内容**，
而不是只看「进程没崩」。覆盖 v12 / v13.0 / v13.1 的全部离线能力。

用法：
    python scripts/smoke_cli_exe.py --exe dist/星语Starry-CLI.exe \
        --expect-version 13.1.0
退出码 0 = 全通过。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True, help="CLI EXE 路径")
    ap.add_argument("--expect-version", default="", help="期望版本号（可选）")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    if not os.path.isfile(exe):
        print("CLI EXE 不存在：%s" % exe)
        return 2

    tmp = tempfile.mkdtemp(prefix="starry_cli_smoke_")
    env = dict(os.environ)
    env["STARRY_DATA_DIR"] = os.path.join(tmp, ".starry")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # 用真实 core 生成一份与本地技能同源的 hub.json（不是手写占位）
    from core import hub as hb
    manifest = hb.build_hub_manifest(hb.Hub().discover(),
                                     hub_version=args.expect_version or "1.0.0")
    hub_path = os.path.join(tmp, "hub.json")
    with open(hub_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    broken_hub = os.path.join(tmp, "missing.json")

    def run(flags):
        try:
            # 拿原始字节：Windows 中文控制台可能是 cp936，CI 可能强制 UTF-8。
            return subprocess.run([exe] + flags, capture_output=True,
                                  env=env, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            return None

    def decode(raw):
        """把 stdout/stderr 按多种候选编码解开，任一命中即算内容存在。"""
        parts = []
        for enc in ("utf-8", "gbk", "cp936", "cp1252", "latin-1"):
            try:
                parts.append(raw.decode(enc))
            except UnicodeDecodeError:
                continue
        return "\n".join(parts)

    def case(name, flags, rc=0, contains=()):
        p = run(flags)
        if p is None:
            check(name, False, "超时")
            return
        text = decode((p.stdout or b"") + (p.stderr or b""))
        ok = (p.returncode == rc) and all(s in text for s in contains)
        check(name, ok, "rc=%s" % p.returncode)
        if not ok:
            print("    输出片段：", text[:200].replace("\n", " | "))

    ver = args.expect_version
    case("--version 打印当前版本", ["--version"],
         contains=("星语 Starry", ver) if ver else ("星语 Starry",))
    case("--platform 打印平台", ["--platform"], contains=("平台",))
    case("--doctor 环境自检", ["--doctor"], contains=("环境自检",))
    case("--hub 列出随包技能", ["--hub"], contains=("Skills Hub",
                                                    "api-contract-review"))
    case("--hub-search 命中 api", ["--hub-search", "api"],
         contains=("api-contract-review",))
    case("--hub-info 输出正文", ["--hub-info", "release-checklist"],
         contains=("发版前检查清单", "## 指令正文"))
    case("--hub-source 追加技能源", ["--hub-source",
                                    os.path.join(ROOT, "skills"), "--hub"],
         contains=("release-checklist",))
    # v13.2：DeepSeek 来源、统一配置项与异常边界
    case("--hub 含 DeepSeek 提示词模板", ["--hub"],
         contains=("deepseek", "deepseek-code-review"))
    case("--hub-sources 来源开关", ["--hub-sources", "deepseek", "--hub"],
         contains=("deepseek-sql-review",))
    case("--hub-info 展示 DeepSeek 元数据",
         ["--hub-info", "deepseek-code-review"],
         contains=("DeepSeek 提示词元数据", "不调用 DeepSeek API"))
    case("--hub-config-show 打印生效配置", ["--hub-config-show"],
         contains=("deepseek", "allow_import", "max_depth"))
    case("--hub-config 读示例文件", ["--hub-config",
                                    os.path.join(ROOT, "config.hub.example.json"),
                                    "--hub-config-show"],
         contains=("config.hub.example.json",))
    case("--hub-diagnostics 打印诊断", ["--hub-diagnostics"],
         contains=("config", "sources", "errors"))
    case("--hub-config 缺文件安全拒绝",
         ["--hub-config", os.path.join(tmp, "missing_cfg.json"), "--hub"],
         rc=2, contains=("Hub 配置文件不存在",))
    case("--hub-update 同版本清单无更新",
         ["--hub-update", "--hub-manifest", hub_path],
         contains=("清单校验：通过", "已是最新"))
    case("--hub-manifest 缺文件安全拒绝",
         ["--hub-manifest", broken_hub], rc=2,
         contains=("读取 Hub 清单失败",))
    case("--workbench 实跑 100%", ["--workbench"],
         contains=("项目进度：**100%**",))
    case("--project --parallel 实跑 100%",
         ["--project", "离线冒烟目标", "--parallel", "--workers", "2"],
         contains=("100%",))
    case("--update-check 离线模式", ["--update-check"],
         contains=("离线",))
    case("--budget 上下文裁剪", ["--budget", "4096"], rc=0)
    case("--project-load 损坏存档被拒",
         ["--project-load", broken_hub], rc=2)

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n==== CLI EXE 冒烟：%d/%d 通过 ====" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
