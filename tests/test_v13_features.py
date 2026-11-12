# -*- coding: utf-8 -*-
"""星语 Starry v13.0 · 大版本新功能单测（整体项目 / 多线并行 / 自动更新）。

运行：python tests/test_v13_features.py    （退出码 0 = 全绿）

设计原则与 v12.0 一致：
  - 只测**真实 core 模块**，不用 fake core 掩盖签名错误；
  - 全部离线、确定性，不联网、不调模型、不需要 API Key；
  - 用 STARRY_DATA_DIR 隔离配置目录，绝不读写用户真实数据；
  - 同时校验 CLI 接入、桌面命令面板入口、打包 hiddenimports 与版本真源，
    让「功能写了但没接进产物」这类问题在 CI 里直接暴露。
"""
import ast
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 任何配置读写都落进临时目录（Windows 上 expanduser("~") 读 USERPROFILE，
# 因此必须用项目显式契约 STARRY_DATA_DIR，而不是 HOME/APPDATA）
_TMP = tempfile.mkdtemp(prefix="starry_v13_test_")
os.environ["STARRY_DATA_DIR"] = os.path.join(_TMP, ".starry")

from core import project as pj                     # noqa: E402
from core import parallel as pl                      # noqa: E402
from core import updatecheck as uc                   # noqa: E402
from core import config as cfg_mod                   # noqa: E402
from core import cli as cli_mod                     # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


def cli_run(argv):
    buf = io.StringIO()
    rc = cli_mod.run_cli(argv, out=buf)
    return rc, buf.getvalue()


# ===========================================================================
# 1) core.project · 整体项目状态机
# ===========================================================================
t = pj.new_task("资料盘点", "check", {"text": "目标"}, depends=["t0"])
check("new_task 状态初始 pending", t["status"] == pj.TASK_PENDING)
check("new_task depends 转字符串列表", t["depends"] == ["t0"])
check("new_task 非法 kind 回退 text",
      pj.new_task("x", "unknown")["kind"] == "text")
check("new_task 非 dict payload 被包装",
      pj.new_task("x", payload="原始文本")["payload"] == {"text": "原始文本"})
check("new_task 空 payload 为 {}", pj.new_task("x")["payload"] == {})

p = pj.create_project("发版", "目标", ["盘点", {"title": "提炼", "kind": "text"}])
check("create_project 混合输入任务数", len(p["tasks"]) == 2)
check("create_project 生成 t1/t2", [x["id"] for x in p["tasks"]] == ["t1", "t2"])
dup = pj.create_project("x", "", [
    {"title": "A", "id": "same"}, {"title": "B", "id": "same"}])
check("create_project 重复 id 自动去重",
      [x["id"] for x in dup["tasks"]] == ["same", "same-2"])

p2 = pj.add_task(p, "汇总", "report", depends=["t1"])
check("add_task 不修改入参", len(p["tasks"]) == 2 and len(p2["tasks"]) == 3)
p3 = pj.add_task(p2, "汇总", task_id="t1")
check("add_task 冲突 id 自动改名", pj.find_task(p3, "t1-2") is not None)

p4 = pj.update_task(p2, "汇总", status=pj.TASK_DONE, result={"ok": 1})
check("update_task 不修改入参", pj.find_task(p2, "汇总")["status"] == pj.TASK_PENDING)
check("update_task 写入状态与结果",
      pj.find_task(p4, "汇总")["status"] == pj.TASK_DONE
      and pj.find_task(p4, "汇总")["result"] == {"ok": 1})
check("update_task 非法状态回退 failed",
      pj.find_task(pj.update_task(p2, "t1", status="乱写"), "t1")["status"]
      == pj.TASK_FAILED)
check("update_task 找不到任务不抛",
      pj.update_task(p2, "不存在")["tasks"] == p2["tasks"])
check("find_task 未命中返回 None", pj.find_task(p, "nope") is None)

plan = pj.plan_from_goal("调研并撰写 v13 发版方案")
check("plan_from_goal 默认 4 任务", len(plan["tasks"]) == 4)
check("plan_from_goal 第一波 3 条并行",
      [x["id"] for x in pj.ready_tasks(plan)] == ["t1", "t2", "t3"])
check("plan_from_goal 汇总依赖前三条",
      plan["tasks"][3]["depends"] == ["t1", "t2", "t3"])
