# -*- coding: utf-8 -*-
"""星语 Starry v13.1 · Skills Hub 单测（多生态兼容 / 更新判定 / 接入门禁）。

运行：python tests/test_v13_1_hub.py    （退出码 0 = 全绿）

设计原则与 v13.0 一致：
  - 只测**真实 core.hub**，不用 fake 模块掩盖签名或返回值错误；
  - 全部离线、确定性，不联网、不调模型、不读写用户真实 skills 目录；
  - 用 STARRY_DATA_DIR 隔离配置目录；
  - 除了纯逻辑，还校验「功能是否真的接进 CLI / 命令面板 / 打包链 / CI」，
    让「写了模块但没进产物」这类问题在 CI 里直接暴露。
"""
import ast
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="starry_v13_1_hub_")
os.environ["STARRY_DATA_DIR"] = os.path.join(_TMP, ".starry")

from core import hub as hb                          # noqa: E402
from core import config as cfg_mod                  # noqa: E402
from core import cli as cli_mod                     # noqa: E402
from core import updatecheck as uc                  # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def cli_run(argv):
    """参数未接入时 argparse 会 SystemExit；收敛成返回值，保证测试跑完整。"""
    buf = io.StringIO()
    try:
        rc = cli_mod.run_cli(argv, out=buf)
    except SystemExit as exc:
        rc = int(exc.code or 0)
    except Exception as exc:                      # noqa: BLE001
        buf.write("EXC: %r" % (exc,))
        rc = -1
    return rc, buf.getvalue()


CLAUDE_MD = read(os.path.join("skills", "claude-code-style", "SKILL.md"))
GITHUB_MD = read(os.path.join("skills", "github-copilot-style", "SKILL.md"))
FLAT_MD = read(os.path.join("skills", "flat-skill.skill.md"))


# ===========================================================================
# 1) frontmatter 解析：三种主流写法必须收敛到同一形态
# ===========================================================================
m1, b1 = hb.parse_frontmatter(CLAUDE_MD)
check("内联逗号 allowed-tools 归一化为列表",
      m1.get("allowed-tools") == ["Read", "Bash", "Grep"])
check("metadata 嵌套映射解析", m1.get("metadata") == {"version": "1.2.0"})
check("frontmatter 后正文保留", b1.startswith("# 发版前检查清单"))
check("description 单行解析",
      m1.get("description", "").startswith("发版前逐项核对版本真源"))

m2, b2 = hb.parse_frontmatter(GITHUB_MD)
check("YAML 列表续行 allowed-tools", m2.get("allowed-tools") == ["Read", "Grep"])
check("内联数组 tags", m2.get("tags") == ["api", "review", "docs"])
check("块标量 > 折叠为单行", "审查对外 API 契约" in str(m2.get("description")))
check("三段版本号保持字符串", m2.get("version") == "2.0.1")
check("普通标量 license", m2.get("license") == "MIT")
check("第二个正文保留", b2.startswith("# API 契约审查"))

m3, _ = hb.parse_frontmatter(FLAT_MD)
check("单值 allowed-tools 也归一化为列表", m3.get("allowed-tools") == ["Read"])

m0, b0 = hb.parse_frontmatter("# 没有 frontmatter\n\n正文\n")
check("无 frontmatter 返回空 meta 与原文", m0 == {} and b0.startswith("# 没有"))
m_bad, b_bad = hb.parse_frontmatter("---\nname: x\n")
check("未闭合 frontmatter 不吞正文", m_bad == {} and b_bad.startswith("---"))
check("_as_list 幂等", hb._as_list(["A", " B "]) == ["A", "B"])
check("_as_list 拒绝 dict", hb._as_list({"a": 1}) == [])


# ===========================================================================
# 2) 多格式解析 → 统一 Skill
# ===========================================================================
s1 = hb.parse_skill_md(CLAUDE_MD, "x/claude-code-style/SKILL.md", "claude-code")
check("Claude Code 技能 id 带源前缀", s1["id"] == "claude-code:release-checklist")
check("统一技能 tools 来自 allowed-tools", s1["tools"] == ["Read", "Bash", "Grep"])
check("统一技能 version 来自 metadata.version", s1["version"] == "1.2.0")
check("统一技能 source/format", s1["source"] == "claude-code"
      and s1["format"] == "skill-md")
