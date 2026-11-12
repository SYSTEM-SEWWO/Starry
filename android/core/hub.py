# -*- coding: utf-8 -*-
"""星语 Starry · Skills Hub（v13.1 新增，v13.2 扩展；纯逻辑 / 零依赖 / 三端同源）。

把主流「技能（Skill）」格式收敛到一份统一模型，让星语可以直接发现并使用
**GitHub、DeepSeek、Claude Code、WorkBuddy** 等来源已有的技能 / 提示词模板，
不需要用户改写或重新录入。

兼容矩阵（v13.2）
-----------------
==================  ======================  ========================================
来源                 载体                     默认扫描位置
==================  ======================  ========================================
Claude Code          SKILL.md + YAML         ~/.claude/skills/<name>/SKILL.md
                     frontmatter             <project>/.claude/skills/<name>/SKILL.md
GitHub / Copilot     SKILL.md（同规范）       .github/skills/<name>/SKILL.md
                                             <repo>/skills/<name>/SKILL.md
WorkBuddy            SKILL.md                ~/.workbuddy/skills/<name>/SKILL.md
                                             <project>/.workbuddy/skills/<name>/
DeepSeek             deepseek.json /         ~/.deepseek/skills/、~/.deepseek/prompts/
                     *.deepseek.md /         <project>/.deepseek/skills/
                     配置内联 prompts         <随包>/skills/deepseek/
星语自有             config.json 的 skills    AppConfig.data["skills"]
通用 Hub 清单        hub.json / skills.json   本地文件（只读取清单，不执行）
==================  ======================  ========================================

**关于 DeepSeek 的诚实界定**：DeepSeek 目前没有官方 Agent Skills / SKILL.md 规范，
本模块兼容的是 *DeepSeek 提示词模板 / 自定义指令*（JSON 清单、`*.deepseek.md`、
配置内联 `prompts`），把它们归一化成同一个 Skill 模型；不声称存在官方技能市场，
也**不调用 DeepSeek API、不联网**。`model` / `temperature` 等字段只作为元数据保存，
供上层决定是否使用，Hub 自身不发起任何模型请求。

设计约束
--------
* **只用标准库**：不引入 PyYAML，frontmatter 用手写极简解析器（覆盖 Skills
  规范实际用到的子集），因此 Windows EXE / Linux deb / Android 三端都能跑。
* **只读、不执行**：Hub 负责发现、解析、归一化、比对；技能正文只是提示词文本，
  不会被 eval / exec / 当作脚本运行。
* **不自动下载**：远程 hub.json 只用于「有没有新版本」的判定（复用
  core.updatecheck 的版本与完整性校验），安装永远由用户显式触发。
* **不修改入参**：所有函数返回新对象。
* **不抛异常给调用方**：扫描 / 配置归一化中的单点失败一律收敛成
  warnings（配置）与 errors（文件）记录，见 `normalize_hub_config()` 与
  `scan_dir(..., errors=...)`；只有「更新清单无效」「导入无正文」这类
  用户显式操作才返回结构化失败结论。
* **向后兼容**：v13.1 的全部公开函数签名与返回值保持不变；v13.2 新增能力一律
  通过可选关键字参数或新函数提供，原有调用方式零改动。
* **配置单一入口**：`config.json` 的 `hub` 段由 `normalize_hub_config()` 统一
  归一化，`Hub.from_config()` 是推荐的集成入口；CLI / GUI / 三端共用同一份配置。

安全边界：hub.json 的 digest 与技能 sha256 都是**完整性校验，不是签名认证**；
远程清单必须来自可信来源（HTTPS / GitHub Releases / 官方仓库）。
"""
import hashlib
import json
import os
import re

from core import updatecheck as _updatecheck

HUB_MAGIC = "STARRY-HUB"
HUB_SCHEMA = 1

# v13.2：新增 deepseek 来源。位置固定在元组中，保证已有 source 字符串不变。
SOURCES = ("claude-code", "github", "workbuddy", "deepseek",
           "starry", "local", "remote")
FORMATS = ("skill-md", "starry-json", "hub-json",
           "deepseek-json", "deepseek-md")

# 可由 config.json 的 hub.sources 开关的来源；local / remote 由显式参数控制。
CONFIG_SOURCES = ("claude-code", "github", "workbuddy", "deepseek", "starry")

SKILL_FILENAMES = ("SKILL.md", "skill.md")
MANIFEST_FILENAMES = ("hub.json", "skills.json")

# ---- v13.2 DeepSeek 载体 -------------------------------------------------
DEEPSEEK_JSON_FILENAMES = (
    "deepseek.json", "deepseek-skills.json", "deepseek-prompts.json")
DEEPSEEK_MD_SUFFIX = ".deepseek.md"
DEEPSEEK_DIR_NAMES = ("deepseek",)     # 非 deepseek 源跳过该子目录，避免重复
DEEPSEEK_NAME_KEYS = ("name", "title", "id", "label")
DEEPSEEK_BODY_KEYS = ("prompt", "content", "system_prompt", "text", "body")
DEEPSEEK_DESC_KEYS = ("description", "desc", "summary", "about")

