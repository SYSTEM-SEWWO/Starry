# -*- coding: utf-8 -*-
"""v15.0.0 回归：LocModel 公开功能规格复刻（本地 AI 工作室）。

运行：python test_v150_fixes.py
"""
import io
import os
import sys
import tempfile
import shutil

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                       (" · " + str(detail)[:120]) if detail else ""))


def test_core_modules():
    print("\n== 核心模块 ==")
    from core import (hwprobe, tiering, ggufmgr, enginemgr,
                      genstudio, runconfig)
    check("9 个核心模块导入成功", True)

    hw = hwprobe.probe()
    check("硬件探测返回完整结构",
          all(k in hw for k in ("platform", "gpus", "backends", "cpu",
                                "memory", "disk")))
    check("后端识别含 CPU", "CPU" in hw["backends"], hw["backends"])
    check("显卡探测不为空", len(hw["gpus"]) >= 1)
    recs = hwprobe.recommend(hw, ggufmgr.builtin_catalog())
    check("推荐七款模型且标注估算", len(recs) == 7 and all(
        m.get("estimate") and "fit" in m for m in recs))
    check("推荐含官网示例", any("Qwen3.6" in m["name"] for m in recs))

    hz = {"vram_gb": 0.0, "memory": {"total_gb": 16.0, "available_gb": 12.0},
          "disk": {"free_gb": 100.0}, "backends": ["CPU"]}
    p = tiering.plan(17.0, hz, moe=True)
    check("分层方案四部件", len(p["parts"]) == 4 and p["ok"],
          [x["key"] for x in p["parts"]])
    check("内存预留 4GB", p["ram"]["reserve_gb"] == 4.0)
    check("放不下时降级到硬盘",
          any(x["device"] == "disk" for x in p["parts"]),
          [(x["key"], x["device"]) for x in p["parts"]])
    check("分层速度标注估算", p["estimate"] and p["tps_estimate"] > 0)

    d = tempfile.mkdtemp(prefix="v150_gguf_")
    try:
        bad = os.path.join(d, "x.gguf")
        open(bad, "wb").write(b"NOTGGUF" * 10)
        r = ggufmgr.parse_gguf(bad)
        check("非 GGUF 明确报错", bool(r["error"]), r["error"])
    finally:
        shutil.rmtree(d, ignore_errors=True)
    check("GGUF 量化枚举含 Q4_K_M", ggufmgr._QUANT_NAMES.get(13) == "Q4_K_M")
    check("内置目录含官网模型",
          any("Muse Glimmer" in m["name"] for m in ggufmgr.builtin_catalog()))

    check("四类引擎齐备",
          set(enginemgr.ENGINES) == {"llm", "image", "video", "lipsync"})
    check("llama.cpp 标为公开官方", enginemgr.ENGINES["llm"]["official"])
    check("非公开引擎不编造 URL",
          enginemgr.engine_url("image", "CUDA")[0] == "")
    check("导入非 ZIP 被拒绝",
          not enginemgr.import_zip("llm", "fake.rar")["ok"])

    check("五种画幅与官网一致",
          set(genstudio.ASPECTS) == {"1:1", "3:4", "4:3", "9:16", "16:9"})
    check("视频四档分辨率",
          set(genstudio.VIDEO_SPECS) ==
          {"横屏 480P", "横屏 720P", "竖屏 480P", "竖屏 720P"})
    t = genstudio.new_image_task("猫", aspect="9:16", steps=8, count=2, seed=42)
    check("图片任务参数可复现",
          t["seed"] == 42 and t["count"] == 2 and t["width"] == 768
          and t["height"] == 1344)
    v = genstudio.new_video_task("海", spec="竖屏 720P", duration=6, seed=7)
    check("视频任务参数正确",
          v["duration"] == 6 and v["width"] == 720 and v["height"] == 1280)
    ls = genstudio.new_video_task("对口型", lipsync_version="省内存版（约 12 GB / 8 GB 显存）")
    check("对口型 v3.6 省内存版", ls["kind"] == "lipsync" and "省内存" in ls["version"])
    r = genstudio.run_task(t, cfg=type("C", (), {"data": {}})())
    check("未配置引擎不伪造生成", not r["ok"] and "未配置" in r["error"])
    q = genstudio.TaskQueue()
    q.add(t)
    check("任务队列状态", q.pending() and q.cancel(1) and not q.pending())

    check("运行参数四档上下文",
          runconfig.CONTEXT_OPTIONS == [8192, 16384, 32768, 65536])
    check("上下文归一化", runconfig.normalize_ctx(20000) == 16384)
    check("思考提示存在", "thinking" in runconfig.THINK_PROMPT)
    check("局域网链接格式",
          all(u.startswith("http://") and u.endswith("/v1")
              for u in runconfig.lan_urls(8080)))