check("统一技能 sha256 为 64 位", len(s1["sha256"]) == 64)
check("skill_digest 不含位置字段",
      hb.skill_digest(s1) == hb.skill_digest(dict(s1, path="另一处/SKILL.md")))
check("parse_skill_md 空文本返回 None", hb.parse_skill_md("") is None)

s2 = hb.parse_skill_md(GITHUB_MD, "x/github-copilot-style/SKILL.md", "github")
check("GitHub 技能 tags 归一化", s2["tags"] == ["api", "review", "docs"])
check("GitHub 技能 version", s2["version"] == "2.0.1")

s3 = hb.parse_skill_md(FLAT_MD, "x/flat-skill.skill.md", "github")
check("扁平 *.skill.md 以 frontmatter.name 为准",
      s3["id"] == "github:offline-workbench")
check("扁平技能 tools", s3["tools"] == ["Read"])

st = hb.parse_starry_skill({"id": "my-skill", "name": "我的技能",
                            "description": "说明", "prompt": "指令",
                            "icon": "✨"})
check("星语自有技能 id", st["id"] == "starry:my-skill")
check("星语自有技能 prompt 映射为 body", st["body"] == "指令")
check("星语自有技能 format", st["format"] == "starry-json")
check("parse_starry_skill 非 dict 返回 None", hb.parse_starry_skill("x") is None)
check("parse_starry_skill 缺 name/id 返回 None",
      hb.parse_starry_skill({"prompt": "x"}) is None)

conv = hb.to_starry_skill(s1)
check("to_starry_skill id 前缀 hub_", conv["id"].startswith("hub_"))
check("to_starry_skill prompt 来自 body", conv["prompt"] == s1["body"])
check("to_starry_skill 字段齐备",
      set(("id", "name", "description", "prompt", "icon")) <= set(conv))


# ===========================================================================
# 3) 真实 skills/ 目录与多源发现（全部落在临时目录，确定性）
# ===========================================================================
real = hb.scan_dir(os.path.join(ROOT, "skills"), "github")
check("仓库内置 skills/ 扫出 3 个技能", len(real) == 3)
check("仓库技能名称集合",
      {s["name"] for s in real} ==
      {"release-checklist", "api-contract-review", "offline-workbench"})

home = os.path.join(_TMP, "home")
root = os.path.join(_TMP, "root")
write(os.path.join(home, ".claude", "skills", "alpha", "SKILL.md"),
      "---\nname: alpha-skill\ndescription: 来自 Claude Code\n---\n\n# A\n")
write(os.path.join(home, ".workbuddy", "skills", "beta", "SKILL.md"),
      "---\nname: beta-skill\ndescription: 来自 WorkBuddy\n---\n\n# B\n")
write(os.path.join(root, ".github", "skills", "gamma", "SKILL.md"),
      "---\nname: gamma-skill\ndescription: 来自 GitHub\n---\n\n# C\n")
write(os.path.join(_TMP, "dup", "alpha", "SKILL.md"),
      "---\nname: alpha-skill\ndescription: 重复项\n---\n\n# A2\n")

sources = [
    ("claude-code", os.path.join(home, ".claude", "skills")),
    ("workbuddy", os.path.join(home, ".workbuddy", "skills")),
    ("github", os.path.join(root, ".github", "skills")),
    ("claude-code", os.path.join(_TMP, "dup")),
]
found = hb.scan_sources(sources, root, home)
check("多源发现 3 个技能（同 id 去重）", len(found) == 3)
check("先出现的源优先（重复项被丢弃）",
      next(s for s in found if s["id"] == "claude-code:alpha-skill")["body"]
      .startswith("# A\n"))
check("source 标记正确",
      {s["source"] for s in found} == {"claude-code", "workbuddy", "github"})

hub_obj = hb.Hub(root=root, home=home, sources=sources,
                 starry_skills=[{"id": "native", "name": "原生技能",
                                 "prompt": "指令"}])
