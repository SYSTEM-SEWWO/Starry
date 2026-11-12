# 真实 GUI 测评报告 · 星语 Starry v13.2.0

> 方法：**真实 Windows 桌面 + 真实鼠标/键盘输入**（pyautogui / user32），
> 不是调用应用内部 API、不是 mock 界面。
> 所有结论都给出证据（截图文件、mock 请求日志、代码行号、测试输出）。
> 复跑工具：`scripts/e2e_session.py` + `scripts/e2e_mouse.py`。

## 1. 测评环境与隔离

| 项 | 值 |
| --- | --- |
| 系统 | Windows（1920×1080，Console 会话） |
| 自动化 | `pyautogui 0.9.54` + `user32`（EnumWindows / SetForegroundWindow / SetCursorPos） |
| 应用 | `python main.py`（源码态，真实桌面窗口） |
| 服务端 | 本地 `127.0.0.1:8765` mock，`/v1/models` 与 `/chat/completions` 一律返回 401 |
| 配置 | 隔离 `STARRY_DATA_DIR` + `APPDATA` 双保险，假 Key `E2E-INVALID-KEY-DO-NOT-USE` |
| 网络 | **零外部流量**；请求只到 127.0.0.1；不读取、不复制用户真实 API Key |

隔离硬门禁（`e2e_session.py`）：启动 GUI 前用同一套环境变量验证
`get_config_dir()` 指向隔离目录且 `base_url()` 指向 mock，不通过就拒绝启动。
实测输出：

```
隔离门禁通过： {'dir': '...\\_e2e_out\\profile',
               'base': 'http://127.0.0.1:8765/v1', 'has_key': True}
```

## 2. 证据清单

> 注：截图与本地 mock 日志等物证已按需求移除；下列结论的文字描述仍有效。

- 启动约 3.5 秒自动 `GET /v1/models`（带 Authorization）→ Key 失效返回 401，
  首启被「欢迎使用星语 Starry」多步引导遮罩覆盖，401 提示被挡在后面（原 E2）。
- 引导走完后主聊天窗口正常出现，界面上没有任何 401 痕迹（原 E3）。
- Ctrl+K 命令面板正常弹出，含「打开设置」等命令（原 E4）。
- 双击误触「网页大模型」打开 DeepSeek 网页登录页（原 E5）。
- 修复前 `core/api.py` 直接 `raise ChatError("HTTP %d：%s" % (status, r.text[:200]))` 上游原文直出（原 E6）。
- 修复前 `app/model_controller.py` 用 `QTimer.singleShot(1200, refresh_models)` + `show_hint(...)` 让错误一闪而过（原 E7）。
- 修复前 `core/config.py` Windows 只读 `APPDATA`，忽略 `STARRY_DATA_DIR`（原 E8）。
- 脱敏配置核查：用户真实配置 `provider=zhipu`、Key 已填、`auto_refresh_models=True`（只查存在性，未读取明文）（原 E9）。
- 复跑脚本：`scripts/e2e_session.py`、`scripts/e2e_mouse.py`（原 E10）。

## 3. 真实用户操作路径（逐步）

| 步 | 操作 | 观察 |
| --- | --- | --- |
| 1 | 启动应用 | 3.5 秒后 mock 收到带 Authorization 的 `/v1/models` → 401（E1） |
| 2 | 截图首屏 | 多步新手引导遮罩盖住主界面，401 提示被挡在后面（E2） |
| 3 | 真实鼠标点击引导「下一步」（像素定位到绿色按钮 `(1054,927)`） | 引导卡片跟随悬浮球移到右下角，仍为多步 |
| 4 | 继续点击 | 引导完成，主聊天窗口出现；**错误提示已消失、无处可查**（E3） |
| 5 | Ctrl+K 打开命令面板 | 面板正常，含「打开设置」等（E4） |
| 6 | 单击「打开设置」 | 只选中、不执行 |
| 7 | 按 Enter | 未执行（焦点在搜索框） |
| 8 | 双击列表项 | 触发了相邻命令，打开 DeepSeek 网页登录页（E5）——多窗口重叠下点击易穿透 |

> 第 6–8 步是**真实的可用性观察**：命令面板在「单击 / Enter / 双击」上表现不一致，
> 已记入问题清单 P7；本版先修 401 主链路，该项列为后续 UI 改进。

