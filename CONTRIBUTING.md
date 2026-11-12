# 贡献指南 · 星语 Starry

感谢你考虑为「星语 Starry」桌面 AI 助手做贡献。本文档说明从环境搭建到提交合并的完整流程，请在新开 Issue / PR 前先阅读。

---

## 0. 项目一句话

> 一个**轻量、美观、可商用**的本地优先桌面 AI 助手：悬浮球交互、液态玻璃 UI、MCP 工具生态、多站点网页接入、本地模型推理，纯 Python + PyQt5，无运行时联网强依赖。

---

## 1. 开发环境

| 项目 | 要求 |
| --- | --- |
| Python | 3.9+（开发验证用 3.11） |
| 操作系统 | Windows / Linux / macOS 均可运行；Windows 为主发布平台 |
| 构建工具 | PyInstaller 6.x（打包 .exe 用） |

```bash
# 1) 克隆
git clone <repo-url> && cd ai-assistant

# 2) 虚拟环境
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3) 安装依赖
pip install -r requirements.txt
pip install -r requirements-optional.txt   # 可选：TTS 朗读 / 网页接入(playwright) / UPX

# 4) 运行（开发模式）
python main.py
```

### 无显示器也能跑自测

CI 与本地均用 `offscreen` 后端，无需图形环境即可完成全部回归：

```bash
QT_QPA_PLATFORM=offscreen python selftest.py
```

全量自测约 **666 项**检查，0 失败方可合入。新增功能**必须**附带自测（见 §5）。

---

## 2. 代码结构（速览）

```
ai-assistant/
├── main.py                 # 程序入口：EULA 首启门 → 装配 AppController
├── app/                    # 控制器层（UI 线程编排）
│   ├── assistant.py        # AppController：主控制器，命令面板/截图/MCP 接线
│   ├── model_controller.py # 流式对话 worker 调度
│   ├── screenshot_controller.py  # 截图提问 / 看屏幕问答
│   └── panel.py            # 侧边面板
├── core/                   # 业务逻辑（不依赖 UI）
│   ├── config.py           # 配置 + 企业商用合规（EULA 令牌 / 许可校验 / 0o600）
│   ├── agent/              # 智能体：工具注册表、运行时、技能、市场
│   ├── mcp.py              # MCP 工具生态（stdio JSON-RPC，零新依赖）
│   ├── screen.py           # 看屏幕问答纯逻辑
│   ├── automation.py       # 自动化规则引擎
│   ├── library.py          # 资料库（向量检索）
│   ├── gateway.py          # 多站点网关 / 密钥池
│   └── ...
├── ui/                     # 视图层（纯 QPainter 自绘组件）
│   ├── frost.py            # 真·毛玻璃容器
│   ├── liquid.py           # 液态玻璃组件库（GlowOrb/MetricRing/Sparkline…）
│   ├── theme.py            # 主题令牌（圆角/动效/品牌色）
│   ├── splash.py           # 资深级开屏动效
│   ├── eula_dialog.py      # 企业商用 EULA 首启门
│   └── ...
├── assets/                 # 图标（icon.ico 用于打包）
├── docs/                   # 调研 / 复审 / API 文档
├── scripts/                # 跨平台打包脚本（build_windows.ps1 等）
├── starrystar.spec         # PyInstaller 打包配置
├── selftest.py             # 全量自测（离线可跑）
├── requirements.txt        # 必需依赖
└── requirements-optional.txt
```

设计原则：**core 不依赖 ui，ui 不反向调用 core 的具体实现**，控制器在 `app/` 层做装配。新功能优先以「纯逻辑层（core/）+ UI 装配（app/或 ui/）+ 自测（selftest.py）」三段式落地。

---

## 3. 提交规范

提交信息沿用现有约定：

```
feat: v7.6.0 —— 提交结构补全 / exe 打包验证 / API 开放文档
fix: 修复毛玻璃在 Wayland 下回退异常
docs: 补充 API 开放文档的 MCP 接入示例
```

- 类型：`feat` / `fix` / `docs` / `refactor` / `test` / `chore`
- 涉及版本号变更时，标题带 `vX.Y.Z`，并同步更新 `core/config.py::APP_VERSION`、`CHANGELOG.md`、`README.md`、自测中的版本断言
- 保持单次提交**单一意图**，便于 review 与 revert

---

## 4. PR 流程

1. 先开 **Issue** 描述问题 / 提案（安全类见下方 §7）
2. Fork → 新建分支 `feat/xxx` 或 `fix/xxx`
3. 本地跑通 `selftest.py`（offscreen）并确保 `pyflakes` 无新增告警
4. 填写 `.github/PULL_REQUEST_TEMPLATE.md` 模板提交 PR
5. 至少 1 名维护者 Review 通过、CI 全绿后合入

> 模板路径：`.github/PULL_REQUEST_TEMPLATE.md`；缺陷 / 功能请求模板在 `.github/ISSUE_TEMPLATE/`。

---

## 5. 如何新增能力（给开发者）

### 5.1 给智能体加一个工具
在 `core/agent/tools.py` 用 `register_tool(tid, desc, schema, fn)` 注册；UI 通过命令面板或对话触发。MCP 服务器暴露的工具会自动以 `mcp_*` 前缀注册（见 `core/mcp.py`）。

### 5.2 接入外部 MCP 服务器
设置 → **MCP 工具**页填写 `名称 / 启动命令 / 参数`，保存后后台线程握手；危险工具（写文件 / 执行命令）来自**未勾选「信任」的服务器**时默认**拒绝执行**，需用户信任放行（动作护栏，[代码安全性评估](docs/代码安全性评估_v7_5.md)）。

### 5.3 新增 UI 皮肤 / 动效
复用 `ui/theme.py` 令牌（圆角 `RADIUS_*`、动效 `DUR_*`、品牌色 `BRAND`）与 `ui/liquid.py`、`ui/frost.py` 组件，勿硬编码颜色 / 字体。

### 5.4 依赖政策
**默认零新依赖**。确需新增时，先在 Issue 论证，再写入 `requirements.txt`（必需）或 `requirements-optional.txt`（可选、缺失不致命），并更新 `starrystar.spec::excludes`（若排除了冲突模块）。

---

## 6. 打包（产出 .exe）

| 平台 | 命令 |
| --- | --- |
| Windows | `powershell -File scripts/build_windows.ps1` → `dist/星语Starry-Windows/星语Starry.exe` |
| Linux   | `bash scripts/build_linux.sh` → `dist/星语Starry-Linux/星语Starry` |
| macOS   | `bash scripts/build_macos.sh` → `.app` |

构建细节见 [`starrystar.spec`](starrystar.spec) 顶部注释。浏览器内核（chromium）与本地模型二进制**刻意不内嵌**，由产品内「设置」页按需安装，以控制安装包体积。

---

## 7. 安全与许可

- **报告漏洞**：请走 `.github/SECURITY.md` 的私有渠道，**不要**公开 Issue。
- **企业商用**：源码以 MIT 授权，二进制 / 商用需遵守随附 `LICENSE`（商业许可），首启须同意 EULA。
- **密钥**：`config.json`（含 API Key）已被 `.gitignore` 忽略，请勿提交真实密钥。

---

感谢贡献！🚀