allskills = hub_obj.discover()
check("Hub.discover 含星语自有技能", len(allskills) == 4)
check("Hub.search 命中描述", len(hub_obj.search("WorkBuddy")) == 1)
check("Hub.search 空查询返回全部", len(hub_obj.search("")) == 4)
check("Hub.search 多词 AND", len(hub_obj.search("来自 GitHub")) == 1)
check("Hub.get 按 id", hub_obj.get("github:gamma-skill") is not None)
check("Hub.get 按 name", hub_obj.get("beta-skill") is not None)
check("Hub.get 未命中返回 None", hub_obj.get("nope") is None)
check("Hub.as_starry 归一化", hub_obj.as_starry("beta-skill")["id"].startswith("hub_"))
check("Hub.add_source 拒绝不存在目录",
      hub_obj.add_source(os.path.join(_TMP, "missing")) is False)
check("Hub.add_starry 使缓存失效", (hub_obj.add_starry(
      {"id": "extra", "name": "新增", "prompt": "P"}) or True)
      and len(hub_obj.discover()) == 5)
check("Hub.catalog 输出表格", "| 来源 | 名称 | 说明 | 工具 |" in hub_obj.catalog())
check("Hub.catalog 含技能名", "gamma-skill" in hub_obj.catalog())
check("render_skill 含标题与正文", "# 技能 · " in hb.render_skill(s1)
      and "发版前检查清单" in hb.render_skill(s1))
check("render_catalog 转义竖线", hb.render_catalog(
      [dict(s1, description="a|b")]).count("\\|") >= 1)
check("default_sources 只列存在目录",
      all(os.path.isdir(p) for _, p in hb.default_sources(root, home)))


# ===========================================================================
# 4) hub.json 清单：生成 / 严格校验 / 防篡改
# ===========================================================================
man = hb.build_hub_manifest(found, hub_version="1.0.0", notes="首批",
                            repo_url="https://example.com/repo")
ok, reason = hb.validate_hub_manifest(man)
check("自建清单校验通过", ok, reason)
check("清单 magic / schema",
      man["magic"] == hb.HUB_MAGIC and man["schema"] == hb.HUB_SCHEMA)
check("清单条目数与技能数一致", len(man["skills"]) == 3)
check("清单条目带 source 字段", all("source" in x for x in man["skills"]))
check("hub_digest 不受 digest 字段影响",
      hb.hub_digest(man) == hb.hub_digest(dict(man, digest="wrong")))

tampered = dict(man, notes="被改过")
check("篡改 notes 被拒绝", not hb.validate_hub_manifest(tampered)[0])
check("篡改 digest 被拒绝",
      not hb.validate_hub_manifest(dict(man, digest="0" * 64))[0])
check("错误 magic 被拒绝",
      not hb.validate_hub_manifest(dict(man, magic="OTHER"))[0])
check("错误 schema 被拒绝",
      not hb.validate_hub_manifest(dict(man, schema=99))[0])
check("非 dict 根节点被拒绝", not hb.validate_hub_manifest([])[0])
check("skills 非列表被拒绝",
      not hb.validate_hub_manifest(dict(man, skills={}))[0])
bad_sha = json.loads(json.dumps(man))
bad_sha["skills"][0]["sha256"] = "abc"
bad_sha["digest"] = hb.hub_digest(bad_sha)
check("非法 sha256 长度被拒绝",
      not hb.validate_hub_manifest(bad_sha)[0])
bad_name = json.loads(json.dumps(man))
bad_name["skills"][0]["name"] = ""
bad_name["digest"] = hb.hub_digest(bad_name)
check("缺 name 条目被拒绝", not hb.validate_hub_manifest(bad_name)[0])

entry = hb.parse_hub_entry(man["skills"][0])
check("清单条目 id 与本地对齐（不加 remote: 前缀）",
      entry["id"] == man["skills"][0]["id"])
check("清单条目 source 保留", entry["source"] == man["skills"][0]["source"])
check("parse_hub_entry 拒绝无 name", hb.parse_hub_entry({"id": "x"}) is None)


# ===========================================================================
# 5) 更新判定：unchanged / changed / added / removed / 无效清单
# ===========================================================================
upd = hb.check_hub_update(found, man)
check("同版本清单判定为无更新", upd["manifest_valid"] and not upd["update_available"])
check("无更新时 added/changed/removed 均为空",
      not upd["added"] and not upd["changed"] and not upd["removed"])
check("无更新原因可读", "已是最新" in upd["reason"])
check("hub_version 回传", upd["hub_version"] == "1.0.0")

