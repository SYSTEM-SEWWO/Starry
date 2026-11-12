# 发布说明 · 星语 Starry v13.2.0

> 主题：**在现有 CLI EXE 之外继续提供 GUI 版 EXE** + **Skills Hub 接入 DeepSeek**
> + **真实 GUI 测评驱动的 401 修复与企业级可靠性改进**。
> v11.5.0 / v12.0.0 / v13.0.0 / v13.1.0 的全部能力、文档、资产与快照完整保留。

## 1. 需求逐条确认

| 要求 | 本版交付 | 状态 |
| --- | --- | --- |
| 在现有 exe 之外另外提供带 GUI 界面的 exe | `星语Starry.exe`（`console=False`，托盘常驻）与 `星语Starry-CLI.exe` **两个独立产物**，一起进 Release | ✅ 沿用 v13.1 并随本版重建、重新冒烟 |
| 新增统一 hub 模块接入 GitHub / **DeepSeek** / Claude Code 等主流 Skills | `core/hub.py` 统一模型；新增 `deepseek` 来源（`deepseek.json` / `*.deepseek.md` / 配置内联 prompts），GitHub / Claude Code / WorkBuddy / 星语自有保持不变 | ✅ |
| 同步更新现有功能 | CLI 4 个新参数、GUI 两个新按钮、API 诊断面板、命令面板新命令、两个 spec / deb / 快照 / 5 个 workflow 同步 | ✅ |
| GUI EXE、Hub 兼容、原有行为共存互不破坏 | 8 套回归 **1351 项 0 失败**；两份 EXE 真实子进程冒烟；47 文件三端同源 | ✅ |
| 可直接集成 | `Hub.from_config()`、`config.hub.example.json`、`--hub-config`、CLI / Python 双示例 | ✅ |
| 兼容范围清晰 | `docs/HUB兼容范围与配置_v13_2.md` §1（含 DeepSeek 诚实界定与字段别名） | ✅ |
| 配置项清晰 | 同上 §2（12 个配置项 + 默认值 + 边界 + 环境变量） | ✅ |
| 异常处理边界清晰 | 同上 §3（17 类扫描边界 + 10 类 API 错误分类） | ✅ |
| 真实用户 GUI 测评、发现并解决问题 | `docs/真实GUI测评报告_v13_2.md`（结论 + 代码行号） | ✅ |
| 企业级可商用改进 | `core/apierrors.py` / `core/apidiag.py` / 静默降级 / 退避 / 脱敏 / 配置隔离 / 审计日志 / 运维 SOP | ✅ |

## 2. 真实 GUI 测评：为什么改这些

以真实 Windows 桌面 + 真实鼠标 / 键盘操作（隔离配置 + 本地 mock 401），
完整走过「启动 → 新手引导 → 主界面 → Ctrl+K 命令面板 → 设置」路径。
结论与证据见 `docs/真实GUI测评报告_v13_2.md`（截图物证已按需移除）。

复现链路：默认 `auto_refresh_models=True` → 启动约 3.5 秒自动 `GET /v1/models`
（带 Authorization）→ Key 失效返回 401 → `list_models` 抛
`HTTP 401：<上游原始响应体>` → `ModelController.show_hint` 一闪而过 →
用户看不到、查不到、不知道怎么修。

## 3. 新增能力

### 3.1 Skills Hub · DeepSeek 来源

- `SOURCES` 增加 `deepseek`；`FORMATS` 增加 `deepseek-json` / `deepseek-md`。
- `parse_deepseek_skill()` / `parse_deepseek_file()` / `parse_deepseek_md()`：
  支持字段别名、四种 JSON 顶层结构、`*.deepseek.md` frontmatter。
- `deepseek_default_dirs()`：随包 `skills/deepseek/`、`~/.deepseek/skills|prompts/`、
  `<project>/.deepseek/skills/`。
- 随包 3 个示例（`deepseek.json` 两条 + `code-review.deepseek.md` 一条）。
- **诚实界定**：DeepSeek 无官方 Agent Skills 规范；兼容的是提示词模板，
  **不调用 DeepSeek API、不联网**，`model` / `temperature` 仅作元数据。

### 3.2 统一配置与异常边界

- `normalize_hub_config()` / `hub_config()` / `config_template()` / `Hub.from_config()`。
- `config.json` 的 `hub` 段：来源开关、额外目录、DeepSeek 子配置、扫描深度、
  导入开关、远程清单占位。示例 `config.hub.example.json` 随 EXE / deb / 快照分发。
- `scan_dir(..., errors=...)` 结构化收集；`Hub.warnings` / `Hub.errors` /
  `Hub.diagnostics()`；GUI「⚙ 生效配置」「🩺 扫描诊断」。
- CLI：`--hub-config` / `--hub-sources` / `--hub-config-show` / `--hub-diagnostics`。

### 3.3 企业级 API 错误治理（401 主链路）

