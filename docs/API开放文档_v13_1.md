# API 开放文档 · 星语 Starry v13.1.0

> 本文公开 v13.1 新增的 **Skills Hub** 全部对外接口。v12.0（`core.stardust`）与
> v13.0（`core.project` / `core.parallel` / `core.updatecheck`）接口保持不变，
> 见 `docs/API开放文档_v13_0.md`。所有接口均为**纯标准库、零第三方依赖**，
> 因此在 Windows EXE / Linux deb / Android 三端同一份代码可直接调用。

## 1. 模块 `core.hub`

```python
from core import hub as hb          # 也可 from core import hub（懒导出）
```

### 1.1 常量

| 常量 | 值 | 说明 |
| --- | --- | --- |
| `HUB_MAGIC` | `"STARRY-HUB"` | `hub.json` 根字段，用于识别清单 |
| `HUB_SCHEMA` | `1` | 清单格式版本 |
| `SOURCES` | `claude-code / github / workbuddy / starry / local / remote` | 合法来源标识 |
| `FORMATS` | `skill-md / starry-json / hub-json` | 统一技能的原始格式 |
| `SKILL_FILENAMES` | `("SKILL.md", "skill.md")` | 目录式技能载体 |
| `MANIFEST_FILENAMES` | `("hub.json", "skills.json")` | 目录内技能清单 |

### 1.2 统一 Skill 模型

所有解析器返回结构一致的 `dict`：

```python
{
  "id": "github:api-contract-review",   # "<source>:<slug>"，去重与比对的主键
  "name": "api-contract-review",
  "description": "审查对外 API 契约…",
  "body": "# API 契约审查\n…",          # 技能正文（提示词原文）
  "source": "github",
  "format": "skill-md",
  "path": "/abs/path/SKILL.md",         # 远程清单条目为空串
  "tools": ["Read", "Grep"],            # 恒为字符串列表
  "version": "2.0.1",                  # 三段版本号保持字符串
  "tags": ["api", "review", "docs"],
  "meta": {"license": "MIT", ...},     # 未消费的 frontmatter 字段
  "sha256": "<64 hex>",                # 对 name/description/body/tools/version 规范化摘要
}
```

`sha256` **不含** `path` / `source` 等位置字段，因此同一技能换台机器、换目录仍得到相同摘要。

### 1.3 解析接口

| 函数 | 签名 | 返回 / 行为 |
| --- | --- | --- |
| `parse_frontmatter` | `(text) -> (meta, body)` | 手写极简 YAML；`allowed-tools` / `tools` / `tags` / `keywords` / `categories` / `triggers` 自动归一化为列表；支持 `\|`、`>` 块标量、列表续行、一层嵌套映射、内联数组 |
| `parse_skill_md` | `(text, path="", source="local", name=None) -> dict\|None` | Claude Code / GitHub / WorkBuddy 的 `SKILL.md`；**frontmatter 的 `name` 优先**于目录名与文件名 |
| `parse_starry_skill` | `(obj, path="", source="starry") -> dict\|None` | 星语自有 `{"id","name","description","prompt","icon"}`；`prompt` 映射为 `body` |
| `parse_hub_entry` | `(item, path="", source=None) -> dict\|None` | `hub.json` 条目；条目已带 `id` 时原样沿用，保证与本地 id 对齐 |
| `to_starry_skill` | `(skill) -> dict` | 转为 `{"id": "hub_<slug>", "name", "description", "prompt", "icon"}`，可直接交给 `SkillManager.add_custom()` |
| `skill_digest` | `(skill) -> str` | 规范化 SHA-256 |
| `hub_digest` | `(manifest) -> str` | 清单（除去 `digest` 字段）规范化 SHA-256 |
| `render_catalog` | `(skills, title="Skills Hub") -> str` | Markdown 表格，竖线自动转义 |
| `render_skill` | `(skill) -> str` | Markdown 详情（说明 / 工具 / 指令正文） |

### 1.4 发现接口

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `bundled_skills_dir` | `() -> str` | 随包 `skills/` 目录；源码运行取项目根，PyInstaller onefile 取 `sys._MEIPASS` |
| `default_sources` | `(root=None, home=None) -> [(source, dir), ...]` | 只返回**存在**的目录：随包 `skills/`、`~/.claude/skills`、`<project>/.claude/skills`、`.github/skills`、`<repo>/skills`、`~/.workbuddy/skills`、`<project>/.workbuddy/skills` |
| `scan_dir` | `(directory, source="local", max_depth=4) -> [skill]` | 递归 `SKILL.md` / `skill.md` / `*.skill.md` / `hub.json`；跳过 `__pycache__` `.git` `node_modules` |
| `scan_sources` | `(sources=None, root=None, home=None, extra_starry=None) -> [skill]` | 汇总并按 `id` 去重（先出现的源优先），按 `(source, name)` 排序 |
| `search` | `(skills, query) -> [skill]` | 名称 / 描述 / 标签 / 正文 / 来源，空格分词 AND，大小写不敏感；空查询返回全部 |

类 `Hub`：