# ---- v13.2 配置与边界 ---------------------------------------------------
HUB_CONFIG_KEY = "hub"
HUB_MAX_DEPTH_LIMIT = 8
ERROR_LIMIT = 200                       # 单次扫描最多记录的异常条数
DEFAULT_HUB_CONFIG = {
    "enabled": True,
    "sources": list(CONFIG_SOURCES),
    "extra_dirs": [],                   # ["path"] 或 [{"path":..., "source":"local"}]
    "max_depth": 4,
    "deepseek": {
        "enabled": True,
        "dirs": [],                     # 额外 DeepSeek 提示词目录
        "files": [],                    # 额外 deepseek.json 路径
        "prompts": [],                  # 直接内联的提示词模板（dict 列表）
        "model": "",                    # 仅元数据，Hub 不调用模型
    },
    "allow_import": True,               # 是否允许导入技能（false 时导入被拒绝）
    "remote_manifest": "",              # 留空 = 不联网；Hub 自身永不发起请求
}

__all__ = [
    "HUB_MAGIC", "HUB_SCHEMA", "SOURCES", "FORMATS", "CONFIG_SOURCES",
    "DEFAULT_HUB_CONFIG", "HUB_CONFIG_KEY",
    "parse_frontmatter", "parse_skill_md", "parse_starry_skill",
    "parse_hub_entry", "parse_deepseek_skill", "parse_deepseek_file",
    "parse_deepseek_md", "skill_digest", "hub_digest",
    "normalize_hub_config", "hub_config", "config_template",
    "bundled_skills_dir", "deepseek_default_dirs", "default_sources",
    "scan_dir", "scan_sources", "search", "to_starry_skill",
    "render_catalog", "render_skill",
    "build_hub_manifest", "validate_hub_manifest", "diff_skills",
    "check_hub_update", "Hub",
]

# Skills 规范里语义上属于「列表」的字段。各家写法不统一：
#   allowed-tools: Read, Bash        ← Claude Code 常见的内联逗号写法
#   allowed-tools:                   ← YAML 列表续行写法
#     - Read
#   tags: [api, docs]                ← 内联数组写法
# 统一在 parse_frontmatter 层面归一化，避免上层各处重复判断。
_LIST_KEYS = frozenset((
    "allowed-tools", "tools", "tags", "keywords", "categories", "triggers",
))


# ---------------------------------------------------------------------------
# 1) 极简 YAML frontmatter 解析（零依赖）
# ---------------------------------------------------------------------------
def _scalar(value):
    """把 YAML 标量转成 Python 值；只处理 Skills 规范实际用到的形态。"""
    v = str(value or "").strip()
    if not v:
        return ""
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.lower() in ("null", "~", "none"):
        return None
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_scalar(x) for x in inner.split(",") if x.strip()] if inner else []
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def _parse_simple_yaml(lines):
    """解析一层键值 + 列表续行 + 块标量（| / >）。不做通用 YAML。"""
    out = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][\w\-]*)\s*:\s*(.*)$", line.strip())
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in ("|", ">", "|-", ">-"):
            block, j = [], i + 1
            while j < len(lines) and (not lines[j].strip()
                                      or lines[j].startswith((" ", "\t"))):
                block.append(lines[j].strip())
                j += 1
            out[key] = ("\n" if val.startswith("|") else " ").join(
                x for x in block if x)
            i = j
            continue
        if val == "":
            # 支持两种续行：YAML 列表（- item）与一层嵌套映射（key: value），
            # 后者是 Claude Code 规范里 metadata: {version: ...} 的常见写法。
            items, sub, j = [], {}, i + 1
            while j < len(lines):
                raw2 = lines[j]
                s = raw2.strip()
                if s.startswith("- "):
                    items.append(_scalar(s[2:]))
                    j += 1
                elif (raw2[:1] in (" ", "\t") and ":" in s
                      and re.match(r"^[A-Za-z_][\w\-]*\s*:", s)):
                    k2, v2 = s.split(":", 1)
                    sub[k2.strip()] = _scalar(v2)
                    j += 1
                elif not s:
                    j += 1
                else:
                    break
            out[key] = items if items else (sub if sub else "")
            i = j
            continue
        out[key] = _scalar(val)
        i += 1
    for key in list(out):
        if key.replace("_", "-") in _LIST_KEYS:
            out[key] = _as_list(out[key])
    return out


def parse_frontmatter(text):
    """返回 (meta: dict, body: str)。没有 frontmatter 时 meta 为空、body 为原文。"""
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = s.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, s
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}, s
    meta = _parse_simple_yaml(lines[1:end])
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return meta, body


def _as_list(value):
    """把内联逗号串 / YAML 列表 / 单值统一成字符串列表（幂等）。"""
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value).split(",") if x.strip()]


def _slug(text, fallback="skill"):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", str(text or "").strip()).strip("-")
    return (s[:60] or fallback).lower()