| 模块 | 作用 |
| --- | --- |
| `core/apierrors.py` | 10 类错误分类、可操作建议、指数退避、`redact()` 脱敏 |
| `core/apidiag.py` | 脱敏环形缓冲（100 条）、`STARRY_API_LOG` 可选 JSONL 审计 |
| `core/api.py` | 统一错误出口；`ChatError.detail`；连接/读取超时分离；上游响应不再直出 |
| `app/model_controller.py` | 启动自动刷新失败**静默降级** + 本次会话退避 + 并发防抖；手动刷新才提示 |
| `ui/settings_dialog.py` | 分类化、逐条建议的错误卡片 |
| `ui/api_diag_dialog.py` | 「API 诊断」面板：查看 / 复制脱敏诊断 / 清空 |
| `app/assistant.py` | 命令面板新增「🩺 API 诊断」 |
| `core/config.py` | `STARRY_DATA_DIR` 显式覆盖（企业部署 / 便携 / 多实例 / 测试隔离） |
| `scripts/e2e_session.py` / `e2e_mouse.py` | 可复跑的真实 GUI 测评 + 隔离硬门禁 |

## 4. 修复清单（含实测发现的回归）

1. 启动即 401 弹窗 → 静默降级 + 退避。
2. 401 错误无中文建议 / 上游原文直出 → 分类 + 建议 + 脱敏。
3. 错误一闪而过无法追溯 → 诊断面板 + 审计日志。
4. 401/429/5xx/超时一视同仁 → 10 类分类 + 重试策略 + 退避。
5. **Windows 忽略 `STARRY_DATA_DIR`**（实测 `base_url()` 回退默认，隔离形同虚设）
   → 支持显式覆盖 + e2e 隔离硬门禁。
6. 新增 `failed_detail` 信号导致 `selftest.py` 的 `FakeFetcher` 崩溃
   → 探测式连接 + 静态断言锁死，779 项回归恢复。
7. 命令面板「单击/Enter/双击」不一致 → **如实登记为未修复**（P7）。

## 5. 实测数据

| 项 | 结果 |
| --- | --- |
| 源码回归 | `selftest 779/0` · `v12 63/63` · `v13 172/172` · `v13.1 Hub 131/131` · `v13.2 DeepSeek 73/73` · `企业级 80/80` · `Android 37/37` + `16/16` = **1351 项，0 失败** |
| GUI EXE | offscreen 自检 **31/31**；`smoke_gui_exe.py` 子进程冒烟（含 DeepSeek / 401 / 脱敏 / 隔离 / 诊断断言） |
| CLI EXE | `smoke_cli_exe.py` 真实子进程冒烟（含 `--hub-config-show` / `--hub-sources` / `--hub-diagnostics`） |
| 三端同源 | `sync_core.py` **47 个文件**一致；`--expect-version 13.2.0` 门禁通过 |
| workflow | 5 个 YAML 全部解析通过 |
| 快照 | `releases/星语Starry-v13.2.0/` + 同名 zip，`verify_release.py` 终验 |

## 6. 资产

| 资产 | 路径 |
| --- | --- |
| Windows GUI EXE | `releases/assets/v13.2.0/windows/星语Starry-GUI-v13.2.0.exe` |
| Windows CLI EXE | `releases/assets/v13.2.0/windows/星语Starry-CLI-v13.2.0.exe` |
| Linux / UOS deb | `releases/assets/v13.2.0/linux/星语Starry-CLI-v13.2.0.deb` |
| 离线更新清单 | `releases/assets/v13.2.0/update.json` |
| APK | `releases/assets/v13.2.0/apk/` **仅 README，不含 APK 二进制** |
| 完整快照 | `releases/星语Starry-v13.2.0/` + 同名 zip + `SHA256SUMS-v13.2.0.txt` |

精确字节与哈希见 `docs/交付资产与财务清单_v13_2.md` 与
`releases/SHA256SUMS-v13.2.0.txt`。历史四版快照全部保留。

## 7. 已知限制（不粉饰）

1. 本机无签名 APK（不伪造、不重签、不拿历史包冒充），真机未跑。
2. 命令面板交互一致性（P7）**本版未修复**。
3. GUI 自检为 offscreen 装配验证；真人鼠标测评在源码态完成，未对最终 EXE 做真人点击。
4. `digest` 是完整性校验不是签名认证；建议后续引入 Ed25519 签名。
5. frontmatter 解析器是有意限定的 YAML 子集；两个新对话框未跟随暗色主题。
6. 历史 `v11.5.0` 快照含 keystore，公开分发前必须移除或轮换。
7. 当前目录非 git 仓库，需用户 `git init` + remote + tag 才触发 workflow。

## 8. 升级方式

无需迁移：`config.json` 新增的 `hub` 段为可选，缺省即全部默认值；
旧 `.starryproj` / `.starry` / `update.json` / `hub.json` 全部兼容。
直接替换 EXE 或安装新 deb 即可。
