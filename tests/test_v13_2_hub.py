# -*- coding: utf-8 -*-
"""星语 Starry v13.2 · DeepSeek 兼容 / 统一配置 / 异常边界单测。

运行：python tests/test_v13_2_hub.py   （退出码 0 = 全绿）

锁死三件事：
  1. DeepSeek 提示词模板（deepseek.json / *.deepseek.md / 配置内联 prompts）
     能被发现并归一化，且与 GitHub / Claude Code / WorkBuddy 原有能力共存；
  2. `config.json` 的 `hub` 段配置项清晰、归一化不抛异常、边界可预期；
  3. 扫描异常（目录不存在 / 文件损坏 / 单条缺字段）收敛为结构化 errors，
     不向调用方抛异常。

全部离线、确定性；不联网、不调用 DeepSeek API、不读写用户真实配置。
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_TMP = tempfile.mkdtemp(prefix="starry_v132_")
os.environ["STARRY_DATA_DIR"] = os.path.join(_TMP, ".starry")

from core import hub as hb                          # noqa: E402
from core import config as cfg_mod                  # noqa: E402
from core import cli as cli_mod                     # noqa: E402

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


def _write_array(path):
    write(path, json.dumps([{"name": "array-form", "prompt": "from array"}],
                           ensure_ascii=False))
    return path


# ===========================================================================
# 1) 兼容范围
# ===========================================================================
check("SOURCES 含 deepseek", "deepseek" in hb.SOURCES)
check("原有来源保持不变", all(
    s in hb.SOURCES for s in ("claude-code", "github", "workbuddy",
                              "starry", "local", "remote")))
check("FORMATS 含两种 DeepSeek 载体",
      "deepseek-json" in hb.FORMATS and "deepseek-md" in hb.FORMATS)
check("CONFIG_SOURCES 五个来源",
      set(hb.CONFIG_SOURCES) == {"claude-code", "github", "workbuddy",
                                 "deepseek", "starry"})
check("DeepSeek 载体常量齐备",
      "deepseek.json" in hb.DEEPSEEK_JSON_FILENAMES
      and hb.DEEPSEEK_MD_SUFFIX == ".deepseek.md")
check("随包 DeepSeek 示例存在",
      os.path.isfile(os.path.join(ROOT, "skills", "deepseek", "deepseek.json"))
      and os.path.isfile(os.path.join(ROOT, "skills", "deepseek",
                                      "code-review.deepseek.md")))
check("DeepSeek 来源有默认扫描目录",
      any(k == "deepseek" for k, _ in hb.default_sources()))

# ===========================================================================
# 2) DeepSeek 解析
# ===========================================================================
d = os.path.join(_TMP, "deepseek_src")
write(os.path.join(d, "deepseek.json"), json.dumps({
    "prompts": [
        {"name": "code-review", "description": "审查代码",
         "prompt": "你是资深工程师…", "model": "deepseek-chat",
         "temperature": 0.2, "tags": ["code"], "version": "1.0.0"},
        {"title": "release-notes", "desc": "整理发布说明",
         "content": "你是发版负责人…", "model": "deepseek-reasoner"},
        {"name": "broken-no-prompt"},
        "not-a-dict",
    ]}, ensure_ascii=False))
write(os.path.join(d, "sql.deepseek.md"),
      "---\nname: sql-review\ndescription: 审查 SQL\nversion: 1.1.0\n"
      "model: deepseek-chat\n---\n\n你是数据库专家…\n")
write(os.path.join(d, "broken-blank.deepseek.md"),
      "---\nname: blank\n---\n\n")

errors = []
found = hb.scan_dir(d, "deepseek", errors=errors)
names = {s["name"] for s in found}
check("deepseek.json + *.deepseek.md 共发现 3 个技能", len(found) == 3,
      str(sorted(names)))
check("字段别名 name/prompt 生效", "code-review" in names)
check("字段别名 title/desc/content 生效", "release-notes" in names)
check("*.deepseek.md 解析", "sql-review" in names)
check("DeepSeek 技能 source 统一为 deepseek",
      all(s["source"] == "deepseek" for s in found))
check("DeepSeek 格式标记正确",
      {s["name"]: s["format"] for s in found}.get("code-review") == "deepseek-json"
      and {s["name"]: s["format"] for s in found}.get("sql-review") == "deepseek-md")
check("DeepSeek 元数据保存但不发起请求",
      any((s.get("meta") or {}).get("model") == "deepseek-chat" for s in found))
check("缺 name/prompt 的条目被跳过", "broken-no-prompt" not in names)
check("非对象条目被跳过", all(isinstance(s, dict) for s in found))
check("异常被结构化记录", len(errors) >= 3
      and all(set(("path", "stage", "reason")) <= set(e) for e in errors))
check("异常记录含缺字段原因",
      any("缺 name 或 prompt" in e["reason"] for e in errors))

inline = hb.parse_deepseek_skill({"name": "inline-demo", "prompt": "hi"}, "")
check("内联 prompts 可解析", inline and inline["id"] == "deepseek:inline-demo")
check("非 dict 输入返回 None", hb.parse_deepseek_skill("x") is None)
check("空正文返回 None", hb.parse_deepseek_skill({"name": "x", "prompt": ""}) is None)
check("顶层数组也接受", len(hb.parse_deepseek_file(
    _write_array(os.path.join(_TMP, "arr.json")))) == 1)

# ===========================================================================
# 3) 与原有能力共存
# ===========================================================================
real = hb.scan_dir(os.path.join(ROOT, "skills"), "github")
check("原有 skills/ 仍扫出 3 个技能", len(real) == 3)
check("非 deepseek 源跳过 deepseek/ 子目录",
      all(s["source"] != "deepseek" for s in real))
check("原有 3 个示例名称不变",
      {s["name"] for s in real} == {"release-checklist",
                                     "api-contract-review",
                                     "offline-workbench"})
h = hb.Hub(root=_TMP, home=_TMP)      # 不扫用户真实 home，保证确定性
all_skills = h.discover()
check("Hub() 默认同时含 github 与 deepseek",
      {"github", "deepseek"} <= {s["source"] for s in all_skills})
check("Hub() 无重复 id", len(all_skills) == len({s["id"] for s in all_skills}))
check("v13.1 的 search 仍可用",
      any(s["name"] == "api-contract-review" for s in h.search("api")))
check("v13.1 的 get/render 仍可用",
      "## 指令正文" in hb.render_skill(h.get("release-checklist")))
check("v13.1 的 to_starry_skill 仍可用",
      hb.to_starry_skill(h.get("deepseek-code-review"))["id"].startswith("hub_"))
man = hb.build_hub_manifest(all_skills)
check("清单含 deepseek 条目",
      any(x["source"] == "deepseek" for x in man["skills"]))
check("往返一致性仍成立（无更新）",
      hb.check_hub_update(all_skills, man)["update_available"] is False)

# ===========================================================================
# 4) 配置项
# ===========================================================================
tpl = hb.config_template()
check("配置模板含全部键", set(tpl) == set(hb.DEFAULT_HUB_CONFIG))
tpl["deepseek"]["dirs"].append("x")
check("配置模板是深拷贝",
      hb.DEFAULT_HUB_CONFIG["deepseek"]["dirs"] == [])
cfg, warns = hb.normalize_hub_config(None)
check("空配置返回全部默认来源", cfg["sources"] == list(hb.CONFIG_SOURCES))
check("空配置无告警", warns == [])
cfg, warns = hb.normalize_hub_config("not-a-dict")
check("非对象根节点回退默认", cfg["sources"] == list(hb.CONFIG_SOURCES))
check("非对象根节点有告警", bool(warns))
cfg, warns = hb.normalize_hub_config(
    {"sources": "deepseek,github,unknown", "max_depth": 99,
     "enabled": "yes", "allow_import": 1})
check("逗号串 sources 可解析", cfg["sources"] == ["deepseek", "github"])
check("未知来源被过滤并告警", any("未知来源" in w for w in warns))
check("max_depth 越界回退 4", cfg["max_depth"] == 4)
check("布尔类型错误回退默认", cfg["enabled"] is True and cfg["allow_import"] is True)
check("类型错误逐项告警", len(warns) >= 4)
cfg, warns = hb.normalize_hub_config({"enabled": False, "sources": ["github"]})
check("enabled=False 关闭全部来源", cfg["sources"] == [])
cfg, warns = hb.normalize_hub_config(
    {"extra_dirs": [d, {"path": d, "source": "deepseek"}, 42]})
check("extra_dirs 字符串与对象都接受", len(cfg["extra_dirs"]) == 2)
check("extra_dirs 无效项被过滤并告警", any("无效项" in w for w in warns))
cfg, warns = hb.normalize_hub_config(
    {"deepseek": {"enabled": "x", "dirs": "oops",
                  "prompts": [{"name": "p", "prompt": "q"}, "bad"]}})
check("deepseek 子配置类型错误回退", cfg["deepseek"]["dirs"] == []
      and cfg["deepseek"]["enabled"] is True)
check("deepseek.prompts 非对象被过滤", len(cfg["deepseek"]["prompts"]) == 1)
check("config.hub.example.json 是合法配置",
      hb.hub_config(os.path.join(ROOT, "config.hub.example.json"))["enabled"])

# ===========================================================================
# 5) Hub.from_config / 异常边界
# ===========================================================================
h2 = hb.Hub.from_config({"sources": ["deepseek"],
                         "deepseek": {"prompts": [
                             {"name": "inline-only", "prompt": "hi"}]}},
                        root=_TMP, home=_TMP)
skills2 = h2.discover()
check("来源开关只留 deepseek",
      {s["source"] for s in skills2} == {"deepseek"})
check("内联 prompts 生效", any(s["name"] == "inline-only" for s in skills2))
h3 = hb.Hub.from_config({"enabled": False}, root=_TMP, home=_TMP)
check("enabled=False 时不扫描任何来源", h3.discover() == [])
h4 = hb.Hub(config={"sources": ["deepseek"],
                    "extra_dirs": [os.path.join(_TMP, "no-such-dir")]},
            root=_TMP, home=_TMP)
h4.discover()
check("不存在的额外目录只记告警不抛", any("不存在" in w for w in h4.warnings))
check("diagnostics 结构齐备", set(h4.diagnostics()) ==
      {"config", "sources", "warnings", "errors", "skills"})
check("allow_import 可通过 can_import 读取",
      hb.Hub(config={"allow_import": False}).can_import() is False)

bad_dir = os.path.join(_TMP, "broken")
os.makedirs(bad_dir, exist_ok=True)
write(os.path.join(bad_dir, "deepseek.json"), "{ this is not json")
errs = []
hb.scan_dir(bad_dir, "deepseek", errors=errs)
check("损坏 JSON 不抛异常", True)
check("损坏 JSON 被记录", any("解析失败" in e["reason"] for e in errs))
check("不存在目录被记录",
      hb.scan_dir(os.path.join(_TMP, "missing"), "local", errors=errs) == []
      and any("目录不存在" in e["reason"] for e in errs))
check("未提供 errors 时静默跳过（零破坏）",
      hb.scan_dir(bad_dir, "deepseek") == [])

# ===========================================================================
# 6) 接入门禁
# ===========================================================================
cli_src = read(os.path.join("core", "cli.py"))
for flag in ("--hub-config", "--hub-sources", "--hub-config-show",
             "--hub-diagnostics"):
    check("CLI 参数 %s 已接入" % flag, flag in cli_src)
ui_src = read(os.path.join("ui", "hub_dialog.py"))
check("GUI 显示生效配置按钮", "btn_config" in ui_src)
check("GUI 显示扫描诊断按钮", "btn_diag" in ui_src)
check("GUI 从 config 装配 Hub", "Hub.from_config" in ui_src)
check("两个 spec 都声明 core.hub",
      '"core.hub"' in read("starry_cli.spec")
      and '"core.hub"' in read("starrystar.spec"))
check("两个 spec 都打包 skills/",
      '("skills", "skills")' in read("starry_cli.spec")
      and '("skills", "skills")' in read("starrystar.spec"))
check("deb 收集 config.hub.example.json",
      "config.hub.example.json" in read(os.path.join("scripts", "build_deb.py")))
check("快照白名单含 config.hub.example.json",
      "config.hub.example.json" in read(os.path.join("scripts", "make_release.py")))
ci = read(os.path.join(".github", "workflows", "ci.yml"))
rel = read(os.path.join(".github", "workflows", "release.yml"))
check("CI 运行 v13.2 单测", "test_v13_2_hub.py" in ci)
check("Release 运行企业级单测", "test_enterprise_api.py" in rel)
# v13.4 起不再钉死单一发版号：每次更新都会升后代版本，只校验 SemVer 下限
_vtuple = tuple(int(x) for x in cfg_mod.APP_VERSION.split(".")[:3])
check("版本真源符合 SemVer 且不低于 13.2.0",
      len(cfg_mod.APP_VERSION.split(".")) == 3 and _vtuple >= (13, 2, 0),
      cfg_mod.APP_VERSION)

total = len(RESULTS)
passed = sum(1 for _, ok, _ in RESULTS if ok)
print("\n==== v13.2 DeepSeek / 配置边界单测：%d/%d 通过 ====" % (passed, total))
for name, ok, extra in RESULTS:
    if not ok:
        print("  x", name, extra)
sys.exit(0 if passed == total else 1)