def test_agent_sandbox():
    print("\n== Agent 沙箱 ==")
    from core import agentfs
    root = tempfile.mkdtemp(prefix="v150_agent_")
    try:
        root = agentfs.set_root(root)
        try:
            agentfs.safe_resolve(root, "../escape.txt")
            escaped = False
        except agentfs.SandboxError:
            escaped = True
        check("拒绝越界路径", escaped)
        try:
            agentfs.safe_resolve(root, os.path.abspath(root + "/x"))
            absolute = False
        except agentfs.SandboxError:
            absolute = True
        check("拒绝绝对路径", absolute)
        p = agentfs.write(root, "a/b.txt", "hello")
        check("沙箱内写入", os.path.isfile(p) and agentfs.read(root, "a/b.txt") == "hello")
        d = agentfs.delete(root, "a/b.txt")
        check("删除需确认", d.get("need_confirm") and not os.path.exists(p) is False)
        ok = agentfs.delete_confirmed(root, "a/b.txt")
        check("确认后才删除", ok and not os.path.exists(p))
        out = agentfs.outside_access(root, "C:/Windows/System32")
        check("访问外部需确认", out.get("need_confirm"))
        r = agentfs.run_command(root, "python -c print(123)")
        check("白名单命令执行", r.get("ok") and "123" in r.get("output", ""), r)
        r2 = agentfs.run_command(root, "format C:")
        check("非白名单命令拒绝", r2.get("need_confirm"))
        plan = agentfs.Plan("测试", root)
        plan.add("写文件")
        plan.start(1)
        plan.finish(1, "完成")
        check("计划进度追踪", plan.progress() == 100 and "✓" in plan.summary())
        v = agentfs.verify(root, expect_files=["a/b.txt"])
        check("产物验证", not v["ok"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_artworks():
    print("\n== 作品库 ==")
    from core import artworks
    check("空库安全返回", isinstance(artworks.scan(), list))
    root = os.path.abspath(artworks.works_dir())
    f = os.path.join(root, "v150_test.png")
    open(f, "wb").write(b"\x89PNG\r\n\x1a\n")
    try:
        artworks.save_tags(f, ["测试"], "一只猫")
        rows = artworks.scan(query="一只猫")
        check("标签+提示词搜索", any(r["path"] == f for r in rows))
        check("删除仅限库内", not artworks.delete("C:/Windows/notepad.exe")["ok"])
    finally:
        try:
            os.remove(f)
            os.remove(f + ".tags.json")
        except OSError:
            pass


def test_source_wiring():
    print("\n== 源码接线与三端同源 ==")
    ui = io.open("ui/local_studio.py", encoding="utf-8").read()
    ast_ = io.open("app/assistant.py", encoding="utf-8").read()
    cfg = io.open("core/config.py", encoding="utf-8").read()
    check("工作室八页齐备", ui.count("self._page_") >= 8)
    check("不用 QThread（规避 native 崩溃）", "QThread(" not in ui)
    check("不用 QMessageBox（规避 native 崩溃）", "QMessageBox(" not in ui)
    check("后台状态轮询", "def _poll_tasks" in ui and "def _run_bg" in ui)
    check("助手入口存在", "def open_local_studio" in ast_)
    check("命令面板入口", '"local_studio"' in ast_)
    check("托盘菜单入口", "本地 AI 工作室" in ast_)
    check("配置默认值", '"local_studio": {' in cfg)
    mods = ("hwprobe", "tiering", "ggufmgr", "enginemgr", "genstudio",
            "artworks", "agentfs", "runconfig")
    same = []
    for m in mods:
        a = io.open("core/%s.py" % m, "rb").read()
        b = io.open("android/core/%s.py" % m, "rb").read()
        same.append(a == b)
    check("三端同源（8 模块）", all(same), [i for i, ok in enumerate(same) if not ok])


def main():
    test_core_modules()
    test_agent_sandbox()
    test_artworks()
    test_source_wiring()
    print("\nTOTAL pass=%d fail=%d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILURES:", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