## 4. 发现的问题与修复状态

| # | 问题 | 证据 | 影响 | 修复 |
| --- | --- | --- | --- | --- |
| P1 | **启动即 401**：默认 `auto_refresh_models=True`，Key 失效时启动 1.2s 自动请求并把错误弹到主界面 | E1/E7/E9 | 新用户第一眼就是报错 | ✅ `ModelController` 启动刷新失败**静默降级** + 本次会话退避 + 并发防抖 |
| P2 | **错误不可操作**：401 抛 `HTTP 401：<上游原始响应体>`，没有中文建议 | E6 | 用户不知道下一步做什么 | ✅ `core/apierrors.py` 统一分类 + 逐条建议 + 主操作 |
| P3 | **上游响应体直出**可能泄露敏感内容 / 展示 HTML | E6 | 安全与体验 | ✅ `redact()` 脱敏 + 截断；`ChatError.detail` 结构化 |
| P4 | **错误一闪而过**，事后无法追溯 | E3 | 「问题都解不了」 | ✅ `core/apidiag.py` 环形缓冲 + `ui/api_diag_dialog.py` + 命令面板「API 诊断」 |
| P5 | **配置目录不可覆盖**：Windows 忽略 `STARRY_DATA_DIR` | E8 + 实测 `base_url()` 回退默认 | 企业部署 / 便携模式 / 测试隔离失效，自动化会读写用户真实配置 | ✅ `get_config_dir()` 支持显式覆盖，并加 e2e 隔离硬门禁 |
| P6 | 401/429/5xx/超时一视同仁，无重试与退避 | E6 | 临时故障也被当成配置错误 | ✅ 10 类分类 + 指数退避（封顶 300s）+ 可重试标记 |
| P7 | 命令面板单击/Enter/双击行为不一致 | E4/E5 | 交互不直观 | ⏳ 记为后续 UI 改进，**未在本版声称修复** |
| P8 | 首启引导遮罩会盖住错误提示 | E2 | 错误不可见 | ✅ 启动错误改为静默 + 诊断可查，不再依赖遮罩下的 toast |

**额外回归（修复过程中实测发现并修复）**：
`selftest.py` 的 `FakeFetcher` 只有 `failed(str)` 信号，新增 `failed_detail(dict)` 后
`ModelController` 直接 `.connect` 导致 779 项自测崩溃。
已改为 `hasattr(fetcher, "failed_detail")` 探测式连接，并用静态断言锁死；
`selftest.py` 重跑 **779/0** 通过。

## 5. 正面结论（实测）

- 401 **没有阻塞应用**：引导完成后主聊天窗口、命令面板、Skills Hub 等离线能力正常可用（E3/E4）。
- 本地 mock 全程未收到任何聊天请求，说明 Hub / 离线功能不会偷偷调用模型。
- 隔离配置下的请求只到 `127.0.0.1`，没有外部流量。

## 6. 复跑命令

```bash
# 终端 A：启动隔离 GUI + 本地 401 mock
python scripts/e2e_session.py --out C:/path/to/e2e_out

# 终端 B：真实鼠标 / 键盘操作
python scripts/e2e_mouse.py --out C:/path/to/e2e_out --action windows
python scripts/e2e_mouse.py --out C:/path/to/e2e_out --action shot --name 01_startup
python scripts/e2e_mouse.py --out C:/path/to/e2e_out --action click --x 1054 --y 927 --name 02_next
python scripts/e2e_mouse.py --out C:/path/to/e2e_out --action key --keys ctrl+k --name 03_palette

# 单元 / 集成回归
python tests/test_enterprise_api.py
python tests/test_v13_2_hub.py
python scripts/verify_release.py --version 13.2.0
```

## 7. 诚实标注

- 本报告基于**源码态** `python main.py` 的桌面操作，未对最终 EXE 做真人点击测试；
  EXE 用 `--selftest --out` 做 offscreen 自检（`scripts/smoke_gui_exe.py`）。
- 截图来自一次具体会话；多窗口重叠导致的点击穿透属于测评环境现象，不等同于产品缺陷。
- P7（命令面板交互一致性）**未修复**，已如实列入后续改进。
- `digest` 是完整性校验，不是签名认证；诊断记录不含密钥，但使用者仍需自行保证来源可信。