check("project_progress 空项目全 0",
      pj.project_progress({})["percent"] == 0
      and pj.project_progress({})["total"] == 0)
check("project_progress pending 统计", pj.project_progress(plan)["pending"] == 4)

# 分波：done 一条后，依赖它的任务仍不 ready
wave = pj.update_task(plan, "t1", status=pj.TASK_DONE)
check("ready_tasks 只放行依赖全 done 的任务",
      [x["id"] for x in pj.ready_tasks(wave)] == ["t2", "t3"])
wave = wave.copy()
for tid in ("t2", "t3"):
    wave = pj.update_task(wave, tid, status=pj.TASK_DONE)
check("第二波放行汇总任务",
      [x["id"] for x in pj.ready_tasks(wave)] == ["t4"])

# .starryproj 存档
blob = pj.pack_project(plan)
check("pack_project 是合法 JSON", isinstance(json.loads(blob), dict))
check("pack/unpack 往返一致", pj.unpack_project(blob) == plan)
check("project_digest 确定性",
      pj.project_digest(plan) == pj.project_digest(pj.clone(plan)))
env = json.loads(blob)
for label, mutate in (
        ("非法 JSON", lambda e: "{not json"),
        ("错 magic", lambda e: dict(e, magic="NOPE")),
        ("版本越界", lambda e: dict(e, version=99)),
        ("缺 tasks", lambda e: dict(e, payload={"title": "x"})),
        ("checksum 篡改", lambda e: dict(e, checksum="0" * 64))):
    bad = mutate(env.copy())
    text = bad if isinstance(bad, str) else json.dumps(bad, ensure_ascii=False)
    try:
        pj.unpack_project(text)
        check("unpack 拒绝「%s」" % label, False)
    except ValueError:
        check("unpack 拒绝「%s」" % label, True)

md = pj.render_project_markdown(plan)
check("render_project_markdown 含标题与表格",
      "# 项目" in md and "| 状态 | 任务 | 类型 | 依赖 |" in md)
check("render_project_markdown 可附并行报告",
      "## 多线并行执行" in pj.render_project_markdown(
          plan, {"workers": 4, "ok": 1, "failed": 0,
                 "elapsed_ms": 1, "results": []}))


# ===========================================================================
# 2) core.parallel · 多线并行执行器
# ===========================================================================
check("split_work 轮转分配",
      pl.split_work([1, 2, 3, 4, 5], 2) == [[1, 3, 5], [2, 4]])
check("split_work lanes=0 回退 1", len(pl.split_work([1], 0)) == 1)
check("split_work 空输入", pl.split_work([], 3) == [[], [], []])

lw = pl.local_worker
check("local_worker text 统计",
      lw({"kind": "text", "payload": {"text": "你好世界 hello world"}})["chars"] > 0)
check("local_worker check 非空判定",
      lw({"kind": "check", "payload": {"text": "有内容"}})["passed"] is True)
check("local_worker check 空文本不通过",
      lw({"kind": "check", "payload": {"text": "  "}})["passed"] is False)
check("local_worker report 生成 Markdown",
      lw({"kind": "report", "title": "汇总",
          "payload": {"text": "正文"}})["markdown"].startswith("### 汇总"))
try:
    lw({"kind": "chat", "payload": {"text": "x"}})
    check("local_worker chat 明确报错", False)
except RuntimeError:
    check("local_worker chat 明确报错", True)

check("run_parallel 空任务", pl.run_parallel([])["total"] == 0)
slow_first = lambda j: (time.sleep(0.02) if j.get("id") == "a" else None) or j["id"]
r = pl.run_parallel([{"id": "a", "title": "A"}, {"id": "b", "title": "B"},
                     {"id": "c", "title": "C"}],
                    worker=slow_first, max_workers=3)
check("run_parallel 结果按输入顺序", r["order"] == ["a", "b", "c"])
check("run_parallel 全部成功", r["ok"] == 3 and r["failed"] == 0)
check("run_parallel 记录并行度", r["workers"] == 3)

def flaky(job):
    if job["id"] == "bad":
        raise RuntimeError("故意失败")
    return "ok"

r = pl.run_parallel([{"id": "good"}, {"id": "bad"}],
                    worker=flaky, max_workers=2)
check("run_parallel 单线异常隔离",
      r["results"][0]["ok"] and not r["results"][1]["ok"])
