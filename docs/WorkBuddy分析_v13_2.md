# WorkBuddy 架构与能力分析（v13.2 · 基于本机安装逆向）

> 分析对象：`C:\Users\HP\AppData\Local\Programs\WorkBuddy`
> 方法：解析 `resources/app.asar` 头部得到真实模块树（11,423 个打包文件），
> 结合 `app.asar.unpacked/`（main/preload/renderer/cli/native）外壳与 `product.*.json` 多版本配置。
> 目的：理解其主程序逻辑与能力模型，为「是否/如何复刻进星语 Starry」提供事实依据。

## 1. 它是什么

一个 **Electron 桌面应用**（非开源可改），技术栈是 `Electron + React + Node`，
与星语 Starry 的 `PyQt5 + 纯 Python` 完全不同。核心逻辑压缩混淆在 `app.asar`（174MB），
解包目录只有外壳（`preload`、`renderer/assets`、`cli/bin`）。

## 2. 进程 / 架构

| 层 | 入口 | 职责（从真实文件归纳） |
| --- | --- | --- |
| main（主进程） | `main/*.js` | 账号(`account.js`)、生命周期(`app-lifetime-job`)、本地服务编排、MCP host、企业连接器 |
| renderer（前端） | `renderer/assets/*.js`（按 chunk 分包，如 `agent-chat-pane-*.js`） | React UI 各面板 |
| preload | `main/preload/` | 主进程↔渲染进程桥 |
| cli | `cli/bin/codebuddy`、`daemon-supervisor` | 命令行与守护进程（后台 agent） |
| native | `native/` | 原生模块（截图、OCR、剪贴板等） |

> 注意：主进程大量存在 `xxx.js` 与 `xxx2.js` 成对文件——典型的大版本并行/灰度迁移痕迹。

## 3. 能力模型（从 asar 真实路径归纳）

| 能力 | WorkBuddy 证据（真实路径） | 星语 Starry 现状 |
| --- | --- | --- |
| **多模型 / 多服务商** | `renderer/assets/ModelsSettingsPanel-*.js`、`custom-model-auth-detector-*.js` | ✅ 已有 `provider + api_keys + base_urls + models`，并支持本地 Ollama |
| **Agent 编排 / 对话循环** | `main/acp.js`（Agent-Client Protocol）、`workbuddy-user-agent.js`、`agent-chat-pane` | ✅ 已有 `SkillManager` / `PluginMarket` / `AutomationManager` 与工具调用循环 |
| **工具 / MCP 生态** | `main/app-server-mcp-apps-host.js`、`renderer/assets/mcp-server-loader-*.js`、`mcp-token-config-*.js` | ✅ 已有 `core/mcp.py`（stdio JSON-RPC 客户端，零新依赖） |
| **技能系统** | `builtin-skill-picker`、`local-skills-memory`、`installed-skills-entitlement`、`wecom-skill-policy` | ✅ 已有 **Skills Hub**（v13.1/13.2，兼容 GitHub / Claude Code / WorkBuddy 的 `SKILL.md`） |
| **资料库 / 记忆** | `local-skills-memory-*.js` | ✅ 已有 `KnowledgeBase`（本地文档 + TF-IDF 检索） |
| **自动化任务** | `main/automation-failure-galileo.js` | ✅ 已有 `AutomationManager`（定时 / 间隔 / 提醒） |
| **多智能体协作（Colleague/Team）** | `renderer/assets/colleague-chat-page-*.js`、`disable-agent-teams-*.js` | ⚠️ 暂缺（可补：专家会诊已有雏形 `panel_dialog`） |
| **Agent Mail / 邮件智能体** | `agent-mail-*.js`、`agentmail-card-*.js` | ⚠️ 暂缺（可补） |
| **企业生态连接器** | `wechat-chat-history`、`wecom-skill-policy`、`wecomaibot-plugin`、`wechatmp`、`wechatkf`、`tencent-docs/` | ⚠️ 暂缺（需各平台 API/鉴权，外部集成） |
| **遥测 / 埋点** | `buddy-telemetry-context.js` | ❌ 无（隐私取向，建议不加） |

## 4. 「复刻」可行性结论

- **字面「全部复刻」不可行、也不合适**：
  - 11,423 个混淆打包模块，核心逻辑在 174MB 的 `app.asar` 内，无法逐文件对应到 PyQt5/Python；
  - 直接搬运其压缩源码既不可读、不可维护，也涉及闭源产品代码，不符合合规要求。
- **可行且高价值的做法**：借鉴其**能力模型与交互范式**，把星语**暂缺**的少数几项按差距清单补进本项目；
  其上表 ✅ 项星语已对等或更优（如 Skills Hub 已兼容 WorkBuddy 的 `SKILL.md`，MCP 已零依赖实现）。

## 5. 建议的差距清单（优先级）

1. **多智能体协作（Colleague/Team）**——把现有「专家会诊」升级为可对话、可分工的多智能体面板。
2. **Agent Mail / 邮件智能体**——本地优先的邮件读取+摘要+草拟（需 IMAP/OAuth，谨慎处理凭据）。
3. **更强模型路由**——WorkBuddy 的 `custom-model-auth-detector` 提示「按服务商自动识别鉴权方式」，星语可加「自动探测 Base URL / 鉴权头」。
4. **企业连接器**（微信/企微/腾讯文档）——仅在前端有需求且用户授权时做，属于外部集成，非核心。

> 以上 1–3 是星语可在不改变技术栈的前提下直接补强的；4 属于生态对接，投入大、依赖外部授权。
