# Skills Hub · 兼容范围 / 配置项 / 异常处理边界（v13.2.0）

> 本文件是集成契约。三张表分别回答：**能接什么**、**怎么配**、**出错会怎样**。
> 所有行为由 `tests/test_v13_2_hub.py`（73 项）与
> `tests/test_enterprise_api.py`（77 项）锁死，可复跑。

## 1. 兼容范围

| 来源标识 | 载体 | 默认扫描位置 | 归一化后 `source` / `format` |
| --- | --- | --- | --- |
| `claude-code` | `SKILL.md` / `skill.md` + YAML frontmatter | `~/.claude/skills/`、`<project>/.claude/skills/` | `claude-code` / `skill-md` |
| `github` | 同上；另支持扁平 `*.skill.md` | 随包 `skills/`、`.github/skills/`、`<repo>/skills/` | `github` / `skill-md` |
| `workbuddy` | 同上 | `~/.workbuddy/skills/`、`<project>/.workbuddy/skills/` | `workbuddy` / `skill-md` |
| **`deepseek`（v13.2 新增）** | `deepseek.json` / `deepseek-skills.json` / `deepseek-prompts.json`、`*.deepseek.md`、配置内联 `prompts` | 随包 `skills/deepseek/`、`~/.deepseek/skills/`、`~/.deepseek/prompts/`、`<project>/.deepseek/skills/` | `deepseek` / `deepseek-json` 或 `deepseek-md` |
| `starry` | `config.json` 的 `skills` 数组 | `AppConfig.data["skills"]` | `starry` / `starry-json` |
| `local` / `remote` | `hub.json` / `skills.json` 清单条目 | 由 `--hub-source` / `hub.extra_dirs` 显式指定 | 按条目声明 / `hub-json` |

### 1.1 DeepSeek 的**诚实界定**

DeepSeek 目前**没有**官方 Agent Skills / `SKILL.md` 规范。本版兼容的是
**DeepSeek 提示词模板 / 自定义指令**，把它们归一化到同一个 Skill 模型：

- 不声称存在官方技能市场；
- **不调用 DeepSeek API、不联网、不消耗 token**；
- `model` / `temperature` / `top_p` / `max_tokens` 只作为 `meta` 元数据保存，
  由上层决定是否使用；Hub 自身不发起任何模型请求；
- 展示详情时会显式标注「Hub 只保存元数据，不调用 DeepSeek API、不联网」。

### 1.2 DeepSeek 字段别名（大小写按常见写法逐一回退）

| 统一字段 | 接受的键 |
| --- | --- |
| `name` | `name` / `title` / `id` / `label` |
| `description` | `description` / `desc` / `summary` / `about` |
| `body` | `prompt` / `content` / `system_prompt` / `text` / `body` |
| `tools` / `tags` | `tools` / `tags` / `keywords` |
| `meta` | `model` / `model_name` / `temperature` / `top_p` / `max_tokens` / `version` / `icon` / `url` |

JSON 顶层接受四种结构：数组、`{"prompts": [...]}`、`{"skills": [...]}`、
`{"templates": [...]}`。`*.deepseek.md` 复用 `SKILL.md` 的 frontmatter 解析器，正文即提示词。

### 1.3 frontmatter 解析器边界（有意限定）

支持：内联逗号、`- item` 列表续行、`[a, b]` 内联数组、`|` / `>` 块标量、一层嵌套映射、
单双引号、布尔 / 整数 / 浮点 / null。`allowed-tools` / `tools` / `tags` / `keywords` /
`categories` / `triggers` 自动归一化为字符串列表。

**不支持**：YAML 锚点、多层嵌套、复杂类型、多行复杂列表。遇到不支持写法会**降级为字符串**
而不抛异常；这是为了保持零依赖与三端同源，不引入 PyYAML。

## 2. 配置项

配置位置：`config.json` 的 `hub` 段（完整示例见项目根 `config.hub.example.json`）。
CLI 可用 `--hub-config <json文件>` 覆盖（文件可写 `{"hub": {...}}` 或裸 hub 配置）。

| 键 | 类型 | 默认 | 含义 / 边界 |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | `false` 时不扫描任何来源；其余配置仍合法 |
| `sources` | list[str] 或逗号串 | 全部 5 个 | 只允许 `claude-code` / `github` / `workbuddy` / `deepseek` / `starry`；未知项过滤并告警 |
| `extra_dirs` | list | `[]` | 元素可为路径字符串（默认 `local`）或 `{"path","source"}`；不存在的目录只记告警，不抛异常 |
| `max_depth` | int | `4` | 合法范围 `0..8`；越界或非整数回退 4 |
| `deepseek.enabled` | bool | `true` | 关闭后不加载 DeepSeek 目录 / 文件 / 内联 prompts |
| `deepseek.dirs` | list[str] | `[]` | 额外提示词目录 |
| `deepseek.files` | list[str] | `[]` | 额外 `deepseek.json` 文件路径 |
| `deepseek.prompts` | list[dict] | `[]` | 直接内联的提示词模板；非 dict 项过滤并告警 |
| `deepseek.model` | str | `""` | 仅元数据，Hub 不据此发请求 |
| `allow_import` | bool | `true` | `false` 时 `--hub-import` 与 GUI「导入」一律拒绝（RC=2） |
| `remote_manifest` | str | `""` | 仅记录；**Hub 永不联网**，留空即离线 |