check("run_parallel 异常带类型信息", "RuntimeError" in r["results"][1]["error"])

calls = {"n": 0}
def retry_then_ok(job):
    calls["n"] += 1
    if calls["n"] < 3:
        raise ValueError("临时失败")
    return "recovered"

r = pl.run_parallel([{"id": "x"}], worker=retry_then_ok, retries=2)
check("run_parallel 重试后成功", r["results"][0]["value"] == "recovered")
check("run_parallel 重试次数符合", calls["n"] == 3)

r = pl.run_parallel([{"id": "a"}, {"id": "b"}],
                    worker=lambda j: time.sleep(0.3), timeout=0.05,
                    max_workers=2)
check("run_parallel 超时被标记", r["timed_out"] is True)
check("run_parallel 超时后结果仍完整", len(r["results"]) == 2)

done, waves = pl.run_project(plan, worker=pl.local_worker, max_workers=4)
check("run_project 分成 2 波", len(waves) == 2)
check("run_project 第一波 3 条", waves[0]["total"] == 3)
check("run_project 第二波 1 条", waves[1]["total"] == 1)
check("run_project 项目 100% 完成", pj.project_progress(done)["complete"] is True)
check("run_project 进度 100%", pj.project_progress(done)["percent"] == 100)
check("run_project 不修改入参", pj.project_progress(plan)["pending"] == 4)
check("run_project 结果已回填",
      all(x["result"] is not None for x in done["tasks"]))

fail_plan = pj.create_project("失败链", "", [
    {"title": "会失败", "kind": "chat", "payload": {"text": "x"}},
    {"title": "依赖它", "depends": ["t1"], "kind": "text"},
])
failed, _ = pl.run_project(fail_plan, worker=pl.local_worker, max_workers=2)
check("依赖失败时上游标记 failed", pj.find_task(failed, "t1")["status"] == "failed")
check("依赖失败时下游标记 skipped",
      pj.find_task(failed, "t2")["status"] == "skipped")

cycle = pj.create_project("循环依赖", "", [
    {"title": "A", "depends": ["t2"]}, {"title": "B", "depends": ["t1"]},
])
cycled, cw = pl.run_project(cycle, worker=pl.local_worker, max_workers=2)
check("循环依赖不死循环", cw == [] and pj.project_progress(cycled)["skipped"] == 2)

merged = pl.merge_results(r if False else waves[0])
check("merge_results 生成表格", "| # | 线 | 状态 | 结果 / 错误 |" in merged)
check("merge_results 标题可定制", "## 自定义" in pl.merge_results(
    waves[0], "自定义"))


# ===========================================================================
# 3) core.updatecheck · 自动更新纯逻辑
# ===========================================================================
for raw, want in (("win32", "windows"), ("exe", "windows"), ("uos", "linux"),
                  ("deb", "linux"), ("apk", "android"), ("darwin", "macos"),
                  ("android", "android")):
    check("normalize_platform %s -> %s" % (raw, want),
          uc.normalize_platform(raw) == want)
check("normalize_platform 未知平台为空", uc.normalize_platform("solaris") == "")
check("parse_version 提取数字", uc.parse_version("v13.2.1-beta") == (13, 2, 1))
check("compare_versions 主版本优先", uc.compare_versions("13.0.0", "12.9.9") == 1)
check("compare_versions 补零比较", uc.compare_versions("13.0", "13.0.0") == 0)
check("is_newer 同版本为否", uc.is_newer("13.0.0", "13.0.0") is False)

REMOTE_VERSION = "99.0.0"   # 永远高于当前版本，避免测试与发版号耦合
ASSETS = [
    {"platform": "windows", "name": "starry.exe",
     "url": "https://example.com/s.exe", "sha256": "a" * 64, "size": 123},
    {"platform": "linux", "name": "starry.deb",
     "url": "https://example.com/s.deb", "sha256": "b" * 64, "size": 456},
]
manifest = uc.build_manifest(REMOTE_VERSION, assets=ASSETS,
                           notes="v13 大版本")
check("build_manifest 自带 digest", len(manifest["digest"]) == 64)
check("manifest_digest 不受 digest 字段影响",
      uc.manifest_digest(manifest) == uc.manifest_digest(
          dict(manifest, digest="wrong")))
check("validate_manifest 正常清单通过", uc.validate_manifest(manifest) == (True, "OK"))

