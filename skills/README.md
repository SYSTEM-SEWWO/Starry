# Skills Hub 示例技能目录

本目录演示星语 Skills Hub 对主流来源技能 / 提示词模板的**自动发现**能力。
`core/hub.py::default_sources()` 会把仓库根的 `skills/` 识别为 GitHub 风格来源，
并把 `skills/deepseek/` 单独识别为 DeepSeek 来源（其它来源会跳过该子目录，避免重复解析）。

| 路径 | 演示的来源 | 特点 |
| --- | --- | --- |
| `claude-code-style/SKILL.md` | Claude Code / Anthropic | 标准 YAML frontmatter + allowed-tools + metadata.version |
| `github-copilot-style/SKILL.md` | GitHub Copilot / Agent Skills | 兼容 SKILL.md，带 license / tags / 多行 description |
| `flat-skill.skill.md` | GitHub 扁平仓库 | 单文件 `*.skill.md`，无需子目录 |
| `deepseek/deepseek.json` | **DeepSeek 提示词模板** | 数组 / `prompts` 清单，字段别名 name/title、prompt/content、model/temperature |
| `deepseek/code-review.deepseek.md` | **DeepSeek 单文件模板** | `*.deepseek.md`，frontmatter + 正文即提示词 |

> **DeepSeek 的兼容范围**：DeepSeek 目前没有官方 Agent Skills / SKILL.md 规范。
> 这里兼容的是 *DeepSeek 提示词模板 / 自定义指令*，把它们归一化成同一个 Skill
> 模型；Hub **不调用 DeepSeek API、不联网**，`model` / `temperature` 只作为元数据保存。

Hub **只读、不执行**：技能正文仅作为提示词文本，不会被当成脚本运行。
导入某个技能：`starry --hub-import deepseek-code-review`。

其它自动扫描位置：

- `~/.claude/skills/<name>/SKILL.md`、`<project>/.claude/skills/…`（Claude Code）
- `.github/skills/<name>/SKILL.md`（GitHub）
- `~/.workbuddy/skills/`、`{workspace}/.workbuddy/skills/`（WorkBuddy）
- `~/.deepseek/skills/`、`~/.deepseek/prompts/`、`<project>/.deepseek/skills/`（DeepSeek）
- 星语 `config.json` 的 `skills` 数组（自有格式）

统一配置项见项目根 `config.hub.example.json` 与
`docs/HUB兼容范围与配置_v13_2.md`：来源开关、额外目录、DeepSeek 内联 prompts、
扫描深度、导入开关都集中在 `config.json` 的 `hub` 段。