```python
h = hb.Hub(root=None, home=None, sources=None, starry_skills=None)
h.add_source(path, source="local")   # -> bool，目录不存在返回 False
h.add_starry(obj)                    # 追加星语自有技能
h.discover(refresh=False)            # -> [skill]，带缓存
h.all(refresh=False)                 # 同 discover
h.search(query)                      # -> [skill]
h.get(skill_id)                      # 按 id 或 name，未命中 None
h.as_starry(skill_id)                # -> 星语格式 dict / None
h.catalog(title="Skills Hub")        # -> Markdown
h.check_update(manifest)             # -> 更新判定 dict
```

### 1.5 清单与更新判定

```python
manifest = hb.build_hub_manifest(
    skills, hub_version="1.3.0", notes="首批", repo_url="https://…")
ok, reason = hb.validate_hub_manifest(manifest)   # (bool, str)
res = hb.check_hub_update(local_skills, manifest)
```

`hub.json` 结构：

```json
{
  "magic": "STARRY-HUB", "schema": 1,
  "hub_version": "1.3.0", "notes": "", "repo_url": "",
  "skills": [
    {"id": "github:release-checklist", "name": "release-checklist",
     "description": "…", "version": "1.2.0", "source": "github",
     "sha256": "<64 hex>", "tools": ["Read","Bash","Grep"],
     "tags": [], "url": ""}
  ],
  "digest": "<64 hex>"
}
```

`validate_hub_manifest` 严格校验：`magic` / `schema` / `digest` / `skills` 类型 /
每条 `name` 非空 / `sha256` 必须是 64 位十六进制。任何字段被改动都会因 digest 不匹配被拒。

`check_hub_update` 返回：

```python
{
  "manifest_valid": bool, "hub_version": str,
  "update_available": bool,
  "added": [skill, ...], "changed": [{"id","name","local","remote"}, ...],
  "removed": [skill, ...], "reason": str,
}
```

判定规则：优先比对清单**声明**的 `sha256`（不是重算值，因为清单不含正文），
缺失时才用 `core.updatecheck.compare_versions` 比较版本号。`added`/`changed`/`removed`
任一非空即 `update_available=True`。

`diff_skills(local, remote)` 直接返回更细的四分类与计数：
`{"added","changed","removed","unchanged","total_local","total_remote"}`。

## 2. CLI 接口（`starry_cli.py` / `dist/星语Starry-CLI.exe`）

| 参数 | 行为 |
| --- | --- |
| `--hub` | 打印技能目录（Markdown 表格）+ 来源与提示 |
| `--hub-search QUERY` | 搜索并打印命中目录 |
| `--hub-info ID` | 打印单个技能的完整说明与指令正文 |
| `--hub-update` | 用 `--hub-manifest` 做技能更新判定 |
| `--hub-manifest PATH` | 本地 `hub.json`；单独给出也隐含执行更新检查 |
| `--hub-source PATH` | 追加本地技能源目录，可重复 |
| `--hub-import ID` | **唯一写操作**：导入为星语自有技能，写入 `config.json` |

约定：全部只读、离线、不联网；`--hub-import` 需要显式提供技能 ID，
且清单里只有元数据没有正文的技能会被拒绝导入。清单文件不存在 / JSON 损坏 /
digest 不匹配均返回非零退出码。

## 3. GUI 接口

- `ui.hub_dialog.HubDialog(parent=None, cfg=None, hub=None)`：技能中心对话框
  （搜索 / 详情 / 添加源 / 导入 / 检查更新 / 导出 `hub.json`）。
- `ui.hub_dialog.offscreen_check()`：无显示器自检，返回 `[(name, ok), ...]`，
  不弹窗、不写文件，供 GUI EXE 的 `--selftest` 调用。
- `main.py --version [--out PATH]`、`main.py --selftest [--out PATH]`：
  窗口程序 `sys.stdout` 可能为 `None`，结果**始终写入 `--out` 指定文件**。
- `scripts/smoke_gui_exe.py --exe PATH [--expect-version X.Y.Z]`：
  子进程冒烟，读取落盘结果判定，退出码 0 = 全通过。

命令面板新增 ID：`hub`（打开 Skills Hub）、`hub_update`（检查技能更新）；
对应 `AssistantApp.open_hub(action=None)`。

## 4. 安全边界（务必阅读）

1. `hub.json` 的 `digest` 与技能 `sha256` 是**完整性校验，不是签名认证**；
   远程清单必须来自可信 HTTPS / GitHub Releases / 官方仓库。
2. Hub **只读发现**：技能正文是提示词文本，不会被 `eval` / `exec` / 当作脚本执行。
3. Hub **不自动下载、不自动安装**；`--hub-import` 与 GUI「导入」都由用户显式触发。
4. `scan_dir` 只遍历本地目录，不发起任何网络请求；`max_depth=4` 防止深层递归。
5. `--hub-import` 会把正文写进 `config.json`，请只导入你信任的技能。

## 5. 最小可运行示例

```python
from core import hub as hb

h = hb.Hub()
print(h.catalog())                         # Markdown 目录
s = h.get("release-checklist")
print(hb.render_skill(s))                  # 详情 + 指令正文
print(hb.to_starry_skill(s)["id"])         # hub_github-release-checklist

m = hb.build_hub_manifest(h.discover(), hub_version="1.0.0")
print(hb.validate_hub_manifest(m))         # (True, 'OK')
print(hb.check_hub_update(h.discover(), m)["reason"])   # 本地技能已是最新
```