for label, mutate in (
        ("非对象", lambda m: []),
        ("错 magic", lambda m: dict(m, magic="X")),
        ("错 schema", lambda m: dict(m, schema=9)),
        ("app_version 非法", lambda m: dict(m, app_version="abc")),
        ("digest 篡改", lambda m: dict(m, notes="被改")),
        ("assets 为空", lambda m: dict(m, assets=[])),
        ("platform 非法", lambda m: dict(m, assets=[dict(ASSETS[0], platform="x")])),
        ("url 非法", lambda m: dict(m, assets=[dict(ASSETS[0], url="ftp://x")])),
        ("sha256 长度错", lambda m: dict(m, assets=[dict(ASSETS[0], sha256="abc")])),
        ("size 非整数", lambda m: dict(m, assets=[dict(ASSETS[0], size="123")]))):
    obj = mutate(manifest.copy())
    ok, _ = uc.validate_manifest(obj)
    check("validate_manifest 拒绝「%s」" % label, ok is False)

check("select_asset 平台匹配", uc.select_asset(manifest, "win32")["name"] == "starry.exe")
check("select_asset 无匹配返回 None", uc.select_asset(manifest, "macos") is None)

f = os.path.join(_TMP, "asset.bin")
with open(f, "wb") as fh:
    fh.write(b"starry-v13-binary")
digest = hashlib.sha256(b"starry-v13-binary").hexdigest()
check("verify_asset_sha256 正确哈希", uc.verify_asset_sha256(f, digest))
check("verify_asset_sha256 错误哈希", not uc.verify_asset_sha256(f, "0" * 64))
check("verify_asset_sha256 非法期望值", not uc.verify_asset_sha256(f, "x"))
check("verify_asset_sha256 文件不存在",
      not uc.verify_asset_sha256(f + ".missing", digest))

r = uc.check_update("12.0.0", manifest, "windows")
check("check_update 发现新版本", r["update_available"] is True)
check("check_update 清单有效", r["manifest_valid"] is True)
check("check_update 选中平台资产", r["asset"]["name"] == "starry.exe")
r = uc.check_update(REMOTE_VERSION, manifest, "windows")
check("check_update 同版本不更新", r["update_available"] is False)
check("check_update 给出「已是最新」", "已是最新" in r["reason"])
r = uc.check_update("12.0.0", manifest, "macos")
check("check_update 无平台资产仍报更新",
      r["update_available"] and r["asset"] is None)
r = uc.check_update("12.0.0", {"magic": "BAD"}, "windows")
check("check_update 非法清单收敛不抛",
      r["manifest_valid"] is False and r["update_available"] is False)

_old = os.environ.get("STARRY_UPDATE_URL")
os.environ.pop("STARRY_UPDATE_URL", None)
check("configured_manifest_url 未配置为空", uc.configured_manifest_url() == "")
os.environ["STARRY_UPDATE_URL"] = "  https://example.com/update.json  "
check("configured_manifest_url 读取并去空白",
      uc.configured_manifest_url() == "https://example.com/update.json")
if _old is None:
    os.environ.pop("STARRY_UPDATE_URL", None)
else:
    os.environ["STARRY_UPDATE_URL"] = _old

mpath = os.path.join(_TMP, "update.json")
with open(mpath, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, ensure_ascii=False)
check("load_manifest 读回一致", uc.load_manifest(mpath) == manifest)
try:
    uc.load_manifest(mpath + ".missing")
    check("load_manifest 缺失文件报错", False)
except ValueError:
    check("load_manifest 缺失文件报错", True)


# ===========================================================================
# 4) CLI 接入（真实 run_cli，注入 StringIO）
# ===========================================================================
parser = cli_mod.build_arg_parser()
for opt in ("--project", "--project-load", "--project-save", "--parallel",
            "--workers", "--timeout", "--retries", "--execute",
            "--update-check", "--update-manifest", "--update-url", "--workbench"):
    check("CLI 参数 %s 已注册" % opt,
          any(opt in a.option_strings for a in parser._actions))

rc, out = cli_run(["--project", "调研并撰写发版方案"])
check("CLI --project rc=0", rc == 0)
check("CLI --project 输出项目报告", "# 项目" in out and "结果复核与汇总" in out)
check("CLI --project 未执行（进度 0%）", "进度：0%" in out)