changed = json.loads(json.dumps(man))
changed["skills"][0]["sha256"] = "f" * 64
changed["skills"][0]["version"] = "9.9.9"
changed["digest"] = hb.hub_digest(changed)
upd2 = hb.check_hub_update(found, changed)
check("内容摘要变化判定为有更新", upd2["update_available"])
check("变化项归入 changed", len(upd2["changed"]) == 1)
check("变化项记录 local/remote", "local" in upd2["changed"][0]
      and "remote" in upd2["changed"][0])

added = json.loads(json.dumps(man))
added["skills"].append({
    "id": "github:brand-new", "name": "brand-new", "description": "新技能",
    "source": "github", "version": "1.0.0", "sha256": "a" * 64,
    "tools": [], "tags": [], "url": "",
})
added["digest"] = hb.hub_digest(added)
upd3 = hb.check_hub_update(found, added)
check("新技能归入 added", len(upd3["added"]) == 1
      and upd3["added"][0]["name"] == "brand-new")
check("仅新增时 removed 为空", not upd3["removed"])

removed = json.loads(json.dumps(man))
removed["skills"] = removed["skills"][:1]
removed["digest"] = hb.hub_digest(removed)
upd4 = hb.check_hub_update(found, removed)
check("缺失技能归入 removed", len(upd4["removed"]) == 2)

bad = hb.check_hub_update(found, dict(man, digest="0" * 64))
check("无效清单不报更新", not bad["update_available"] and not bad["manifest_valid"])
check("无效清单给出原因", bool(bad["reason"]))

d = hb.diff_skills(found, [hb.parse_hub_entry(x) for x in man["skills"]])
check("diff_skills 统计本地/远端数量",
      d["total_local"] == 3 and d["total_remote"] == 3)
check("diff_skills 键齐备",
      set(("added", "changed", "removed", "unchanged")) <= set(d))
check("空本地时全部为 added",
      len(hb.diff_skills([], [hb.parse_hub_entry(man["skills"][0])])["added"]) == 1)


# ===========================================================================
# 6) 接入门禁：功能必须真的进 CLI / GUI / 打包链 / CI
# ===========================================================================
core_init = read(os.path.join("core", "__init__.py"))
check("core/__init__.py 懒导出 hub",
      '"hub": "core.hub"' in core_init)
check("from core import hub 可用", hb.__name__ == "core.hub")

cli_src = read(os.path.join("core", "cli.py"))
for flag in ("--hub", "--hub-search", "--hub-info", "--hub-update",
             "--hub-manifest", "--hub-source", "--hub-import"):
    check("CLI 参数 %s 已接入" % flag, flag in cli_src)

rc, out = cli_run(["--hub"])
check("CLI --hub 返回 0", rc == 0)
check("CLI --hub 输出技能目录", "Skills Hub" in out or "技能" in out)
rc, out = cli_run(["--hub-search", "api"])
check("CLI --hub-search 返回 0", rc == 0)
check("CLI --hub-search 命中 api-contract-review", "api-contract-review" in out)
rc, out = cli_run(["--hub-info", "release-checklist"])
check("CLI --hub-info 返回 0", rc == 0)
check("CLI --hub-info 输出正文", "发版前检查清单" in out)
rc, out = cli_run(["--hub-manifest", os.path.join(_TMP, "missing.json")])
check("CLI --hub-manifest 缺文件时安全退出", rc != 0)

assistant_src = read(os.path.join("app", "assistant.py"))
check("命令面板有 hub 入口", '"hub"' in assistant_src)
check("命令面板有 hub_update 入口", '"hub_update"' in assistant_src)

for spec in ("starry_cli.spec", "starrystar.spec"):
    src = read(spec)
    check("%s 声明 core.hub" % spec, '"core.hub"' in src)
    check("%s 把 skills/ 打进产物" % spec, '("skills", "skills")' in src)
check("GUI spec 声明 ui.hub_dialog",
      '"ui.hub_dialog"' in read("starrystar.spec"))
check("GUI spec 声明 ui.workbench_dialog",
      '"ui.workbench_dialog"' in read("starrystar.spec"))
check("存在 scripts/smoke_gui_exe.py",
      os.path.isfile(os.path.join(ROOT, "scripts", "smoke_gui_exe.py")))
check("build-windows.yml 构建 GUI EXE",
      "starrystar.spec" in read(os.path.join(".github", "workflows",
                                             "build-windows.yml")))