CLI 覆盖项（优先级最高）：`--hub-sources github,deepseek`、`--hub-source <目录>`（可重复）。

其它相关环境变量：

| 变量 | 作用 |
| --- | --- |
| `STARRY_DATA_DIR` | **v13.2 修复**：显式数据/配置目录，企业部署 / 便携模式 / 多实例隔离 / 自动化测试。设置后直接作为配置目录，不再回退 `%APPDATA%` |
| `STARRY_API_LOG` | 可选审计日志（JSONL，脱敏），供企业合规留存；默认关闭 |

可观测性命令：

```bash
starry --hub-config-show        # 打印生效配置 + 配置告警 + 模板
starry --hub-diagnostics        # 打印生效来源 / 告警 / 逐条扫描异常 / 技能数
```

GUI：「⚙ 生效配置」「🩺 扫描诊断」两个按钮展示同样信息。

## 3. 异常处理边界

**总原则**：扫描 / 配置归一化中的单点失败一律收敛，不向调用方抛异常；
只有用户显式操作（导入无正文、清单无效）才返回结构化失败结论与非零退出码。

| 场景 | 行为 | 抛异常 | 可见性 |
| --- | --- | --- | --- |
| 配置根节点非 dict | 全量回退默认值 | 否 | `warnings` |
| 单个配置项类型错误 | 该项回退默认值，其它项保留 | 否 | `warnings` |
| 未知来源名 | 过滤 | 否 | `warnings` |
| `max_depth` 越界 | 回退 4；扫描时停止深层递归 | 否 | `warnings` |
| 目录不存在 | 跳过 | 否 | `errors`（`stage=scan`） |
| 文件读取 / 编码失败 | 跳过该文件 | 否 | `errors` |
| JSON 损坏 | 跳过该文件 | 否 | `errors`（`解析失败`） |
| 单条缺 `name` 或 `prompt` | 跳过该条 | 否 | `errors` |
| frontmatter 未闭合 | 退化为正文 | 否 | — |
| `hub.json` digest 不匹配 | 不收录，记录原因 | 否 | `errors` |
| id 冲突 | 先出现的源优先去重 | 否 | — |
| `errors` 超过 200 条 | 停止记录，扫描继续 | 否 | `ERROR_LIMIT` |
| 导入技能无正文 | 拒绝，RC=2 / GUI 提示 | 否 | 明确文案 |
| `allow_import=false` 时导入 | 拒绝，RC=2 | 否 | 明确文案 |
| `hub.json` 无效（更新判定） | `manifest_valid=false`、`update_available=false` | 否 | `reason` |
| 远程清单不可用 | 不联网、不判定 | 否 | — |
| `--hub-config` 文件不存在 | 明确报错，RC=2 | 否 | stdout |

`errors` 元素结构：`{"path", "stage", "reason"}`，由 `scan_dir(..., errors=list)` 收集；
`Hub.errors` / `Hub.diagnostics()["errors"]` 可读取。`warnings` 为字符串列表。

### 3.1 API 错误分类（v13.2 新增，见 `core/apierrors.py`）

| HTTP / 异常 | 分类 | 可重试 | 基础退避 | 主操作 |
| --- | --- | --- | --- | --- |
| 401 | `auth` | 否 | — | 打开设置核对 Key 与 Base URL |
| 402 | `quota` | 否 | — | 充值 / 换模型 |
| 403 | `forbidden` | 否 | — | 检查权限 |
| 404 | `not_found` | 否 | — | 检查 Base URL / 模型名 |
| 429 | `rate_limit` | 是 | 30s | 稍后重试 |
| 5xx | `server` | 是 | 10s | 自动重试 |
| 连接失败 / 超时 / DNS | `network` | 是 | 5s | 检查网络 |
| 非 JSON 响应 | `parse` | 否 | — | 检查是否误填网页地址 |
| 未配置地址 / Key | `config` | 否 | — | 打开设置 |
| 其它 | `unknown` | 是 | 5s | 打开诊断 |

退避公式 `min(300, base * 2^(attempt-1))`。所有对外文本经 `redact()`，
**不输出** API Key / Bearer Token / 完整响应体。

## 4. 可直接集成的最小示例

```python
from core import hub as hb

# 方式一：从 config.json 的 hub 段装配（推荐，CLI/GUI/三端一致）
h = hb.Hub.from_config(cfg)               # cfg 为 AppConfig / dict / JSON 路径
skills = h.discover()
print(h.catalog())
print(h.diagnostics()["errors"])

# 方式二：显式配置
cfg_obj, warnings = hb.normalize_hub_config({
    "sources": ["github", "deepseek"],
    "deepseek": {"prompts": [{"name": "review", "prompt": "审查代码…"}]},
    "allow_import": False,
})
h = hb.Hub(config=cfg_obj)
```

```bash
# 方式三：CLI / EXE
starry --hub-config config.hub.example.json --hub
starry --hub-config-show
starry --hub-sources deepseek --hub-search review
```