rc, out = cli_run(["--project", "调研并撰写发版方案", "--parallel", "--workers", "3"])
check("CLI --parallel rc=0", rc == 0)
check("CLI --parallel 进度 100%", "进度：100%" in out)
check("CLI --parallel 输出汇总", "多线并行汇总" in out)
check("CLI --parallel 遵守 --workers", "并行度 3" in out)

proj_file = os.path.join(_TMP, "saved.starryproj")
rc, out = cli_run(["--project", "写一本书", "--parallel",
                   "--project-save", proj_file])
check("CLI --project-save 落盘", rc == 0 and os.path.exists(proj_file))
check("CLI --project-save 存的是执行后状态",
      pj.project_progress(pj.unpack_project(
          open(proj_file, encoding="utf-8").read()))["complete"] is True)
rc, out = cli_run(["--project-load", proj_file])
check("CLI --project-load rc=0", rc == 0 and "写一本书" in out)

with open(proj_file, "w", encoding="utf-8") as fh:
    fh.write(json.dumps(dict(json.loads(pj.pack_project(plan)), magic="BAD"),
                        ensure_ascii=False))
rc, out = cli_run(["--project-load", proj_file])
check("CLI 拒绝损坏项目", rc == 2 and "拒绝载入" in out)
check("CLI 拒绝损坏项目不重复刷屏", out.count("没有可处理的项目") == 0)

os.environ.pop("STARRY_UPDATE_URL", None)
rc, out = cli_run(["--update-check"])
check("CLI --update-check 离线 rc=0", rc == 0)
check("CLI --update-check 明确未联网", "未发起任何网络请求" in out)
check("CLI --update-check 给出配置指引", "STARRY_UPDATE_URL" in out)

with open(mpath, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, ensure_ascii=False)
rc, out = cli_run(["--update-check", "--update-manifest", mpath])
check("CLI 本地清单 rc=0", rc == 0)
check("CLI 本地清单校验通过", "清单校验：通过" in out)
check("CLI 本地清单发现新版本",
      ("发现新版本 %s" % REMOTE_VERSION) in out)
check("CLI 本地清单列出资产哈希", "a" * 64 in out)
check("CLI 不自动下载", "不自动下载" in out)

bad_manifest = os.path.join(_TMP, "bad-update.json")
with open(bad_manifest, "w", encoding="utf-8") as fh:
    json.dump(dict(manifest, notes="被篡改"), fh, ensure_ascii=False)
rc, out = cli_run(["--update-check", "--update-manifest", bad_manifest])
check("CLI 篡改清单不报可用更新",
      "清单校验：失败" in out and "发现新版本" not in out)

rc, out = cli_run(["--workbench"])
check("CLI --workbench rc=0", rc == 0)
for sec in ("## 1 · 运行环境", "## 2 · 整体项目", "## 3 · 多线并行执行",
            "## 4 · 自动更新", "## 5 · 常用命令"):
    check("CLI --workbench 含「%s」" % sec, sec in out)
check("CLI --workbench 实际跑完并行", "项目进度：**100%**" in out)
check("CLI --workbench 显示 2 波", "波次：**2**" in out)
check("CLI --workbench 显示当前版本", cfg_mod.APP_VERSION in out)


# ===========================================================================
# 5) 产物接入：懒导出 / 打包 / 桌面命令面板 / 版本真源
# ===========================================================================
import core as core_pkg                                       # noqa: E402
for mod in ("project", "parallel", "updatecheck", "stardust"):
    check("core 懒导出 %s" % mod,
          hasattr(core_pkg, mod) and mod in core_pkg.__all__)

spec = open(os.path.join(ROOT, "starry_cli.spec"), encoding="utf-8").read()
for mod in ("core.project", "core.parallel", "core.updatecheck"):
    check("PyInstaller hiddenimports 含 %s" % mod, '"%s"' % mod in spec)

assistant_src = open(os.path.join(ROOT, "app", "assistant.py"),
                    encoding="utf-8").read()
tree = ast.parse(assistant_src)
ids = set()
for node in ast.walk(tree):
    if (isinstance(node, ast.Tuple) and node.elts
            and isinstance(node.elts[0], ast.Constant)
            and isinstance(node.elts[0].value, str)):
        ids.add(node.elts[0].value)