mk_src = read(os.path.join("scripts", "make_release.py"))
check("发版快照白名单含 skills/", '"skills"' in mk_src)
check("发版脚本支持两位版本发布说明命名",
      "short_ver" in mk_src and "notes_candidates" in mk_src)
check("发版脚本发布说明有多级回退",
      mk_src.count("RELEASE_NOTES_v%s.md") >= 2)

check("存在 ui/hub_dialog.py",
      os.path.isfile(os.path.join(ROOT, "ui", "hub_dialog.py")))
main_src = read("main.py")
check("main.py 支持 --version", "--version" in main_src)
check("main.py 支持 --selftest", "--selftest" in main_src)

deb_src = read(os.path.join("scripts", "build_deb.py"))
check("deb 打包收集 skills/ 示例", "skills" in deb_src)

ci_src = read(os.path.join(".github", "workflows", "ci.yml"))
rel_src = read(os.path.join(".github", "workflows", "release.yml"))
check("CI 运行 Hub 单测", "test_v13_1_hub.py" in ci_src)
check("Release 运行 Hub 单测", "test_v13_1_hub.py" in rel_src)

# v13.2：不再把测试钉死在单一发版号（沿用 v13.0 P0-2 的去耦合做法）
_vtuple = tuple(int(x) for x in cfg_mod.APP_VERSION.split(".")[:3])
check("APP_VERSION 符合 SemVer 且不低于 13.1.0",
      len(cfg_mod.APP_VERSION.split(".")) == 3 and _vtuple >= (13, 1, 0))

# ---- 6b) 更新清单同平台多资产（v13.1 GUI EXE 引入的真实缺陷）----
spec = importlib.util.spec_from_file_location(
    "gum_v131", os.path.join(ROOT, "scripts", "gen_update_manifest.py"))
gum = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gum)

multi = os.path.join(_TMP, "multi_assets")
write(os.path.join(multi, "windows", "starry-cli.exe"), "cli")
write(os.path.join(multi, "windows", "starry-gui.exe"), "gui-bytes-longer")
write(os.path.join(multi, "windows", "starry-debug.exe"), "debug")
assets, skipped, base = gum.collect(multi, "13.1.0", "example/starry",
                                    "2026-11-09")
check("同平台两份正式 EXE 都收录", len(assets) == 2)
check("debug 包仍被排除", all("debug" not in a["name"] for a in assets))
check("资产按名称稳定排序",
      [a["name"] for a in assets] == ["starry-cli.exe", "starry-gui.exe"])
check("资产哈希来自真实字节",
      assets[0]["sha256"] == hashlib.sha256(b"cli").hexdigest())
check("更新检查列出同平台全部资产", "可更新资产（" in cli_src)

upd_rel = os.path.join("releases", "assets", "v13.1.0", "update.json")
if os.path.isfile(os.path.join(ROOT, upd_rel)):
    upd_man = json.loads(read(upd_rel))
    wins = [a for a in upd_man.get("assets", [])
            if a.get("platform") == "windows"]
    check("正式清单结构校验通过", uc.validate_manifest(upd_man)[0])
    check("正式清单含 windows 两份 EXE", len(wins) == 2)
    check("正式清单含 linux deb",
          any(a.get("platform") == "linux"
              for a in upd_man.get("assets", [])))
    check("正式清单不含 android 假资产",
          not any(a.get("platform") == "android"
                  for a in upd_man.get("assets", [])))
else:
    check("正式清单已生成", False)

# 全量 Python 源码语法检查（含新增模块）
py_ok, py_bad = 0, []
for base in ("core", "ui", "app", "scripts", "tests"):
    d = os.path.join(ROOT, base)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if fn.endswith(".py"):
            try:
                ast.parse(read(os.path.join(base, fn)))
                py_ok += 1
            except SyntaxError as exc:
                py_bad.append("%s/%s: %s" % (base, fn, exc))
check("新增模块后 Python 源码语法全通过", not py_bad, "; ".join(py_bad[:3]))


total = len(RESULTS)
passed = sum(1 for _, ok, _ in RESULTS if ok)
print("\n==== v13.1 Skills Hub 单测：%d/%d 通过 ====" % (passed, total))
for name, ok, extra in RESULTS:
    if not ok:
        print("  x", name, extra)
sys.exit(0 if passed == total else 1)