def skill_digest(skill):
    """对技能**内容**做规范化 SHA-256（不含 path / source 等位置字段）。"""
    payload = {
        "name": (skill or {}).get("name", ""),
        "description": (skill or {}).get("description", ""),
        "body": (skill or {}).get("body", ""),
        "tools": (skill or {}).get("tools", []),
        "version": (skill or {}).get("version", ""),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _skill(skill_id, name, description, body, source, fmt, path="",
           tools=None, version="", tags=None, meta=None):
    s = {
        "id": str(skill_id),
        "name": str(name or skill_id),
        "description": str(description or ""),
        "body": str(body or ""),
        "source": source if source in SOURCES else "local",
        "format": fmt if fmt in FORMATS else "skill-md",
        "path": str(path or ""),
        "tools": _as_list(tools),
        "version": str(version or ""),
        "tags": _as_list(tags),
        "meta": dict(meta or {}),
    }
    s["sha256"] = skill_digest(s)
    return s


# ---------------------------------------------------------------------------
# 2) 各格式解析 → 统一 Skill
# ---------------------------------------------------------------------------
def parse_skill_md(text, path="", source="local", name=None, fmt=None):
    """解析 Claude Code / GitHub / WorkBuddy 的 SKILL.md。

    要求 frontmatter 至少有 name（或由目录名兜底）与 description；
    没有 frontmatter 但有正文时也接受，用文件名/目录名兜底。
    v13.2 新增可选 `fmt`（默认 "skill-md"），供 DeepSeek Markdown 复用同一解析器。
    """
    meta, body = parse_frontmatter(text)
    base = os.path.basename(os.path.dirname(os.path.abspath(path))) if path else ""
    # frontmatter 的 name 最权威；目录名 / 文件名只是无 frontmatter 时的兜底。
    # 早期版本把 name 参数放首位，会让扁平 *.skill.md 的文件名覆盖 SKILL.md
    # 里声明的名称，进而使同一技能在本地与清单里得到不同 id。
    guess = meta.get("name") or name or base or "skill"
    desc = meta.get("description") or ""
    if not str(body).strip() and not desc:
        return None
    sid = "%s:%s" % (source if source in SOURCES else "local", _slug(guess))
    version = meta.get("version") or ""
    metadata = meta.get("metadata")
    if not version and isinstance(metadata, dict):
        version = metadata.get("version") or ""
    return _skill(
        sid, guess, desc, body, source, fmt or "skill-md", path,
        tools=_as_list(meta.get("allowed-tools") or meta.get("allowed_tools")),
        version=str(version),
        tags=_as_list(meta.get("tags")),
        meta={k: v for k, v in meta.items()
              if k not in ("name", "description", "allowed-tools",
                           "allowed_tools", "tags", "version")})


def parse_starry_skill(obj, path="", source="starry"):
    """解析星语自有格式（cfg.data["skills"] 里的元素）。"""
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("id")
    if not name:
        return None
    sid = "%s:%s" % (source, _slug(obj.get("id") or name))
    return _skill(
        sid, name, obj.get("description") or "",
        obj.get("prompt") or obj.get("body") or "",
        source, "starry-json", path,
        tools=obj.get("tools"), version=obj.get("version") or "",
        tags=obj.get("tags"), meta={"icon": obj.get("icon", "🧩")})


def to_starry_skill(skill):
    """归一化为星语自有格式，可直接交给 SkillManager.add_custom()。"""
    s = skill or {}
    return {
        "id": "hub_%s" % _slug(s.get("id") or s.get("name")),
        "name": s.get("name") or "未命名技能",
        "description": s.get("description") or "",
        "prompt": s.get("body") or "",
        "icon": (s.get("meta") or {}).get("icon", "🧩"),
    }


# ---------------------------------------------------------------------------
# 2b) v13.2 DeepSeek 提示词模板 → 统一 Skill
# ---------------------------------------------------------------------------
def _record(errors, path, stage, reason):
    """把单点失败收敛为结构化记录；errors 为 None 时静默跳过（零破坏）。"""
    if isinstance(errors, list) and len(errors) < ERROR_LIMIT:
        errors.append({"path": str(path or ""), "stage": str(stage),
                       "reason": str(reason)})


def _first(obj, keys, default=""):
    for k in keys:
        v = obj.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def parse_deepseek_skill(obj, path="", source="deepseek"):
    """把一条 DeepSeek 提示词模板归一化成统一 Skill。

    字段别名（大小写不敏感由调用方保证，这里按常见写法逐一回退）：

    ============  ==================================================
    统一字段       接受的键
    ============  ==================================================
    name          name / title / id / label
    description   description / desc / summary / about
    body          prompt / content / system_prompt / text / body
    meta          model / model_name / temperature / top_p /
                  max_tokens / version / icon / url
    ============  ==================================================

    缺 name 或正文时返回 None（不抛异常，由调用方记录到 errors）。
    """
    if not isinstance(obj, dict):
        return None
    name = _first(obj, DEEPSEEK_NAME_KEYS)
    body = _first(obj, DEEPSEEK_BODY_KEYS)
    if not name or not str(body).strip():
        return None
    src = source if source in SOURCES else "deepseek"
    sid = "%s:%s" % (src, _slug(obj.get("id") or name))
    meta = {
        "provider": "deepseek",
        "model": str(obj.get("model") or obj.get("model_name") or ""),
    }
    for k in ("temperature", "top_p", "max_tokens",
              "version", "icon", "url"):
        if obj.get(k) not in (None, ""):
            meta[k] = obj[k]
    return _skill(
        sid, name, _first(obj, DEEPSEEK_DESC_KEYS, ""), body,
        src, "deepseek-json", path,
        tools=obj.get("tools"), version=obj.get("version") or "",
        tags=obj.get("tags") or obj.get("keywords"), meta=meta)


def parse_deepseek_file(path, source="deepseek", errors=None):
    """读取 DeepSeek JSON 清单，返回技能列表。

    接受三种顶层结构：数组、`{"prompts": [...]}`、`{"skills": [...]}`、
    `{"templates": [...]}`。任何读取 / 结构 / 单条错误都只记录不抛出。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError, UnicodeError) as exc:
        _record(errors, path, "deepseek-json", "读取/解析失败：%s" % exc)
        return []
    if isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict):
        items = (obj.get("prompts") or obj.get("skills")
                 or obj.get("templates") or [])
        if not isinstance(items, list):
            _record(errors, path, "deepseek-json",
                    "prompts/skills/templates 不是列表，已跳过")
            return []
    else:
        _record(errors, path, "deepseek-json", "根节点必须是数组或对象，已跳过")
        return []
    out = []
    for i, item in enumerate(items):
        s = parse_deepseek_skill(item, path, source)
        if s:
            out.append(s)
        else:
            _record(errors, "%s[%d]" % (path, i), "deepseek-json",
                    "缺 name 或 prompt / 非对象，已跳过该条")
    return out


def parse_deepseek_md(text, path=""):
    """解析 `*.deepseek.md`（复用 SKILL.md 的 frontmatter，正文即提示词）。"""
    s = parse_skill_md(text, path, "deepseek", fmt="deepseek-md")
    if s:
        # 只加元信息；skill_digest() 不含 meta，因此 sha256 不受影响。
        s.setdefault("meta", {})["provider"] = "deepseek"
    return s


# ---------------------------------------------------------------------------
# 2c) v13.2 统一配置（config.json 的 "hub" 段）
# ---------------------------------------------------------------------------
def config_template():
    """返回一份可直接写进 config.json 的 hub 配置模板（深拷贝，互不污染）。"""
    import copy
    return copy.deepcopy(DEFAULT_HUB_CONFIG)


def normalize_hub_config(raw=None, overrides=None):
    """归一化 hub 配置，返回 `(config, warnings)`；**任何输入都不抛异常**。

    边界约定：
      * 根节点非 dict            → 全量回退默认值 + warning
      * 单项类型错误             → 该项回退默认值 + warning（其它项保留）
      * 未知来源名               → 过滤掉 + warning
      * enabled=False            → sources 归一化为空（不扫描，但配置仍合法）
      * max_depth 非整数/越界    → 回退 4，范围 [0, 8]
      * extra_dirs / dirs / files 里的路径不要求存在（存在性由扫描阶段判定）
      * remote_manifest 只记录，不联网、不校验 URL
    """
    import copy
    cfg = copy.deepcopy(DEFAULT_HUB_CONFIG)
    warnings = []
    raw = raw if raw is not None else {}
    if not isinstance(raw, dict):
        warnings.append("hub 配置根节点不是对象，已回退全部默认值")
        raw = {}
    ov = overrides if isinstance(overrides, dict) else {}
    if overrides is not None and not isinstance(overrides, dict):
        warnings.append("hub 配置 overrides 不是对象，已忽略")

    def pick(key):
        return ov[key] if key in ov else raw.get(key, cfg[key])

    def warn(msg):
        warnings.append(msg)

    # enabled / allow_import：严格布尔，其它类型回退
    for key in ("enabled", "allow_import"):
        v = pick(key)
        if isinstance(v, bool):
            cfg[key] = v
        else:
            warn("%s 不是布尔值，回退为 %s" % (key, cfg[key]))

    # sources：接受列表 / 元组 / 逗号分隔字符串
    v = pick("sources")
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    if not isinstance(v, (list, tuple)):
        warn("sources 不是列表，回退为全部来源")
        v = list(CONFIG_SOURCES)
    allowed, unknown = [], []
    for item in v:
        s = str(item).strip().lower()
        if s in CONFIG_SOURCES:
            if s not in allowed:
                allowed.append(s)
        else:
            unknown.append(s)
    if unknown:
        warn("未知来源已忽略：%s" % ", ".join(sorted(set(unknown))))
    cfg["sources"] = allowed if cfg["enabled"] else []

    # max_depth：0..HUB_MAX_DEPTH_LIMIT 的整数
    v = pick("max_depth")
    if isinstance(v, int) and not isinstance(v, bool) \
            and 0 <= v <= HUB_MAX_DEPTH_LIMIT:
        cfg["max_depth"] = v
    else:
        warn("max_depth 非法（需 0~%d 的整数），回退 4" % HUB_MAX_DEPTH_LIMIT)
        cfg["max_depth"] = 4

    # extra_dirs：字符串或 {path, source}
    v = pick("extra_dirs")
    if not isinstance(v, (list, tuple)):
        warn("extra_dirs 不是列表，回退为空")
        v = []
    dirs = []
    for item in v:
        if isinstance(item, str) and item.strip():
            dirs.append({"path": item.strip(), "source": "local"})
        elif isinstance(item, dict) and str(item.get("path") or "").strip():
            src = str(item.get("source") or "local").lower()
            if src not in SOURCES:
                warn("extra_dirs 来源 %r 未知，按 local 处理" % src)
                src = "local"
            dirs.append({"path": str(item["path"]).strip(), "source": src})
        else:
            warn("extra_dirs 含无效项，已跳过：%r" % (item,))
    cfg["extra_dirs"] = dirs

    # deepseek 子配置
    d_raw = pick("deepseek")
    if not isinstance(d_raw, dict):
        warn("deepseek 配置不是对象，回退默认值")
        d_raw = {}
    d = copy.deepcopy(DEFAULT_HUB_CONFIG["deepseek"])
    if isinstance(d_raw.get("enabled"), bool):
        d["enabled"] = d_raw["enabled"]
    elif "enabled" in d_raw:
        warn("deepseek.enabled 不是布尔值，回退 True")
    for key in ("dirs", "files", "prompts"):
        val = d_raw.get(key, d[key])
        if not isinstance(val, (list, tuple)):
            warn("deepseek.%s 不是列表，回退为空" % key)
            val = []
        if key == "prompts":
            d[key] = [x for x in val if isinstance(x, dict)]
            if len(d[key]) != len(val):
                warn("deepseek.prompts 含非对象项，已跳过")
        else:
            d[key] = [str(x).strip() for x in val if str(x).strip()]
    model = d_raw.get("model", d["model"])
    d["model"] = str(model) if model is not None else ""
    cfg["deepseek"] = d

    rm = pick("remote_manifest")
    cfg["remote_manifest"] = str(rm) if isinstance(rm, str) else ""
    return cfg, warnings


def hub_config(cfg=None, overrides=None):
    """便捷入口：从 AppConfig / dict / JSON 路径读 hub 段并归一化，只返回 config。

    `cfg` 可以是 AppConfig 实例（读 `.data["hub"]`）、dict、或 JSON 文件路径。
    需要 warnings 时请直接调用 `normalize_hub_config()`。
    """
    raw = {}
    if isinstance(cfg, str):
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                obj = json.load(f)
            raw = obj.get(HUB_CONFIG_KEY, obj) if isinstance(obj, dict) else {}
        except (OSError, ValueError, UnicodeError):
            raw = {}
    elif hasattr(cfg, "data") and isinstance(getattr(cfg, "data"), dict):
        raw = cfg.data.get(HUB_CONFIG_KEY, {}) or {}
    elif isinstance(cfg, dict):
        raw = cfg.get(HUB_CONFIG_KEY, cfg) or {}
    return normalize_hub_config(raw, overrides)[0]


# ---------------------------------------------------------------------------
# 3) 多源发现
# ---------------------------------------------------------------------------
def bundled_skills_dir():
    """随程序分发的示例技能目录；源码运行与 PyInstaller onefile 都指向同一处。"""
    import sys
    base = (getattr(sys, "_MEIPASS", None)
            or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "skills")


def deepseek_default_dirs(root=None, home=None):
    """v13.2：DeepSeek 提示词模板候选目录（只返回真实存在的目录）。"""
    root = os.path.abspath(root or os.getcwd())
    home = os.path.abspath(home or os.path.expanduser("~"))
    cands = [
        os.path.join(bundled_skills_dir(), "deepseek"),   # 随包示例
        os.path.join(home, ".deepseek", "skills"),
        os.path.join(home, ".deepseek", "prompts"),
        os.path.join(root, ".deepseek", "skills"),
    ]
    seen, out = set(), []
    for p in cands:
        key = os.path.normcase(os.path.abspath(p))
        if os.path.isdir(p) and key not in seen:
            seen.add(key)
            out.append(os.path.abspath(p))
    return out


def default_sources(root=None, home=None):
    """返回 [(source_kind, absolute_dir), ...]，只列存在的目录。"""
    root = os.path.abspath(root or os.getcwd())
    home = os.path.abspath(home or os.path.expanduser("~"))
    candidates = [
        # v13.1：随包示例（EXE / deb 里也要能开箱看到技能）
        ("github", bundled_skills_dir()),
        ("claude-code", os.path.join(home, ".claude", "skills")),
        ("claude-code", os.path.join(root, ".claude", "skills")),
        ("github", os.path.join(root, ".github", "skills")),
        ("github", os.path.join(root, "skills")),
        ("workbuddy", os.path.join(home, ".workbuddy", "skills")),
        ("workbuddy", os.path.join(root, ".workbuddy", "skills")),
    ]
    # v13.2：DeepSeek 提示词模板目录。随包 skills/deepseek/ 单独成为一个源，
    # 且 scan_dir 会让其它源跳过 deepseek 子目录，避免同一文件被解析两次。
    candidates += [("deepseek", p)
                   for p in deepseek_default_dirs(root, home)]
    seen, out = set(), []
    for kind, path in candidates:
        key = os.path.normcase(os.path.abspath(path))
        if os.path.isdir(path) and key not in seen:
            seen.add(key)
            out.append((kind, os.path.abspath(path)))
    return out


def scan_dir(directory, source="local", max_depth=4, errors=None):
    """递归扫描目录下的技能载体；返回统一 Skill 列表。

    - `SKILL.md` / `skill.md` / `*.skill.md`：Claude Code / GitHub / WorkBuddy；
    - `hub.json` / `skills.json`：通用清单（只读取，不执行其中内容）；
    - **v13.2** `deepseek*.json` / `*.deepseek.md`：DeepSeek 提示词模板，
      命中时强制标记 `source="deepseek"`，与传入的 source 无关。

    异常边界：目录不存在 / 读取失败 / 编码错误 / JSON 损坏 / 单条缺字段
    一律跳过并写入 `errors`（若提供），**不向调用方抛异常**。
    `errors` 是可选的 list，元素为 `{"path","stage","reason"}`，
    最多记录 `ERROR_LIMIT` 条，防止异常目录把内存撑爆。
    """
    out = []
    directory = os.path.abspath(directory or "")
    if not os.path.isdir(directory):
        _record(errors, directory, "scan", "目录不存在，已跳过")
        return out
    base_depth = directory.rstrip(os.sep).count(os.sep)
    for base, dirs, files in os.walk(directory):
        # 随包 skills/ 下有 deepseek/ 子目录；非 deepseek 源跳过它，
        # 避免同一份提示词被两个来源各解析一次产生重复 id。
        keep = [d for d in dirs
                if d not in ("__pycache__", ".git", "node_modules")]
        if source != "deepseek":
            keep = [d for d in keep if d.lower() not in DEEPSEEK_DIR_NAMES]
        dirs[:] = keep
        if base.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        for fn in files:
            full = os.path.join(base, fn)
            low = fn.lower()

            # ---- v13.2 DeepSeek 载体（优先判定）----
            if low in DEEPSEEK_JSON_FILENAMES:
                out.extend(parse_deepseek_file(full, "deepseek", errors))
                continue
            if low.endswith(DEEPSEEK_MD_SUFFIX):
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        skill = parse_deepseek_md(f.read(), full)
                    if skill:
                        out.append(skill)
                    else:
                        _record(errors, full, "deepseek-md", "正文为空，已跳过")
                except (OSError, UnicodeError) as exc:
                    _record(errors, full, "deepseek-md", "读取失败：%s" % exc)
                continue

            # ---- 原有载体（行为保持不变，仅补错误记录）----
            if fn in SKILL_FILENAMES:
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        skill = parse_skill_md(f.read(), full, source)
                    if skill:
                        out.append(skill)
                except (OSError, UnicodeError) as exc:
                    _record(errors, full, "skill-md", "读取失败：%s" % exc)
            elif low.endswith(".skill.md") and fn not in SKILL_FILENAMES:
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        skill = parse_skill_md(
                            f.read(), full, source,
                            name=os.path.splitext(os.path.splitext(fn)[0])[0])
                    if skill:
                        out.append(skill)
                except (OSError, UnicodeError) as exc:
                    _record(errors, full, "skill-md", "读取失败：%s" % exc)
            elif fn in MANIFEST_FILENAMES:
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        obj = json.load(f)
                    ok, reason = validate_hub_manifest(obj)
                    if ok:
                        for item in obj.get("skills", []):
                            s = parse_hub_entry(item, path=full)
                            if s:
                                out.append(s)
                    else:
                        _record(errors, full, "hub-json", "清单校验失败：%s" % reason)
                except (OSError, ValueError, UnicodeError) as exc:
                    _record(errors, full, "hub-json", "读取失败：%s" % exc)
    return out


def parse_hub_entry(item, path="", source=None):
    """把 hub.json 里的条目转成统一 Skill（正文可内嵌或留空）。

    id 必须与本地扫描结果保持同源，否则 diff_skills() 会把每个技能同时
    判成 added 和 removed。清单条目若已带完整 id（`source:slug`）则原样使用；
    否则用条目声明的 source（再退回参数 / remote）拼装。
    """
    if not isinstance(item, dict) or not item.get("name"):
        return None
    src = item.get("source") or source or "remote"
    if src not in SOURCES:
        src = "remote"
    sid = str(item.get("id") or "")
    if ":" not in sid:
        sid = "%s:%s" % (src, _slug(sid or item.get("name")))
    return _skill(
        sid, item.get("name"), item.get("description") or "",
        item.get("body") or item.get("prompt") or "",
        src, "hub-json", path,
        tools=item.get("tools"), version=item.get("version") or "",
        tags=item.get("tags"),
        meta={"url": item.get("url", ""), "sha256": item.get("sha256", "")})


def scan_sources(sources=None, root=None, home=None, extra_starry=None,
                 max_depth=4, errors=None, extra_skills=None):
    """汇总所有来源，按 id 去重（先出现的源优先），返回排序后的列表。

    v13.2 新增可选参数（均带默认值，旧调用零改动）：
      `max_depth` 透传给 scan_dir；`errors` 收集扫描异常；
      `extra_skills` 合入已解析的技能（配置内联的 DeepSeek prompts / files）。
    """
    pairs = list(sources) if sources is not None else default_sources(root, home)
    found, seen = [], set()

    def add(s):
        if isinstance(s, dict) and s.get("id") and s["id"] not in seen:
            seen.add(s["id"])
            found.append(s)

    for kind, path in pairs:
        for s in scan_dir(path, kind, max_depth=max_depth, errors=errors):
            add(s)
    for obj in (extra_starry or []):
        add(parse_starry_skill(obj))
    for s in (extra_skills or []):
        add(s)
    return sorted(found, key=lambda s: (s["source"], s["name"].lower()))


def search(skills, query):
    """按名称 / 描述 / 标签 / 正文做大小写不敏感匹配；空查询返回全部。"""
    q = str(query or "").strip().lower()
    if not q:
        return list(skills or [])
    terms = [t for t in re.split(r"\s+", q) if t]
    out = []
    for s in skills or []:
        hay = " ".join([s.get("name", ""), s.get("description", ""),
                        " ".join(s.get("tags") or []), s.get("body", ""),
                        s.get("source", "")]).lower()
        if all(t in hay for t in terms):
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# 4) Hub 清单与更新判定
# ---------------------------------------------------------------------------
def hub_digest(manifest):
    obj = {k: v for k, v in (manifest or {}).items() if k != "digest"}
    canonical = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_hub_manifest(skills, hub_version="1.0.0", notes="", repo_url=""):
    """从本地技能生成可分发的 hub.json（条目只带元数据 + 内容摘要）。"""
    entries = []
    for s in skills or []:
        entries.append({
            "id": s.get("id"), "name": s.get("name"),
            "description": s.get("description"),
            "version": s.get("version") or "",
            "source": s.get("source"),
            "sha256": s.get("sha256"),
            "tools": s.get("tools", []),
            "tags": s.get("tags", []),
            "url": (s.get("meta") or {}).get("url", ""),
        })
    obj = {
        "magic": HUB_MAGIC, "schema": HUB_SCHEMA,
        "hub_version": str(hub_version or "1.0.0"),
        "skills": entries, "notes": str(notes or ""),
        "repo_url": str(repo_url or ""),
    }
    obj["digest"] = hub_digest(obj)
    return obj


def validate_hub_manifest(obj):
    """返回 (ok, reason)。结构与 digest 严格校验；正文可为空（清单只带元数据）。"""
    if not isinstance(obj, dict):
        return False, "Hub 清单根节点必须是对象"
    if obj.get("magic") != HUB_MAGIC:
        return False, "不是 Starry Hub 清单（magic 不匹配）"
    if obj.get("schema") != HUB_SCHEMA:
        return False, "不支持的 Hub 清单格式版本：%r" % (obj.get("schema"),)
    if obj.get("digest") != hub_digest(obj):
        return False, "Hub 清单校验失败（内容被修改或传输损坏）"
    skills = obj.get("skills")
    if not isinstance(skills, list):
        return False, "skills 必须是列表"
    for i, s in enumerate(skills):
        if not isinstance(s, dict) or not str(s.get("name") or "").strip():
            return False, "skills[%d].name 缺失" % i
        sha = str(s.get("sha256") or "")
        if sha and not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            return False, "skills[%d].sha256 必须是 64 位十六进制" % i
    return True, "OK"


def diff_skills(local, remote):
    """比对本地技能与远程清单，返回 added / changed / removed / unchanged。

    判定优先用 sha256（内容摘要），其次用 version（复用 SemVer 比较）。
    """
    lmap = {s["id"]: s for s in (local or [])}
    rmap = {s["id"]: s for s in (remote or [])}
    added = [rmap[k] for k in sorted(rmap) if k not in lmap]
    removed = [lmap[k] for k in sorted(lmap) if k not in rmap]
    changed, unchanged = [], []
    for k in sorted(set(lmap) & set(rmap)):
        a, b = lmap[k], rmap[k]
        la, rb = a.get("sha256"), b.get("sha256")
        if la and rb:
            same = la == rb
        else:
            va, vb = a.get("version") or "0", b.get("version") or "0"
            same = _updatecheck.compare_versions(vb, va) <= 0
        (unchanged if same else changed).append(
            {"id": k, "name": b.get("name", k),
             "local": a.get("sha256") or a.get("version") or "",
             "remote": rb or b.get("version") or ""})
    return {"added": added, "changed": changed,
            "removed": removed, "unchanged": unchanged,
            "total_local": len(lmap), "total_remote": len(rmap)}


def check_hub_update(local, manifest):
    """纯逻辑更新判定，返回结构化结论（不联网、不抛异常）。"""
    res = {
        "manifest_valid": False, "hub_version": "",
        "update_available": False, "added": [], "changed": [],
        "removed": [], "reason": "",
    }
    ok, reason = validate_hub_manifest(manifest)
    if not ok:
        res["reason"] = reason
        return res
    res["manifest_valid"] = True
    res["hub_version"] = str(manifest.get("hub_version") or "")
    remote = []
    for item in manifest.get("skills", []):
        s = parse_hub_entry(item)
        if not s:
            continue
        # 清单只带元数据、正文为空，_skill() 重算的摘要必然与本地不同。
        # 比对必须以清单**声明**的内容摘要为准，否则每个技能都会被误判为变更。
        declared = str(item.get("sha256") or "")
        if declared:
            s["sha256"] = declared
        remote.append(s)
    d = diff_skills(local, remote)
    res["added"] = d["added"]
    res["changed"] = d["changed"]
    res["removed"] = d["removed"]
    res["update_available"] = bool(d["added"] or d["changed"] or d["removed"])
    res["reason"] = ("技能有更新：新增 %d / 变更 %d / 移除 %d"
                     % (len(d["added"]), len(d["changed"]), len(d["removed"]))
                     if res["update_available"] else "本地技能已是最新")
    return res


# ---------------------------------------------------------------------------
# 5) 渲染
# ---------------------------------------------------------------------------
def render_catalog(skills, title="Skills Hub"):
    lines = ["## %s" % title, "",
             "共 %d 个技能 · 来源：%s"
             % (len(skills or []),
                ", ".join(sorted({s.get("source", "") for s in skills or []})) or "无"),
             "", "| 来源 | 名称 | 说明 | 工具 |", "| --- | --- | --- | --- |"]
    for s in skills or []:
        desc = str(s.get("description") or "").replace("|", "\\|")[:90]
        lines.append("| `%s` | **%s** | %s | %s |" % (
            s.get("source", ""), s.get("name", ""), desc,
            ", ".join(s.get("tools") or []) or "—"))
    return "\n".join(lines) + "\n"


def render_skill(skill):
    s = skill or {}
    lines = ["# 技能 · %s" % s.get("name", ""), "",
             "- 来源：`%s` · 格式：`%s`" % (s.get("source"), s.get("format")),
             "- 版本：%s" % (s.get("version") or "未标注"),
             "- 摘要：`%s`" % str(s.get("sha256") or "")[:16],
             "- 文件：`%s`" % (s.get("path") or "（远程清单）"),
             "", "## 说明", "", s.get("description") or "（无）", ""]
    if s.get("tools"):
        lines += ["## 可用工具", "", ", ".join(s["tools"]), ""]
    meta = s.get("meta") or {}
    if meta.get("provider") == "deepseek":
        lines += ["## DeepSeek 提示词元数据", "",
                  "- 建议模型：`%s`" % (meta.get("model") or "未指定（由上层决定）")]
        for key in ("temperature", "top_p", "max_tokens"):
            if meta.get(key) not in (None, ""):
                lines.append("- %s：`%s`" % (key, meta[key]))
        lines += ["- 说明：Hub 只保存元数据，**不调用 DeepSeek API、不联网**。", ""]
    lines += ["## 指令正文", "", s.get("body") or "（清单只含元数据，正文需从来源获取）", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6) 门面
# ---------------------------------------------------------------------------
class Hub:
    """技能中心门面：注册源 → 发现 → 搜索 → 归一化 → 更新判定。

    三种构造方式（v13.1 的第一种行为完全不变）：

    1. `Hub()` / `Hub(sources=[...])`：默认全来源扫描，无条件并入星语自有技能；
    2. `Hub(config=...)`：按 `config.json` 的 `hub` 段开关来源与 DeepSeek 配置；
    3. `Hub.from_config(cfg_or_dict_or_json_path)`：**推荐集成入口**。

    诊断信息统一放在 `hub.warnings`（配置问题）与 `hub.errors`（扫描问题），
    或调用 `hub.diagnostics()` 一次取全。任何单点失败都不会让 discover() 抛异常。
    """

    def __init__(self, root=None, home=None, sources=None, starry_skills=None,
                 config=None):
        self.root = root or os.getcwd()
        self.home = home or os.path.expanduser("~")
        self.config, self.warnings = normalize_hub_config(config)
        self._configured = config is not None
        self._explicit_sources = sources is not None
        self._starry = list(starry_skills or [])
        self._inline = []                 # 配置内联的 DeepSeek prompts / files
        self._preset_errors = []
        self.errors = []
        self._skills = None
        if self._explicit_sources:
            self._sources = list(sources)
        elif self._configured:
            self._sources = self._sources_from_config()
        else:
            self._sources = default_sources(self.root, self.home)

    # ------------------------------------------------------------------
    # v13.2 配置装配
    # ------------------------------------------------------------------
    def _sources_from_config(self):
        c = self.config
        if not c["enabled"]:
            return []
        enabled = set(c["sources"])
        pairs = [(k, p) for (k, p) in default_sources(self.root, self.home)
                 if k in enabled]
        for item in c["extra_dirs"]:
            if os.path.isdir(item["path"]):
                pairs.append((item["source"], os.path.abspath(item["path"])))
            else:
                self.warnings.append("extra_dirs 目录不存在：%s" % item["path"])
        d = c["deepseek"]
        if d["enabled"] and "deepseek" in enabled:
            for p in d["dirs"]:
                if os.path.isdir(p):
                    pairs.append(("deepseek", os.path.abspath(p)))
                else:
                    self.warnings.append("deepseek.dirs 目录不存在：%s" % p)
            for f in d["files"]:
                for s in parse_deepseek_file(f, "deepseek", self._preset_errors):
                    self._inline.append(s)
            for obj in d["prompts"]:
                s = parse_deepseek_skill(obj, "", "deepseek")
                if s:
                    self._inline.append(s)
                else:
                    _record(self._preset_errors, "hub.deepseek.prompts",
                            "deepseek-json", "缺 name 或 prompt，已跳过该条")
        return pairs

    @classmethod
    def from_config(cls, config, root=None, home=None, starry_skills=None):
        """从 AppConfig / dict / JSON 路径构造 Hub（推荐的集成入口）。"""
        if isinstance(config, str) or hasattr(config, "data"):
            config = hub_config(config)
        return cls(root=root, home=home, starry_skills=starry_skills,
                   config=config)

    def can_import(self):
        """配置是否允许导入技能（hub.allow_import）。"""
        return bool(self.config["allow_import"])

    def diagnostics(self):
        """返回结构化诊断：配置 / 生效来源 / 警告 / 扫描异常 / 技能数。"""
        import copy
        return {
            "config": copy.deepcopy(self.config),
            "sources": [{"source": k, "path": p} for k, p in self._sources],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "skills": len(self.discover()),
        }

    # ------------------------------------------------------------------
    # 原有 API（签名与行为保持不变）
    # ------------------------------------------------------------------
    def add_source(self, path, source="local"):
        path = os.path.abspath(path)
        if os.path.isdir(path):
            self._sources.append((source, path))
            self._skills = None
            return True
        return False

    def add_starry(self, obj):
        self._starry.append(obj)
        self._skills = None

    def discover(self, refresh=False):
        if self._skills is None or refresh:
            starry = self._starry
            if self._configured and "starry" not in self.config["sources"]:
                starry = []
            errors = list(self._preset_errors)
            self._skills = scan_sources(
                self._sources, self.root, self.home, starry,
                max_depth=(self.config["max_depth"] if self._configured else 4),
                errors=errors, extra_skills=self._inline)
            self.errors = errors
        return list(self._skills)

    def all(self, refresh=False):
        return self.discover(refresh)

    def search(self, query):
        return search(self.discover(), query)

    def get(self, skill_id):
        for s in self.discover():
            if s["id"] == skill_id or s["name"] == skill_id:
                return s
        return None

    def as_starry(self, skill_id):
        s = self.get(skill_id)
        return to_starry_skill(s) if s else None

    def catalog(self, title="Skills Hub"):
        return render_catalog(self.discover(), title)

    def check_update(self, manifest):
        return check_hub_update(self.discover(), manifest)