for cid in ("workbench", "project_plan", "project_run", "project_save",
            "project_load", "update_check"):
    check("命令面板含 v13 命令 %s" % cid, cid in ids)

# v13.1：不再把测试钉死在单一发版号（资深程序员复审 P0-2 的闭环）。
# 只要求「符合 SemVer 且不低于 v13.0」，后续升版不必再改这条断言。
def _ver_tuple(text):
    try:
        return tuple(int(x) for x in str(text).split(".")[:3])
    except (TypeError, ValueError):
        return (0, 0, 0)


check("APP_VERSION 符合 SemVer 且不低于 13.0.0",
      len(cfg_mod.APP_VERSION.split(".")) == 3
      and _ver_tuple(cfg_mod.APP_VERSION) >= (13, 0, 0))
mcp = open(os.path.join(ROOT, "core", "mcp.py"), encoding="utf-8").read()
check("MCP CLIENT_INFO 版本与 APP_VERSION 同步",
      '"version": "%s"' % cfg_mod.APP_VERSION in mcp)
pyproject = open(os.path.join(ROOT, "android", "pyproject.toml"),
                 encoding="utf-8").read()
check("Android 工程版本与 APP_VERSION 同步",
      'version = "%s"' % cfg_mod.APP_VERSION in pyproject)


# ===========================================================================
# 6) 更新清单生成器（防止把 apk/README.md 误判为 android 资产）
# ===========================================================================
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import gen_update_manifest as gum                          # noqa: E402

check("platform_of 不把 apk/README.md 当资产",
      gum.platform_of(os.path.join("apk", "README.md")) == "")
check("platform_of 排除 update.json", gum.platform_of("update.json") == "")
check("platform_of 识别 exe/deb/apk",
      gum.platform_of("windows/a.exe") == "windows"
      and gum.platform_of("linux/a.deb") == "linux"
      and gum.platform_of("apk/a.apk") == "android")

gdir = os.path.join(_TMP, "gen_assets")
os.makedirs(os.path.join(gdir, "apk"), exist_ok=True)
os.makedirs(os.path.join(gdir, "windows"), exist_ok=True)
with open(os.path.join(gdir, "windows", "dummy.exe"), "wb") as fh:
    fh.write(b"exe-bytes")
with open(os.path.join(gdir, "apk", "README.md"), "w", encoding="utf-8") as fh:
    fh.write("说明：本机无 APK")
gout = os.path.join(_TMP, "gen_update.json")
rc = subprocess.run(
    [sys.executable, os.path.join(ROOT, "scripts", "gen_update_manifest.py"),
     "--version", cfg_mod.APP_VERSION, "--assets-dir", gdir,
     "--repo", "example/starry", "--out", gout, "--online"],
    capture_output=True, text=True, encoding="utf-8", errors="replace")
check("生成器在含 README 的 apk/ 目录下仍成功", rc.returncode == 0,
      rc.stderr[:120])
if rc.returncode == 0:
    gen = json.load(open(gout, encoding="utf-8"))
    check("生成器只收录真实二进制资产",
          [a["platform"] for a in gen["assets"]] == ["windows"])
    check("生成器清单通过 validate_manifest",
          uc.validate_manifest(gen) == (True, "OK"))
    check("生成器哈希来自真实字节",
          gen["assets"][0]["sha256"]
          == hashlib.sha256(b"exe-bytes").hexdigest())
    check("生成器 formal 模式写入真实仓库 URL",
          "example/starry" in gen["assets"][0]["url"])

empty = os.path.join(_TMP, "empty_assets")
os.makedirs(empty, exist_ok=True)
rc = subprocess.run(
    [sys.executable, os.path.join(ROOT, "scripts", "gen_update_manifest.py"),
     "--version", cfg_mod.APP_VERSION, "--assets-dir", empty,
     "--out", os.path.join(_TMP, "empty.json")],
    capture_output=True, text=True, encoding="utf-8", errors="replace")
check("生成器拒绝生成空清单", rc.returncode != 0)
check("空清单确实未落盘",
      not os.path.exists(os.path.join(_TMP, "empty.json")))


total = len(RESULTS)
passed = sum(1 for _, ok, _ in RESULTS if ok)
print("\n==== v13.0 新功能单测：%d/%d 通过 ====" % (passed, total))
for name, ok, extra in RESULTS:
    if not ok:
        print("  x", name, extra)
sys.exit(0 if passed == total else 1)
