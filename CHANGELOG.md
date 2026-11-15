## [13.9.0] - 2026-11-15

### 白屏根因修复（用户反馈「2 级子窗口全部只卡在白屏、无法交互」）

实证定位（`_glassdbg.py`）：`FrostGlass.__init__` **自带 QVBoxLayout**，
v13.8 的 `apply_glass()` 又调用 `glass.setLayout(inner)`，Qt 直接忽略；
而原布局条目已先被 `old.takeAt(0)` 全部摘走 → 控件不属于任何布局 →
尺寸为 0 / 白屏。叠加 `WA_TranslucentBackground` + 透明 QSS 让窗口整体透明。

重写 `ui/glass_dialog.py`：
- **完全不动原布局**：只插入一个 `_Backdrop(FrostGlass)` 背景层，
  `lower()` 到兄弟控件之下，`WA_TransparentForMouseEvents` 不吃鼠标，
  resize 自动铺满；
- 不改 windowFlags、不设窗口透明、不覆盖 QDialog 背景 QSS；
- 背景层强制 faux 渐变（子控件 `frameGeometry()` 是相对坐标，
  直接抓屏会抓错屏幕区域）；
- 幂等、原生对话框与已自带玻璃窗口跳过。

实测（真实 Qt 窗口）：控件全在原布局（标签/输入/按钮宽度 516、标签页 538）、
`translucent=False`、按钮可点击、层级正确、resize 跟随、幂等。

### 缓存「总是清不掉」修复

三重根因（实证）：
1. `project_dir` 用 `os.getcwd()` —— EXE 启动时 cwd 常是桌面/系统目录，
   扫不到真实项目缓存 → 新增 `project_root()` 从 `__file__` 可靠推断；
2. `.pyc` 运行时由 Python 自动重建，清理后立刻重扫显示「又有了」→
   扫描规则明确标注自动重建，清理后不再立刻重扫、显示实际删除数；
3. 任一文件失败即 `return` 中断整批 → 改为记录失败并继续；
4. 用户数据目录里真正堆积的 `config.json.bak_*` / `sessions.json.bak-*`
   旧备份**从未进入扫描规则** → 新增 `stale_backups` 类别，
   按修改时间保留最近 3 份，其余可清理（仍先备份、可撤销）。

`CacheDialog` 新增「⚡ 一键清理」（省略二次确认但仍先备份、仍走安全白名单）、
清理结果明确显示「实际删除 N 个文件 / 失败 N 项」及失败原因。

### 新增：悬浮球不定时小表情 / 小动作

`ui/ball_moods.py`：待机每 12–28 秒随机触发，持续 1.8–3.2 秒；
8 种表情（眨眼 / 微笑 / 惊讶 / 困倦 / 爱心眼 / 歪头 / 挥手 / 哈欠）+
微动作（浮动 / 摇摆 / 弹性缩放 / 小星星）。拖拽与思考/输出态不打扰；
`cfg.data["ball_moods"]` 可开关，命令面板 `😊 让悬浮球做个表情` /
`🎭 开关悬浮球小表情` 与托盘菜单均可触发。

### 反复通读后的其它修复
- 悬浮球构造时无 parent，配置开关读不到 → 构造后显式 `set_moods_enabled`；
- 背景层抓屏坐标修正、默认配置补 `ball_moods: True`（三端同源）；
- 全仓静态门禁致命 0。

验证：`test_v139_fixes` 30/30、真实 Qt 集成（白屏修复/表情/缓存窗口）全通过、
selftest 历史定向 48/48、v13.8 31/31、v13.7 25/25、v13.6.5 31/31、
三端同源门禁 PASS。

## [13.8.0] - 2026-11-15

### 缺陷修复（用户反馈「还是不行 / 时好时坏」）

1. **对话删除后无法及时更新、重启才见效、删了又回来**：
   根因是 `history`(内存) 与 `sessions`(存储) 双写漂移 + `SessionDialog` 删除
   当前会话后 store 已切 current，但 `_on_session_selected` 因 `id == current_id()`
   直接 return，主窗口仍持旧 history，随后 `_save_current_session()` 把旧内容
   写进新会话 → 旧对话"复活"。
   修复：`SessionStore` 增加 `revision` + 变更订阅；主窗口订阅后自动
   `_sync_from_store()`；切换/删除时强制刷新；**统一为单一真源**（存储只存
   非 system 消息，system 运行时注入），去掉所有 `sessions.append` 双写。
   实测：删除单条 / 批量 / 清空 / 删除整个会话后，store 与 UI 立即一致，
   重新加载不复活，其它会话与会话列表完全不变。
2. **主窗口仍要拖特定位置**：旧实现在 `MouseMove` 里反复用 `widgetAt` 判定，
   鼠标滑过按钮就中断。改为「按下时判定一次并锁定 `_drag_active`」，
   移动阶段只看该标志；标题栏、消息区空白、状态栏均可拖，按钮/输入框照常响应。
3. **勾选删除单条看不见**：旧实现只给 `_render_history`/`on_send` 的气泡挂
   复选框，流式回复气泡没有；入口还藏在「⋯」菜单里。
   修复：`_ensure_checks()` 按布局顺序为**所有**气泡统一挂可见复选框并校准序号；
   新增常驻「☑」「🔍」按钮、右键菜单（复制/编辑/收藏/删除本条）、
   `Ctrl+Shift+A` 进入选择模式；删除改用 `messagetools.map_ordinals` 实时映射，
   不再依赖会漂移的缓存索引。
4. **所有二级窗口毛玻璃圆角**：新增 `ui/glass_dialog.py`，全局 Show 事件钩子
   自动把任何 QDialog 内容包进 `FrostGlass`（圆角 + 磨砂 + 高光 + 投影），
   保留系统标题栏与全部交互；原生对话框与已自带玻璃的窗口自动跳过。
   `main.py` 启动时安装，覆盖未来新增窗口。

### 新增功能（core/messagetools.py，三端同源纯逻辑）

- 消息级工具箱：单条删除 / 编辑 / 复制 / 收藏，会话内查找（Ctrl+F），
  本对话消息统计（条数/字数/估算 token），所选消息导出 Markdown。
- 斜杠命令：`/new /clear /select /find /sessions /settings /export /help`。
- 会话备份/恢复：`sessions.json` 快照到 `backups/`（保留最近 10 份），
  恢复前自动再备份一次，带 JSON 结构校验。
- 命令面板 / 托盘菜单新增 6 个入口；`Ctrl+F` 查找、`Ctrl+Shift+X` 退出选择。

### 反复通读源码后的额外修复
- 修掉 3 处历史 `undefined name 'QMessageBox'`（归档导入 / 分支列表 /
  会话合并），静态门禁致命项归零。
- 智能选模型确认框改为非阻塞，避免模态短时阻塞主窗口。
- `pyflakes_gate.py` 分级门禁持续保证「致命 0」。

验证：`test_v138_fixes` 31/31、真实 Qt 窗口集成全通过（玻璃/勾选/拖拽/
删除即时生效/不复活/清空隔离/删会话同步）、`test_v137_fixes` 25/25、
`test_v1365_layout` 31/31、三端同源门禁 PASS。

## [13.7.0] - 2026-11-13

### 对话管理与交互缺陷修复（7 项，用户反馈逐项对应）

1. **清空对话记录**：旧实现清空后立刻 `show_welcome()` 又插入欢迎气泡，观感上「清不掉」；
   且 `set_messages` 未显式传 session_id。现在 `core/sessions.py` 新增
   `clear_messages(session_id)`，显式锁定目标会话、只清该会话、用空态提示替代欢迎气泡；
   其它对话与会话列表完全不变，重新加载后仍为空。
2. **勾选删除单条记录**：新增 `delete_messages(session_id, indices)`；主窗口消息勾选模式
   （标题栏「⋯ 更多」/ 命令面板 / 托盘 / `☑` 工具条），每条气泡带复选框、全选、
   删除选中、完成。仅删除所选，保留未选中消息，会话与对话列表保持不变。
   修复 history 与 sessions 索引偏移（启动时补齐的 system 消息）导致的删错行。
3. **统一拖拽**：旧 eventFilter 只装在 `title_bar`，子控件吞掉鼠标事件 → 只有特定区域可拖。
   现在装到 QApplication 子树过滤器，标题栏 / 消息区空白 / 状态栏等均可拖；
   `_INTERACTIVE` 白名单放行按钮、输入框、下拉、链接文本等，交互完全正常。
4. **主窗口背景自定义**：设置 → 外观新增「🖼 主窗口背景」（跟随主题 / 纯色 / 图片 +
   叠加强度），`FrostGlass.set_custom_background()` 即时绘制，「立即应用」无需重启，
   保存后持久化；图片失效自动回退纯色。
5. **缓存清理无响应**：旧版在 UI 线程同步 scan/clean + 嵌套模态确认框 → 窗口冻结。
   现在全部走 `_CacheWorker(QThread)`，按钮全程可点、进度可见，成功/失败/异常均
   `_finish_busy()` 恢复交互；确认框与结果提示改为非阻塞 `show()`。
6. **子窗口打开后主窗口卡死**：`QDialog.exec_()` 应用模态 + 主窗口置顶导致子窗口被遮、
   主窗口不可点。新增 `_show_child()` 统一非模态（NonModal + 跟随置顶 + 持有引用），
   12 个缓存子窗口与设置/关于/洞察等全部改走该路径；`finished` 统一
   `_on_child_closed()` 刷新状态栏 / 技能 / 工具 / 模型列表，主窗口功能继续可用。
7. Release 资产补充 macOS / DEB / Linux / Android 多平台包（见 releases/）。

验证：`test_v137_fixes.py` 25/25、真实窗口集成 5/5、
`AssistantApp` 真实链路（清空隔离 + 勾选删除）全通过；三端同源门禁 PASS。

## [13.6.5] - 2026-11-13

### 布局根因修复：栏目密度四档 + 旧配置一次性迁移

用户反馈「布局没有任何改动，再放大一点，还是很紧，太奇怪了」。两个真因：
1. 项目目录改名 `Starry` → `星语Starry` 且 EXE 移入 `releases/`，上轮给出的 EXE 路径失效，用户运行的仍是旧版；
2. `ui/chat_window.py::_restore_geometry()` 用 `config.json` 里保存的 `window_size=[430,640]`
   **覆盖**代码里的新默认值，导致改源码对老用户完全无效。

- 新增 `core/uilayout.py`（三端同源、零 Qt）：紧凑 / 标准 / 宽松 / 超宽松四档全部栏目尺寸；
  `migrate()` 首次启动一次性把旧窗口抬到 `620×860` 并打版本标记，之后不再覆盖用户手动尺寸。
- `ui/chat_window.py`：`_apply_layout()` 统一应用密度，`set_density()` 即时切换（无需重启），
  `reset_layout()` 一键恢复推荐布局；标题栏 6 个次要图标收进「⋯ 更多」菜单解决横向拥挤；
  状态栏显示 `v13.6.5 · 布局宽松`，方便确认实际运行的版本；新增 `Ctrl+Alt+D` 快捷键。
- `ui/settings_dialog.py`：外观页新增「栏目密度」下拉 + 「↺ 恢复推荐布局」按钮（信号即时生效）。
- `app/assistant.py`：命令面板 `📐 切换栏目密度` / `↺ 恢复推荐布局`，托盘菜单同步入口。
- `core/cli.py` + `android/core/cli.py`：`--ui-layout` 只读诊断、`--ui-density NAME` 直接设置。
- `main.py`：中文安装路径下 Qt 平台插件加载失败（`no Qt platform plugin could be initialized`）
  的自动兜底 —— 复制 platforms 到纯英文临时目录。

### GitHub 流程与文档
- 新增 `docs/GitHub_提交与Release发布流程.md`：首次配置 / 身份 / token / SSH / 建远程仓库 /
  日常提交（约定式信息）/ 冲突处理 / 版本发布清单 / tag 触发 CI / `gh release create` /
  网页发布 / 发布后校验 / 8 条常见问题排错表。
- 新增一键脚本 `scripts/git_push.sh`（门禁 → 提交 → 推送）与
  `scripts/github_release.sh`（门禁 → 打包 → SHA 校验 → 可选推 tag → 建 Release 上传资产）。
- README 新增「🚀 如何使用」章节（运行 / 布局四档 / 提交 / 发布 / 源码运行）与流程入口。

## [13.6.4] - 2026-11-12

### 界面优化：聊天窗口上/下栏布局放宽（拥挤度修复）

用户反馈：聊天窗口顶部标题栏与底部输入区过于拥挤。调整（`ui/chat_window.py`）：

- 标题栏 48→56px，内边距/间距 14/6→16/10。
- 消息区边距 12/10→14/14、条目间距 10→14。
- 输入区边距 (12,6,12,10)→(14,10,14,14)、间距 6→10；智能体行按钮 28→34px、行距 4→8。
- 输入框最小高 74→88px（自适应上限 150→170、余量 +22）。
- 底部按钮行距 4→10；提示词 30→32、深度思考 30→36、发送 32→38px。
- 状态栏 24→30px、左右边距 14→16。

## [13.6.3] - 2026-11-12

### Bug 修复：SSE 流式响应中文乱码（ä½ å¥½…）

用户反馈：助手输出中文变成 `ä½ å¥½ï¼æä»ä¹æå¯ä»¥å¸®ä½ åï¼` 这类乱码。

根因：`core/api.py` 的 `chat_stream` / `chat_agent_stream` 用
`resp.iter_lines(decode_unicode=True)` 读 SSE 流。`requests` 在响应**不带 charset**
时（OpenAI 兼容 / LM Studio / Ollama 的 `text/event-stream` 通常如此）会把
`resp.encoding` 默认成 `ISO-8859-1`（latin-1），于是把 UTF-8 中文字节按 latin-1 解码 → 乱码。

修复：两个流式方法在读取前显式 `resp.encoding = "utf-8"`（LLM 接口始终为 UTF-8），
错误响应体 `.text` 也按 UTF-8 解码。`android/core/api.py` 同源同步修改。

## [13.6.2] - 2026-11-12

### Bug 修复：发图片给纯文本模型触发服务端 HTTP 400

用户反馈：带图发送时服务端返回
`HTTP 400: The provided messages contain images, but minicpm5-1b does not support image inputs.`
（v13.6.1 把默认模型设为 `minicpm5-1b`，纯文本）。

根因：`on_send` 带图时调用 `ensure_vision_model()` 尝试自动切视觉模型，但**仅在模型池存在
可用视觉模型时才切换**；当本机只加载了纯文本模型、无视觉模型可切时，它只提示一句就放行，
图片仍被塞进请求体 → 服务端 400。

修复：
- `app/assistant.py` `on_send` 增加**发送前能力守卫**：带图时先取 `ensure_vision_model()`
  的返回值（当前模型能否看图）；无可用视觉模型时**本地下掉图片、仅发文字并明确提示**，
  彻底杜绝 400，对话仍可继续。
- `app/model_controller.py` `ensure_vision_model()` 改为返回 `bool`（当前模型能否看图），
  供守卫判断。
- `core/models.py` 视觉识别增强：`_VISION_HINTS` 扩充 `minicpm-v` / `minicpmo` / `internvl` /
  `cogvlm` / `llava` / `moondream` / `smolvlm` / `florence` / `idefics` / `qwen-vl` /
  `qwen2-vl` / `qwen2.5-vl` / `pixtral` 等，`MiniCPM-V-2_6`、`InternVL`、`LLaVA` 等不再被
  误判为「不支持图片」（纯文本模型如 `minicpm5-1b` 仍正确判为不支持，不影响默认行为）。

## [13.6.1] - 2026-11-12

### 模型配置修复续：默认 lmstudio 且开箱可用

用户明确要求「默认 lmstudio，且可用」。在 v13.6.0 端点/空模型/深度思考修复基础上补强：

- **默认服务商改为 `lmstudio`**（桌面端 `core/config.py` 与安卓端同步），新装即落在本地优先。
- **切换到本地服务商（lmstudio / ollama）时自动拉取模型**，下拉框立即出现本机真实模型，无需手动点「获取模型列表」。
- **拉到模型后自动选中第一个**；聊天模型下拉中**过滤 `embed` 类 embedding 模型**，避免误选不能对话的模型。
- 同步对齐当前用户配置：`provider` 由误挂的 `ollama` 改回 `lmstudio`（其 `Base URL` 实为 LM Studio 1234 端口），默认模型取本机缓存的真实聊天模型，其余服务商原样保留。

## [13.6.0] - 2026-11-12

### Bug 修复：设置里改不了模型 / 默认 LM Studio

用户反馈「没法更改设置模型，默认 lmstudio」。在**配置副本**上复现（未改动用户真实配置），
确认 4 个根因，全部基于真实代码与实测数据：

1. **模型框手动输入被忽略**（最直接原因）：模型下拉 `setEditable(True)`，但
   `_on_save()` 取 `currentData()` —— 用户改写文本后它仍返回旧下拉项数据，
   输入的新模型名被静默丢弃。修复：比较编辑文本与当前项数据，用户改写时以输入值为准。
2. **服务商名硬编码端点**：`ModelFetcher` 只看 `key == "ollama"` 就固定请求
   `localhost:11434/api/tags`，完全忽略用户填写的 Base URL。用户真实配置里
   `ollama.base_url = http://127.0.0.1:1234/v1`（LM Studio 端口），
   因此「获取模型列表」永远拉不到真实模型，下拉只剩 5 个写死的 Ollama 预设。
   修复：新增零依赖 `core/endpoints.py`，按**实际地址**判定 Ollama `/api/tags`
   或 OpenAI 兼容 `/v1/models`；`core/models.py` 保留同名包装函数。
3. **本地服务商没有预设模型**：`lmstudio` / `modelscope_local` 的 `models=[]`、
   `default_model=""`，无缓存时设置页模型下拉 **0 项**、`cfg.model()` 返回空串，
   用户看不到也选不了模型。修复：
   - 空模型时给出明确引导（点「获取模型列表」或手动输入模型 ID）+ 输入框占位提示；
   - 保存时禁止静默写入空模型，弹可操作提示并阻止保存；
   - `AppConfig.model()` 在配置为空时回退到预设 / 缓存首个模型。
4. **深度思考覆盖手动选择**：`deep_thinking=True` 时 `set_deep_thinking()` 无条件
   `set_model(candidates[0])`。修复：当前已是推理模型则保持用户选择；关闭时只在
   当前模型仍是「当初自动切换过去那个」时才恢复，不覆盖用户后来手动改的模型。

### 新增的排障能力
- 设置 → 模型：检测到「Ollama 服务商 + 1234 端口」等错配时，显示
  **「一键改用 LM Studio」** 按钮，切换服务商并保留已填 Base URL / Key。
- `normalize_base_url()` 清理粘贴带换行的 URL（真实配置里出现过
  `http://127.0.0.1:1234\n/v1`）。
- CLI `starry --model-diagnose`：**只读**打印服务商 / Base URL / 端点判定 /
  当前模型 / 可选模型 / 错配建议，不修改任何配置。对当前配置的实测输出明确给出
  「服务商与地址不匹配 → 建议 lmstudio」。
- `starry_cli.spec` 补齐 v13.2–v13.6 新增纯逻辑模块的 hiddenimports，
  避免 CLI EXE 里这些命令因函数内 import 失效。

### 验证
- 全量 `selftest.py` **1050 通过 / 0 失败**（新增 38 项 bug 复现级回归：
  端点判定、URL 归一化、空模型回退/拦截、错配一键修正、
  获取模型列表传参、深度思考保护、CLI 诊断、spec 声明）。
- 本地脚本在配置副本上验证：空模型保存被拦截、手动输入模型可保存、
  错配修正后 `provider=lmstudio` 且保留 `http://127.0.0.1:1234/v1`。
- `check_core_parity.py --expect-version 13.6.0` 通过（三端同源 56 文件）；
  独立单测 172/172 + 80/80 + 131/131 + 73/73。
- 版本真源 `13.5.0 → 13.6.0`；根目录 `星语Starry-GUI-v13.6.0.exe`，历代保留。

---

## [13.5.0] - 2026-11-12

### 大版本主题
开发者调试模式与分级日志 · 界面自动缩放 · 设置页视觉重构 ·
缓存清理进设置页 · 控制逻辑条件化分发

### ① 开发者调试模式 + 日志输出
- 新增 `core/devlog.py`：DEBUG/INFO/WARN/ERROR 分级、500 条环形缓冲、
  实时订阅 sink、可选 JSONL 落盘、导出/清空、**所有文本过 `apierrors.redact` 脱敏**；
  默认完全静默，只有开启 `debug_mode` 或 `STARRY_DEBUG=1` 才收集。
- 环境变量：`STARRY_DEBUG` / `STARRY_LOG_LEVEL` / `STARRY_LOG_FILE`；
  配置：`debug_mode`、`log_level`（默认关闭 / INFO）。
- 新增 `ui/devtools_dialog.py`：实时日志视图、级别下拉、状态与分级计数、
  环境信息（版本/平台/Python/数据目录/配置摘要，**不显示 Key 明文**）、
  清空/复制/导出；跨线程日志经 Qt 信号转到 UI 线程。
- 埋点：启动（`startup`）、请求发起/完成/失败（`request`，含耗时与字符数）、
  设置变更（`settings`）、自动缩放（`uiscale`）、缓存（`cache`）。
- 入口：命令面板 `🛠 开发者调试面板`、托盘、设置页「存储与缓存」；
  CLI `--devlog` / `--debug` / `--log-level`。

### ② 自动缩放大小比例
- 新增 `core/uiscale.py`（纯逻辑、三端同源）：按屏幕可用区域与逻辑 DPI
  推荐缩放档（标准 1.0 / 大 1.15 / 超大 1.3）、最终字号与窗口尺寸，
  小屏自动收紧窗口；`apply_to_config` 写回 `font_scale` 与 `window_size`。
- 设置 → 外观新增「🔎 自动缩放」分区：开关 `auto_ui_scale`（默认关）、
  实时推荐说明、「立即按屏幕适配」按钮；开启后启动时在首屏后的延迟初始化里应用，
  **不拖慢启动**。
- CLI `--ui-scale [--screen WxH] [--dpi N]` 纯计算展示建议，不改配置。

### ③ 设置 UI 美化
- 新增 `ui/settings_style.py`：附加 QSS（页签选中态下划线、状态横幅、
  分区标题/分隔线、输入焦点态、卡片式 GroupBox、按钮主次层次），
  叠加在 `build_qss` 之上，**不改既有控件结构**。
- 设置页顶部新增「⚙ 当前生效配置」状态横幅（服务商/模型/主题/缩放/调试状态）；
  8 个页签统一带图标；关键分区有标题与说明；`apply_theme` 同步刷新附加样式。
- 修正 `__init__` 初始字号未应用 `font_scale` 的问题。

### ④ 清理缓存（上轮已有，本轮补强入口与策略）
- 核心 `core/cacheclean.py` / `ui/cache_dialog.py` 沿用 v13.4（只读扫描、
  硬保护名单、二次确认、先备份可撤销、每批 ≤10 文件、绝不 rmtree）。
- **设置页新增「💾 存储与缓存」页**：只读展示可清理类别/项数/占用，
  一键打开缓存清理窗口，并显示开发者调试入口。
- 新增「退出时自动清理临时残留（.tmp/.log）」开关 `auto_clean_tmp`（默认关），
  退出时仍走备份 + 小批量安全链路。
- 上轮的命令面板 / 托盘 / CLI 入口全部保留。

### ⑤ 优化控制逻辑
- `_apply_settings` 重构：记录 `_applied_snapshot`，按**变更项条件化分发**——
  主题/字号只在相关字段变化时刷新、热键只在变更时重启、悬浮球只在尺寸变化时重建、
  置顶只在变更时设置、模型列表只在服务商变化或首次重载；首次调用仍等价旧版全量应用。
- 新增 `_refresh_open_dialogs_theme()`：把十余段重复的 `if self._xxx_dialog is not None`
  收敛为统一遍历，兼容两种 `apply_theme` 签名，新增窗口不再漏刷新，异常静默降级。
- 变更项写入分级日志，可在调试面板核对；自动缩放复用 `_apply_settings`，避免写两套逻辑。

### 版本与验证
- 版本真源 `13.4.0 → 13.5.0`；三端同源 **55 文件**一致，
  `check_core_parity.py --expect-version 13.5.0` 通过。
- 全量 `selftest.py` **1012 通过 / 0 失败**（新增 63 项；浏览器全链路因
  本机未装 Chromium 内核按环境 SKIP）。
- 独立单测：172/172、80/80、131/131、73/73 全通过。
- 根目录产物：`星语Starry-GUI-v13.5.0.exe`（+ SHA-256），历代 EXE 保留不覆盖。

---

## [13.4.0] - 2026-11-11

### 大版本主题
把根目录后代版本 EXE 写进 CI · 应用内 API Key 申请全程指引 ·
安全可撤销的缓存清理 · 大模型能力矩阵与自动路由

### ① 后代版本 EXE 打包进入 CI 步骤
- `.github/workflows/release.yml` 新增 `root-exe` job（Windows runner）：
  安装依赖 → 生成图标 → `python scripts/build_root_exe.py` →
  校验 `星语Starry-GUI-v<版本>.exe` 与 SHA-256 → 上传 artifact →
  由 `publish` job 附到 GitHub Releases（`root-exe-assets/*.exe`）。
- `.github/workflows/ci.yml` 新增「根目录后代版本 EXE 命名约定自检」，
  每次 push / PR 校验 `build_root_exe.py` 能从 `APP_VERSION` 解析出 SemVer。
- 本地等价命令仍是 `python scripts/build_root_exe.py`（自动读版本、历代不覆盖）。

### ② 应用内「申请 API Key」完整过程说明
- 新增 `core/apikey_guide.py`（纯数据 / 零联网）：从 `PROVIDERS` 单一真源取
  申请地址与 Base URL，给出 6 步通用流程 + 各服务商差异化提示 +
  5 条安全注意事项 + Key 格式自检；网页版 / 本地模型明确标注「无需 Key」。
- 新增 `ui/apikey_guide_dialog.py`：左侧服务商、右侧步骤正文、顶部 Key 状态、
  「复制完整说明 / 打开申请地址 / 去设置填写 / 关闭」。
- 接线：设置页 API Key 行新增「📖 申请步骤」按钮；命令面板 `apikey_guide`；
  托盘菜单入口。CLI：`--apikey-guide [PROVIDER]` 打印同一份说明。

### ③ 清理全部应用缓存（安全优先的设计）
- 新增 `core/cacheclean.py`：扫描只读 → 分类列出 → 用户勾选 → 二次确认 →
  **先备份可撤销** → 每批最多 10 个文件、失败即停。
- 硬保护名单：`config.json`（含 API Key）/ 会话 / 资料库 / 长期记忆 /
  自动化 / 统计 / 网关数据 / GGUF 模型 / 浏览器登录态一律不碰；
  拒绝路径穿越、符号链接与非白名单后缀；**只 `os.remove` 单文件，绝不 rmtree**。
- 可清理：Python 字节码 `.pyc`、原子写残留 `.tmp`、日志 `.log/.jsonl`、
  `config.json` 内的 `model_cache` / `market_cache` 等软缓存键。
- 新增 `ui/cache_dialog.py`：勾选 + 试运行 + 危险警告二次确认 + 备份目录入口。
- CLI：`--cache-scan`（只读）、`--cache-clean`（默认试运行，需 `--yes` 才真删）。
- 命令面板 `cache_clean`、托盘菜单入口。

### ④ 完善大模型能力
- 新增 `core/modelcap.py`：模型能力矩阵（工具 / 视觉 / 推理 / JSON / 免费 /
  上下文窗口 / 最大输出，明确标注 `confidence=heuristic`）、上下文 token 估算、
  **按本轮请求特征自动路由**、失败回退链。
- 已知约束：`deepseek-reasoner` 等推理模型不支持 function calling，工具请求会避开；
  图片请求优先视觉模型；深度思考优先推理模型；超上下文窗口直接淘汰。
- 接线：`auto_route_model` 开关（默认关，向后兼容），开启后每轮请求在构造
  `ChatClient` 前自动选模型；命令面板 `model_route` / `model_caps` /
  `auto_route_toggle`；CLI `--model-capabilities` / `--model-route`
  （可加 `--need-tools` / `--with-images` / `--deep`）。

### 版本与验证
- 版本真源 `13.3.0 → 13.4.0`；三端同源 **53 文件**一致，
  `check_core_parity.py --expect-version 13.4.0` 通过。
- 全量 `selftest.py` **949 通过 / 0 失败**（新增 73 项；浏览器全链路因本机
  未安装 Chromium 内核按环境 SKIP，不再是假失败也不中断回归）。
- 独立单测：172/172、80/80、131/131、73/73 全通过。
- 修复两处旧的「钉死单一发版号」断言（`test_v13_2_hub.py`、
  `test_enterprise_api.py`），改为 SemVer 下限，避免每次升代都要改测试。
- 修复 `modelcap.route_model` 失败分支 `alternatives` 类型不一致导致的 CLI 异常，
  并在无预设模型的服务商下给出可操作提示。

---

## [13.3.0] - 2026-11-11

### 大版本主题
调研 GitHub 同类爆火开源项目并融入四项优点 · 每次更新固定产出「后代版本后缀」根目录 EXE

### 调研对象（GitHub 星数，2026-11-11 检索）

| 项目 | 星数 | 重点借鉴的优点 |
| --- | --- | --- |
| Open WebUI | ~157k | 自托管本地优先、插件生态 |
| LobeChat / LobeHub | ~84k | Agent / 技能市场、可编辑记忆 |
| AnythingLLM | ~68k | 文档问答的 source citations、Intelligent Skill Selection（工具按需加载省 token） |
| Cherry Studio | ~53k | 跨会话 + 知识库全局搜索、Markdown / 代码高亮 / Mermaid、对话导出 |
| LibreChat | ~47k | 多服务商统一、MCP |
| Chatbox | ~42k | 本地会话存储、跨平台简洁体验 |

### 新增（全部零新依赖、向后兼容）

- `core/globalsearch.py`：跨数据源统一检索（会话 / 资料库 / 提示词 / 长期记忆 / 收藏）。
  中英文分词 + 二元组、各源内排名归一化后全局混排、单源异常隔离、鸭子类型注入。
- `ui/globalsearch_dialog.py`：全局搜索窗口（实时防抖、数据源过滤、命中统计、
  双击跳转、复制结果）；接入命令面板 `global_search`、托盘菜单。
- `core/library.py`：新增 `citations_for()` / `format_citations()`，把本轮回答引用了
  哪些资料回显给用户（AnythingLLM 式可溯源）；`app/assistant.py` 记录
  `_last_citations`，角标显示来源数，命令面板 `citations` 打开来源面板。
- `core/toolselect.py`：工具按需选择，按名称 / 描述 / 参数与本轮问题的相关性只注入
  Top-K 工具，输出 token 节省报告；`core/agent/tools.py` 新增
  `get_tool_specs_for_query()`（不传问题行为与旧 API 完全一致）。
- `core/markdown_render.py`：代码块语言标签、Mermaid 图表源码标记、
  `extract_code_blocks()` / `mermaid_blocks()` / `code_block_languages()`。
- `core/cli.py`：新增 `--global-search` / `--citations` / `--tool-select` /
  `--tool-top-k` / `--tool-input`，与桌面同源，全部本地执行零联网。
- `scripts/build_root_exe.py`：**固定约定** —— 每次更新执行
  `python scripts/build_root_exe.py`，自动从 `APP_VERSION` 读后代版本号，
  打包并把 `星语Starry-GUI-v<版本>.exe` + `.sha256` 放到项目根目录，
  历代产物不覆盖、可回溯。

### 版本与产物
- 版本真源 `13.3.0`（config / mcp / pyproject / release.yml）；三端同源 **50 文件**一致。
- 根目录产物：`星语Starry-GUI-v13.3.0.exe`（+ SHA-256 校验和文件）。
- `tests/test_enterprise_api.py` 版本断言改为 SemVer 下限，避免每次升代都要改测试。

### 验证
- 全量 `selftest.py` **876 通过 / 1 失败**（新增 54 项全通过；唯一失败
  `已就绪时点击安装有反馈` 属环境相关：沙箱未装 Chromium 浏览器二进制，
  `playwright_available()` 为 False，与本次改动无关）。
- 发布门禁 `check_core_parity.py --expect-version 13.3.0` 通过；
  独立单测 172/172 + 80/80 + 131/131 通过。

---

## [13.2.0] - 2026-11-10

### 大版本主题
GUI EXE 与 CLI EXE 双产物共存 · Skills Hub 新增 DeepSeek 兼容 · 真实 GUI 测评驱动的 401 企业级治理

### 新增
- `core/hub.py`：新增 `deepseek` 来源（`deepseek.json` / `*.deepseek.md` / 配置内联 prompts），
  字段别名、四种 JSON 顶层结构、`deepseek_default_dirs()`；随包 `skills/deepseek/` 3 个示例。
  **诚实界定**：DeepSeek 无官方 Skills 规范，兼容的是提示词模板；不调用 API、不联网。
- 统一 Hub 配置：`normalize_hub_config()` / `hub_config()` / `config_template()` /
  `Hub.from_config()` / `Hub.diagnostics()`；`config.json` 的 `hub` 段 + `config.hub.example.json`。
- 异常边界：`scan_dir(..., errors=...)` 结构化收集、`Hub.warnings` / `Hub.errors`、
  `ERROR_LIMIT`；CLI `--hub-config` / `--hub-sources` / `--hub-config-show` / `--hub-diagnostics`；
  GUI「⚙ 生效配置」「🩺 扫描诊断」。
- `core/apierrors.py`：10 类 API 错误分类、可操作建议、指数退避（封顶 300s）、
  `redact()` 脱敏（Bearer / sk- / api_key / token / 查询串密钥）。
- `core/apidiag.py`：脱敏环形缓冲（100 条）、`STARRY_API_LOG` 可选 JSONL 审计。
- `ui/api_diag_dialog.py`：「API 诊断」面板（查看 / 复制 / 清空），命令面板新增 `api_diag`。
- `scripts/e2e_session.py` / `scripts/e2e_mouse.py`：可复跑的真实 GUI 鼠标测评
  + 隔离硬门禁（不碰用户真实 Key、零外部流量）。

### 修复（真实 GUI 测评取证）
- **启动即 HTTP 401**：`core/api.py::list_models` 原样抛上游响应体、
  `ModelController` 启动 1.2s 自动刷新并 `show_hint` 一闪而过。
  现改为分类化可操作错误 + 静默降级 + 本次会话退避 + 并发防抖；
  只有手动「测试连接」才提示。
- **错误不可追溯**：诊断面板 + 审计日志 + 设置页分类化错误卡片。
- **配置目录不可覆盖**：Windows 下 `get_config_dir()` 忽略 `STARRY_DATA_DIR`，
  导致企业部署 / 便携 / 测试隔离失效、自动化读写用户真实 `config.json`。
  现支持显式覆盖并加 e2e 硬门禁。
- 上游响应体直出 → 脱敏摘要；连接 / 读取超时分离 `(5s, 15s)`。
- 新增 `failed_detail` 信号使 `selftest.py` 的 `FakeFetcher` 崩溃
  → 探测式 `hasattr` 兼容 + 静态断言锁死，779 项回归恢复。

### 工程化
- 版本真源 `13.2.0`（config / mcp / pyproject / build_deb）；三端同源 **47 文件**。
- 两个 spec 新增 `core.apierrors` / `core.apidiag` / `ui.api_diag_dialog` 与
  `config.hub.example.json` datas；`build_deb.py` / `make_release.py` 同步收集。
- `ci.yml` / `release.yml` 增加 `test_v13_2_hub.py` 与 `test_enterprise_api.py`。
- `smoke_cli_exe.py` / `smoke_gui_exe.py` 增加 DeepSeek / 401 / 脱敏 / 隔离 / 诊断断言。
- `main.py --selftest` 自检扩展至 31 项。
- 文档：`docs/真实GUI测评报告_v13_2.md`（含 `docs/evidence_v13_2/` 截图）、
  `docs/HUB兼容范围与配置_v13_2.md`、`docs/企业级运维与故障排查_v13_2.md`、
  `docs/RELEASE_NOTES_v13_2.md`、`docs/交付资产与财务清单_v13_2.md`。

### 实测
8 套回归 **1351 项 0 失败**；GUI EXE 自检 31/31；两份 EXE 子进程冒烟；
5 个 workflow YAML 通过；47 文件三端同源。

### 已知限制
命令面板「单击/Enter/双击」交互不一致（测评 P7）**未修复**；
无签名 APK；GUI 自检为 offscreen，真人测评在源码态完成；
`digest` 非签名认证；两个新对话框未跟随暗色主题。

---

## [13.1.0] - 2026-11-09

### 大版本主题
GUI 版 EXE + Skills Hub（兼容 GitHub / Claude Code / WorkBuddy 等主流 Skills）+ 技能更新功能

### 新增
- `core/hub.py`：统一 Skills Hub 纯逻辑（零第三方依赖、三端同源）
  - 手写极简 YAML frontmatter 解析器，支持内联逗号 / 列表续行 / 内联数组 /
    `|` `>` 块标量 / 一层嵌套映射；列表型字段自动归一化
  - 统一 Skill 模型、内容摘要 `skill_digest()`、多源发现、搜索、星语格式转换
  - `hub.json` 生成 / 严格校验（`magic` / `schema` / `digest` / `sha256`）
  - `diff_skills()` / `check_hub_update()` 技能更新四分类判定
  - `bundled_skills_dir()` 统一源码 / onefile EXE / deb 三种形态的技能目录定位
- `skills/`：3 份示例技能（Claude Code 风格 / GitHub Copilot 风格 / 扁平 `*.skill.md`）
- `ui/hub_dialog.py`：桌面 Skills Hub（搜索 / 详情 / 添加源 / 导入 / 检查更新 / 导出清单）
  + `offscreen_check()` 无显示器自检
- `main.py`：`--version` / `--selftest --out` 无显示器自检入口（窗口程序结果落盘）
- `scripts/smoke_gui_exe.py` / `scripts/smoke_cli_exe.py`：本机与 CI 共用的 EXE 子进程冒烟
- CLI 7 个新参数：`--hub` / `--hub-search` / `--hub-info` / `--hub-update` /
  `--hub-manifest` / `--hub-source` / `--hub-import`
- 命令面板 2 条新命令：`hub` / `hub_update`
- **真实 GUI 版 EXE**：`starrystar.spec` 构建 `dist/星语Starry.exe`（`console=False`），
  随 tag 进 GitHub Releases

### 工程化
- 版本单一真源升级到 `13.1.0`（`core/config.py` / `core/mcp.py` / `android/pyproject.toml`）
- `core/__init__.py` 懒导出 `hub`；`sync_core.py` 同步后三端同源 45 个文件
- 两个 spec 补 `core.hub` 与 `skills/` datas；GUI spec 补齐 v12/v13 懒加载模块
- `scripts/build_deb.py` 收集 `skills/`；`scripts/make_release.py` 目录白名单补 `skills/`
- `ci.yml` / `release.yml` 增加 Hub 单测；`build-windows.yml` 新增 `build-gui-exe` job
- `release.yml` 快照校验增加 `skills/` / `core/hub.py` / `ui/hub_dialog.py`
- `gen_update_manifest.py` 改为收录同平台**全部正式资产**（此前取体积最大者会吞掉 CLI EXE）；
  `--update-check` 同步列出该平台全部资产
- `starry_cli.py` 尊重 `PYTHONIOENCODING`，解决管道下中文输出编码判定问题
- `tests/test_v13_features.py` 版本断言改 SemVer 下限，关闭 v13.0 遗留 P0-2「测试与发版号耦合」

### 修复（12 项真实缺陷，详见 `docs/评审纪要_v13_1.md`）
- frontmatter 列表字段未归一化 / `metadata.version` 未读取 / `_as_list(dict)` 产生垃圾
- 清单条目被加 `remote:` 前缀重造 id、用空正文重算 sha256 比对 → 往返比对全错
- 扁平 `*.skill.md` 文件名覆盖 frontmatter `name`
- 「缺文件」用例假绿、spec 接入断言过松、CLI EXE 中文冒烟编码误判
- 更新清单同平台多资产被吞
- **`make_release.py` 找错发布说明文件名**：v13.0 快照内 `RELEASE_NOTES.md` 退化成
  一行占位（GitHub Release 正文也因此不完整）→ 三级回退 + 单测锁死
- 发版快照目录白名单漏 `skills/` → 完整快照缺示例技能

### 文档
新增 14 份 `docs/*_v13_1.md`：发布说明、代码安全性评估、HR / 美术 / 资深程序员 /
GitHub / 创造力复审、API 开放文档、使用指南（总 / Windows GUI EXE / Linux deb）、
交付资产与财务清单（APK 单列）、项目结构与提交指南、评审纪要。

### 已知限制
本机无签名 APK（不伪造）；当前目录非 git 仓库；历史 v11.5 快照含 keystore 需轮换；
`digest` 是完整性校验不是签名认证；GUI 自检未覆盖真人交互点击。

---

## [13.0.0] - 2026-11-07

### 大版本主题
整体项目 → 多线并行 → 自动更新 · WorkBuddy 式电脑端工作台 · Windows EXE / Linux deb 大版本

### 新增
- `core/project.py`：整体项目状态机（目标 / 任务 / 依赖 / 状态 / 产物）、`ready_tasks()` 分波、
  `project_progress()`、`.starryproj` 存档（magic/version/payload/SHA-256，损坏一律拒绝）、
  `plan_from_goal()` 默认「三条并行 + 一条汇总」模板、Markdown 项目报告
- `core/parallel.py`：分波并行执行器，结果按输入顺序回填、单线异常隔离、整体超时
  （`shutdown(wait=False, cancel_futures=True)`）、失败重试、循环依赖防御、
  `local_worker` 离线确定性执行器（不联网 / 不消耗 token）
- `core/updatecheck.py`：SemVer 比较、平台归一化、`update.json` 结构与 digest 校验、
  平台资产选择、分块 SHA-256 校验、离线更新判定
- `ui/workbench_dialog.py`：WorkBuddy 式桌面工作台（目标输入 → 任务树 → 分波并行 →
  进度条 → 报告；保存 / 载入 / 导出 / 检查更新；双击看结果明细）
- `scripts/gen_update_manifest.py`：只从真实二进制计算哈希生成 `update.json`，
  拒绝空清单，支持本地离线与 GitHub 正式两种模式
- `.github/workflows/update-manifest.yml`：Release published 后下载全部资产 →
  生成权威清单 → `--clobber` 回传，可重跑补齐 APK
- CLI 12 个新参数：`--project` / `--project-load` / `--project-save` / `--parallel` /
  `--workers` / `--timeout` / `--retries` / `--execute` / `--update-check` /
  `--update-manifest` / `--update-url` / `--workbench`
- 桌面命令面板 6 条新命令：打开工作台、从当前对话规划项目、规划并多线并行执行、
  保存 / 载入整体项目、检查版本更新
- `tests/test_v13_features.py`：172 项单测（三模块 + CLI + 打包接入 + 更新清单生成器回归）

### 工程化
- 版本单一真源升级到 `13.0.0`（`core/config.py` / `core/mcp.py` / `android/pyproject.toml`）
- `starry_cli.spec` hiddenimports 增加 3 个新模块；`scripts/build_deb.py` 描述与文档收集范围更新
- `ci.yml` 增加 v12/v13 单测、三端同源门禁、Linux deb 构建验证 job；
  `release.yml` 增加 v13 单测与更新清单生成器自测
- `core/` ↔ `android/core/` 44 个文件字节一致；全量 AST 门禁通过
- 测试版本断言改为动态读取单一真源，避免升级版本时改测试

### 修复（本轮反复优化）
- `gen_update_manifest.py` 初版按目录推断平台，把 `apk/README.md` 误判为 android 资产
  → 改为只按二进制扩展名判定，新增 10 条单测锁死
- `--project-load` 载入损坏项目时重复打印两行提示 → 失败即返回
- v13 单测把 13.0.0 同时用作「当前版本」与「远端新版本」，升级后 3 项失效
  → 远端版本独立为 `99.0.0`
- EXE 冒烟脚本把 GBK 输出按 UTF-8 解码导致误判 → 冒烟脚本多编码兜底（EXE 本身无缺陷）

### 产物与验证
- Windows EXE `15,928,759` 字节：10 项子进程冒烟 RC=0，`--workbench` 实跑 100%
- Linux deb `195,294` 字节 / 59 data 文件：独立解析校验通过，含 3 个新 core 模块
- `update.json`：2 个真实资产（windows / linux），哈希与资产字节一致；**不含 android**（本机无 APK，不伪造）
- 全量回归 `779 + 63 + 37 + 16 + 172 = 1067` 项通过，0 失败
- 5 个 GitHub Actions workflow YAML 解析通过

---

## [12.0.0] - 2026-11-07

### 大版本主题
安卓闪退根因修复 · 三端同源工程化 · 星尘卡/存档/上下文预算 · 完整 Releases 快照体系

### 新增
- `core/stardust.py`：星尘卡 `build_echo_card`、上下文预算 `plan_trim`、
  `.starry` 可移植存档 `pack_archive/unpack_archive`（SHA-256 校验、纯标准库、三端同源）
- `scripts/sync_core.py` / `check_core_parity.py`：替代人工双份拷贝，CI 强制字节一致 + 版本单一真源
- `scripts/verify_apk.py`：APK 静态鉴定器（签名块、Chaquopy 资源、依赖混装检测）
- `scripts/build_deb.py`：纯标准库构造 deb（ar + tar.gz），本机可真实产出并自检
- `scripts/make_release.py`：一个版本 = 完整自包含文件夹 + 同名 zip + MANIFEST + checksums + RELEASES 索引
- `.github/workflows/release.yml`：tag → 门禁 → 全量测试 → 快照 → Release 的统一编排
- CLI：`--doctor` / `--archive` / `--restore` / `--budget` / `--echo`
- 桌面命令面板：星尘卡、上下文预算、导出/导入存档、环境自检（5 条）
- Android：诊断页、ActivityIndicator 思考指示、深色主题、字号缩放、气泡层级、
  停止生成、流式节流、全局 excepthook + crash.log

### 修复（安卓闪退专项，详见 docs/APK鉴定与闪退根因报告_v12_0.md）
- **F1** `AppConfig.load()` 移入 startup try；`get_config_dir()` 改为 Android 感知 + 逐级回退，永不抛异常
- **F2** 注入 `app.paths.config` 到 `STARRY_CONFIG_DIR`
- **F3** 所有 `toga.Selection(value=...)` 做成员校验（实测 Toga 0.5.7 会抛 ValueError）
- **F4** 修正 `learn_from_conversation(prompt=, answer=)` → 真实签名 `(user_text, assistant_text)`，
  长期记忆在安卓端真正生效
- **F5** `scroll_to_bottom()` → `vertical_position = max_vertical_position`（实测 0.5.7 无前者）
- **F6** 全局 excepthook + 应用内诊断页；**F7** 单回调异常隔离；**F8** 单窗口约束
- **构建链**：`android/pyproject.toml` 去掉裸 `toga` 元包、钉死 `toga-core==0.5.7`，
  消除 v11.5 APK 实测到的 toga 0.2.15 / toga_core 0.5.7 混装

### 测试重写
- `tests/test_android_v12.py`：真实 core + 严格 UI 替身，37/37；修正了 v11.5
  「FakeMemory 复刻错误签名导致假绿」的问题
- `tests/test_v12_features.py`：63/63
- `android/test_app_logic.py`：fake 层修正后 16/16
- EXE 冒烟：`--version/--platform/--doctor/--budget/--archive/--restore` 退出码均 0

### 收尾复核（发布快照终检）
- 安全：`make_release.py` 的 `"*.keystore"` 曾写在**精确匹配集合**里导致通配永不生效，
  任意名称密钥可能随发布 zip 泄漏；改为 `fnmatch` 通配排除 6 类密钥/证书，
  并新增 `assert_no_secrets()` 发布前扫描，命中即中止发版
- 修复 `SHA256SUMS` 资产路径被扁平化（现保留 `apk/ linux/ windows/` 子目录）
- 修复 `RELEASES.md` 索引不幂等（同版本重跑会产生重复行），并自动补录历史版本
  文件夹；现含 v12.0.0 `latest` 与 v11.5.0 `superseded` 两行
- `MANIFEST.md` 明确说明本清单与 `checksums.txt` 自身不列入校验条目
  （342 条校验 / 344 个文件，差值为这两个文件）
- 重建 EXE 与 deb（此前落后于 `core/cli.py` 的 `--budget` 修复），六项冒烟 RC=0；
  deb 独立解析 `Version: 12.0.0` / 55 data 文件通过
- 补齐 v12.0 文档矩阵 12 份（六项复审 / 纪要 / API / 两份使用指南 / 结构指南 /
  财务清单），`docs/*.md` 123 份全量进入版本快照
- **全量自测由「761 通过 / 12 失败」修到「779 通过 / 0 失败」**：
  装好 Playwright Chromium 后失败依旧（767/12），证伪了此前「环境依赖」的判断；
  真实根因是 `core/gateway.py` 把统计 / 预算固定在 `~/.starry`，Windows 上
  `expanduser("~")` 读 `USERPROFILE`，测试里 `HOME=tmp` 隔离无效，读到真实累计数据。
  修复：新增可选 `STARRY_DATA_DIR` 注入点（默认路径不变、不迁移用户数据），
  自测各段独立隔离；新增 `chromium_kernel_available()`，已装好内置 Chromium 时
  「一键安装内核」不再重复下载 100+ MB（`ui/settings_dialog.py`）
- `core/` 同步到 `android/core/`（gateway.py / browser_llm.py），重建 EXE 与 deb
  并刷新 `releases/assets/v12.0.0/` 版本资产
- 生成 `releases/星语Starry-v12.0.0/`（344 文件）与同名 zip，
  `MANIFEST.md` / `checksums.txt` / `SHA256SUMS-v12.0.0.txt` / `RELEASES.md` 齐备；
  v11.5.0 历史快照 331 文件完整保留、未覆盖

### 变更
- 版本号统一 12.0.0；selftest 中 4 处硬编码版本断言改为动态
- CI tag 规则收紧为 `v*.*.*`，三个 workflow 共用 concurrency 串行化，
  Release 一律 append_body；新增 APK 构建后静态鉴定门禁

---

# 变更日志 / Changelog

本文件记录星语 Starry 的版本演进。版本号遵循 `主版本.次版本.修订号`（语义化版本）。

## [11.5.0] - 2026-11-07

### 攻坚主线：Windows 真 `.exe` 闭环（长期缺口）
- 此前每版 Windows 端只提供 `build_windows_cli.ps1`、从未产出真 exe；本轮在**本机 Wine**（`wine64` + Windows 版 Python 3.11 embeddable + PyInstaller 6.22.3）真实编译出 `星语Starry-CLI.exe`（PE32+ console x86-64，12MB）
- 新增 `.github/workflows/build-windows.yml`：推 `v*` tag → `windows-latest` 打包 → `--version` / `--platform` 冒烟自检 → Artifact → **追加资产到 GitHub Releases**（`append_body`，不覆盖安卓侧 Release 标题）；一个 tag 同时产出 APK + EXE
- 完善 `scripts/build_windows_cli.ps1`：venv 幂等、读取 `APP_VERSION`、打包后自检并校验 `$LASTEXITCODE`、随包附带 README / 命令行指南 / 构建指南
- 新增 `docs/Windows_EXE_构建指南.md`：三种获得 exe 的方式（Releases / Windows 本地 / Linux+Wine）、实测踩坑（`init_sys_streams` → 必须走 `cmd /c`）、验证清单、SmartScreen 等 FAQ
- **实测修复 Windows 中文控制台秒退**：cp1252 无法编码中文，`core/cli.py::_emit` 抛 `UnicodeEncodeError` → exe 退出；`starry_cli.py` 入口 `reconfigure(errors="replace")` + `_emit` 捕获并按目标流编码 `replace` 重写（最后退 ASCII）双层兜底，UTF-8 / cp1252 双场景 `--version` / `--platform` 退出码均 0；桌面 / 安卓 `core/cli.py` 同源同步

### 电脑端新增功能：对话洞察三件套（core/insights.py）
- 新建 `core/insights.py` 纯函数层（零 GUI 框架依赖、不 import sessions 避免循环依赖、绝不修改入参），桌面与 `android/core/insights.py` 字节一致
- **🔀 分支对比**：`common_prefix_len` / `diff_sessions` → 最长共同前缀、`modified`（同位置差异）、`a_only` / `b_only`、`identical`、`similarity`；`format_diff_markdown` 渲染
- **🧬 会话合并**：`merge_messages`（自动识别共同前缀跳过重复、可选 dedup、返回 `mapping` 供下标重映射）；`SessionStore.merge_into(target, source)` 薄状态层：收藏下标按 mapping 重映射、tags 合并、来源会话不删除、target 置 current 并落库
- **📊 对话统计**：`message_content`（兼容多模态）、`estimate_tokens`（CJK 1 字/token、其余 4 字符/token）、`session_stats` / `overview_stats`、`format_stats_markdown`
- **PC UI**：命令面板新增「📊 对话统计洞察」「🔀 分支对比」「🧬 会话合并」；新建 `ui/insight_dialog.py`（QTextBrowser 渲染 Markdown，支持复制 / 另存 .md，`setMarkdown` 有 fallback）；`_pick_other_session` 统一选择非当前会话

### 反复优化：全量自测暴露的检索精度修复
- 首次跑全量 `selftest.py` 得 **776 通过 / 3 失败**；两处为 V11.3 起过时的硬编码断言（命令面板数写死 31、实际 43；「导出」搜索期望 1 条、V11.3 起因「批量导出全部会话」变成 2 条），已改为结构不变量断言（校验下限 + 关键命令齐备 / 命中集合包含 `export` 与 `export_all`）
- 第三处 `搜索无结果` 暴露 **V11.1 遗留真实缺陷**：`core/sessions.py::_tokenize` 把中文拆成单字，搜「不存在的关键词xyz」时标题里的「的」等高频虚词也会得分，无关会话被误召回
- 修复：`_tokenize` 改为按**连续 CJK 片段**切分（长度 ≥2 整段入 token + 片段内二元组，**丢弃单字**）；`search_ranked` 无有效 token 时返回 `[]` 而非 `self.list()`。「重命名」仍能命中「重命名后的会话」，虚词噪音消除
- 修复后 **780 通过 / 0 失败**；针对性回归 40/40、安卓逻辑 16/16 全绿
- 因 `core/sessions.py` 变更，APK / CLI / deb / Windows exe **全部重新构建**，5 个版本文件夹与 zip 一并重新生成，杜绝「源码已修、分发仍旧」的历史问题

### 测试与版本
- `test_v11_5_pc.py` **22/22 全绿**（diff 共同前缀/一致/无关/空/多模态/截断、merge 前缀/无关/显式前缀/dedup/无副作用、stats 单会话/全局/空/多模态、token 估算、Markdown 渲染、merge_into 收藏重映射/tags/非法/持久化、AST 校验零 GUI 依赖）
- 回归 V11.4 9/9、V11.3 4/4；语法编译、安卓 core 全量编译、Qt 无头对话框渲染均通过
- 版本号四处一致 **11.5.0**（`APP_VERSION` / `CLIENT_INFO.version` / `pyproject.toml` / selftest 断言）；每版独立带后缀版本文件夹 + zip 分发，历史大版本 v7.6–v11.4 全保留

## [11.4.0] - 2026-11-06

### 电脑端新增功能：消息引用（Quote）/ 分支对话（Branch）
- 全链路工作流：整体项目 + 打包 exe/各端 + 提交结构 → 代码安全性评估 → HR复审 → 美术复审 → 资深程序员复审 → GitHub复审 → 反复优化 → 创造力复审 → API开放文档；每版独立带后缀版本文件夹 + zip 分发，历史大版本 v7.6–v11.3 全保留
- **💬 消息引用**：`core.sessions.format_quote` 纯函数把历史消息格式化为 Markdown 引用块（过滤 system / 空内容、`QUOTE_MAX_CHARS` 截断、多行逐行 `>` 前缀、多模态取文本）；`build_quoted_prompt` 把引用块与追问拼成带上下文的 user 消息；`SessionStore.get_message` / `quote_block` 便捷接口
- **🌿 分支对话**：`SessionStore.branch_from(sid, index)` 从某条消息（含）处复制 `messages[:index+1]` 生成新会话（逐条浅拷贝、继承 tags、starred 按 `<= index` 过滤、记录 `branched_from={session_id,index}` 溯源、自动置为 current、越界/不存在返回 None）；`list_branches` 聚合派生分支摘要
- **PC UI 接入**：命令面板新增「💬 引用消息追问」「↩️ 引用最后回复」「🌿 分支对话」「🌱 分支列表」；新建 `ui/message_picker_dialog.py`（引用/分支两模式共用消息选择器）。打开选择器前先 `_save_current_session()` 建立一致索引基线，规避启动补 system 提示造成的下标偏移
- 全部逻辑落 `core/` 桌面安卓同源共用，零 Qt / 零安卓依赖；`core/sessions.py` 与 `android/core/sessions.py` 保持字节一致
- 测试：新增 `test_v11_4_pc.py` **9/9 全绿**（引用格式化/过滤/截断/多行/多模态、build_quoted_prompt 各分支、quote_block/get_message 越界、branch_from 复制前缀/元数据继承/深拷贝隔离/越界/持久化、list_branches 与旧数据向后兼容）；V11.3 回归 `test_v11_3_pc.py` 4/4 全绿
- 版本号四处一致 **11.4.0**（`APP_VERSION` / `CLIENT_INFO.version` / `pyproject.toml` / selftest 断言）；安卓 APK 干净重建为 11.4.0 并 v2/v3 签名
- 对应文档：`docs/代码安全性评估_v11_4.md`、`HR复审_v11_4.md`、`美术复审_v11_4.md`、`资深程序员复审_v11_4.md`、`GitHub复审_v11_4.md`、`创造力复审_v11_4.md`、`API开放文档_v11_4.md`、`评审纪要_v11_4.md`、`RELEASE_NOTES_v11_4.md`

## [11.3.0] - 2026-11-02

### 安卓闪退根治 + 流程优化
- **彻底根因修复**：定位到上一版 APK 的 `METADATA` 版本残留 `11.0.0`、构建链路复用了陈旧缓存 wheel，导致分发出去的安装包仍是未修复代码。本轮**干净重建**（清空 `build/`、`dist/` 与 venv 内陈旧 app wheel，改用系统 JDK17 `/usr/lib/jvm/java-17-openjdk-amd64`），重新产出 APK 并经 `apksigner`(v2+v3) 签名校验；核验新 APK 内 `pyc` 已无损坏的 `from toga.style import Column/Row` 导入、`direction` 用字符串、`_show_fatal_error` 兜底存在，且版本号升为 **11.3.0**
- 修复真实存在的 **`_do_turn` 异常处理器闭包 `NameError`**：`except` 变量在块结束后即被删除，原 `lambda: self._append_error("出错了：%s" % e)` 延迟执行会触发 `NameError`、崩坏「发送失败」错误显示；改为固化成局部变量 `err` 再传入
- **流程优化（不再静默闪退）**：`startup()` 初始化失败时不再 `re-raise` 杀进程，而是弹出最小「错误窗口 + logcat」便于自助排查；构造期与 `main_loop()` 均加崩溃兜底（`__main__.py`）；`self.main_window` 缺失时兜底新建，确保 App 永静默闪退

### 电脑端新增功能（纯逻辑，桌面/安卓共用 `core/`）
- **⭐ 消息收藏（Star）**：`SessionStore.toggle_star(sid, idx)` / `is_starred` / `list_starred()`，会话 `starred` 索引集持久化；桌面命令面板「⭐ 收藏最后回复」「📌 收藏夹」（收藏夹对话框双击跳转到所在会话）
- **📋 AI 会话总结**：纯函数 `build_summary_prompt(messages)` 构造总结提示词；桌面「📋 AI 总结当前会话」后台线程流式生成要点并 `set_summary()` 缓存到会话元数据
- **📦 批量导出全部会话**：`core.exporter.export_all_sessions(store, fmt)` 支持 `markdown/json/text/html` 合并导出与 `zip`（每会话独立 `.md` + `index.md`）；桌面「📦 批量导出全部会话」命令

### 测试与版本
- 新增 **`test_v11_3_pc.py`**（4/4 通过）：覆盖收藏切换/列表、摘要缓存、`build_summary_prompt`、批量导出五种格式
- 安卓无头 GTK 启动回归：单窗口、设置页切换、发送路径（含错误兜底）全绿；dist 仅保留可直接安装的签名 APK（移除不可直接安装的 AAB）
- 版本号四处一致 **11.3.0**（`APP_VERSION` / `CLIENT_INFO.version` / `pyproject.toml` / selftest 断言）

## [11.2.0] - 2026-11-02

### 功能更新：会话标签管理 + 消息编辑/删除 + PDF 导出（纯逻辑，桌面/安卓共用 `core/`）
- 新增 **会话标签（Tags）**：`SessionStore.set_tags()` 归一化标签（list / 逗号分隔字符串均可、去重、单会话上限 12 个）；`list_tags()` 聚合全部标签及计数；`list(tag=)` 与 `search_ranked(tag=)` 支持按标签过滤；每条会话摘要与检索结果均携带 `tags` 字段
- 新增 **消息编辑 / 删除**：`edit_message(sid, idx, content)` 修改某条消息（系统提示受保护、越界返回 False）；`delete_message(sid, idx)` 删除某条消息；桌面端新增「🗑 删除最后一条消息」（命令面板 + 托盘菜单），撤回刚发出/收到的内容并同步会话存储
- 新增 **PDF 导出**：`core/exporter.conversation_to_pdf()` 复用 HTML 版式由 WeasyPrint 渲染为 PDF 字节流；`EXPORT_FORMATS` 在环境支持时条件注册 `pdf`，`available_formats()` 供 UI 决定展示项；桌面「导出对话」对话框新增 PDF 选项（环境无 weasyprint 时自动隐藏）
- 桌面 **会话管理框增强**：新增标签筛选下拉（「全部标签」+ 各标签）与每行 🏷 标签编辑按钮；检索摘要行沿用既有 `MutedLabel` 样式，视觉一致
- 新增 **`test_v11_2.py`**（21/21 通过）：覆盖标签解析/过滤、消息编辑/删除保护、PDF 字节流与 HTML 一致性；安卓逻辑回归 **`test_app_logic.py` 14/14 仍全绿**
- 版本号四处一致 **11.2.0**（`APP_VERSION` / `CLIENT_INFO.version` / `pyproject.toml` / selftest 断言）

### 复审（V11.2 功能更新）
- 代码安全性评估：新增函数均为纯逻辑、无命令注入/路径穿越风险；PDF 依赖 guard 导入，缺失时明确报错而非静默失败
- 资深程序员复审：标签/编辑/删除零 Qt 依赖、可单测；UI 仅消费结果，回退兼容旧 `list/search` 返回结构（新增 tags 字段向后兼容）
- 美术复审：标签筛选下拉与 🏷 按钮沿用既有控件样式，检索摘要行未变
- HR / 创造力 / GitHub 复审：见 `docs/评审纪要_v11_2.md`

## [11.1.0] - 2026-11-01

### 功能更新：跨会话相关性检索 + 多格式导出（纯逻辑，桌面/安卓共用 `core/`）
- 新增 **`SessionStore.search_ranked()`**：中英文混合分词（英文整词 + 中文单字/二元组）、
  词频与标题加权排序，返回带 `score` 与 `snippet`（高亮摘要片段）的结果；旧 `search()` 委托之，
  桌面会话检索框自动获得相关性排序，并新增命中摘要行展示
- 新增 **`core/exporter` 多格式导出**：`conversation_to_json` / `conversation_to_text` /
  `conversation_to_html`（原仅有 Markdown），并新增统一入口 `export_conversation(fmt=...)` 与
  `EXPORT_FORMATS` 注册表；桌面「导出对话」对话框支持 Markdown / JSON / TXT / HTML 四选一，自动补扩展名
- 新增 **`test_search_export.py`**（5/5 通过）：覆盖空查询、相关性排序、中文二元组命中、四格式导出与 HTML 转义、多模态文本提取
- 安卓逻辑回归 **`test_app_logic.py` 14/14 仍全绿**（核心改动对移动端无破坏）
- 版本号四处一致 **11.1.0**（`APP_VERSION` / `CLIENT_INFO.version` / `pyproject.toml` / selftest 断言）

### 复审（V11.1 功能更新）
- 代码安全性评估：新增函数均为纯逻辑、无命令注入/路径穿越风险；HTML 导出已做转义
- 资深程序员复审：检索与导出零 Qt 依赖、可单测；UI 仅消费结果，回退兼容旧 `search()` 返回结构
- 美术复审：检索摘要行沿用 `MutedLabel` 样式，视觉一致
- HR / 创造力 / GitHub 复审：见 `docs/评审纪要_v11_1.md`

## [11.0.0] - 2026-10-31

### 重头戏：安卓 APK（开箱即用）+ UOS deb + GitHub Releases 式分发
- 新增 **`android/` BeeWare / Toga 原生安卓工程**：基于 `briefcase` → Gradle → `python-for-android`
  - **移植全部核心代码**：聊天 / 深度思考流 / 长期记忆 / 智能体工具 / 平台检测全部复用桌面版纯 Python `core/`，非另写伪实现
  - 安卓 `app.py` 仅约 300 行 Toga GUI 胶水；后台线程联网 + 事件循环线程安全回写（规避安卓主线程网络限制）
  - 思考可视化在移动端以「思考卡片 + 实时流式文字」还原桌面「液态玻璃悬浮球」
- 新增 **`.github/workflows/build-android.yml`**：推送 `v*` tag 即在 GitHub 运行器上**真实编译并签名 APK、自动发布到 Releases**，对标官方开源项目发版体验（开箱侧载安装）
- 新增 **`scripts/build_android_apk.sh`**：一键装 SDK/NDK 并构建 APK（本地等价流程）
- **UOS / Debian `.deb` 完整打包并验证**：命令行二进制 + `dpkg-deb` → `星语Starry-CLI-UOS.deb`（32MB，已 `dpkg-deb -I` 校验）
- 版本号四处一致 **11.0.0**（`APP_VERSION` / `CLIENT_INFO.version` / selftest 断言）

### 文档与评审
- 八份 V11.0 评审/API 文档：`代码安全性评估` / `HR复审` / `美术复审` / `资深程序员复审` / `GitHub复审` / `创造力复审` / `API开放文档` / `使用指南_Android_APK`
- 新增《使用指南_Android_APK.md》（侧载安装 + 配置 + 构建），更新《命令行使用指南.md》

### 工程与发布秩序
- 版本后缀文件夹自包含（`星语Starry-v11.0-*`：GUI / windows-cli / linux-cli / uos / android），每文件夹含完整源码 + 全部 md + 主文件 + README/CHANGELOG
- 历次大版本（V8.0 / V9.0 / V10.0）能力完整保留并随核心演进
- 自测全绿；桌面版与命令行版 PyInstaller 真实构建验证通过

## [10.0.0] - 2026-10-31

### 平台适配 + 无界面命令行（V10.0 重头戏）
- 新增 **`core/platforms.py`**：纯函数平台检测与版本后缀（Windows / Linux / 统信 UOS / Android(Termux) / macOS）
- 新增 **`core/cli.py` + `starry_cli.py`**：零 PyQt 依赖的无界面命令行引擎，复用桌面版 `ChatClient` 与 `AgentRuntime`
  - 支持 `-p/--prompt`、`-f/--file`、管道输入；`--agent` 智能体工具模式、`--json` 结构化输出、`--platform` 诊断
  - 复用 V8.0 长期记忆注入、V9.0 REA 预设并入（`--add-rea`）；网页接入型服务商被安全拒绝
- 新增 **`starry_cli.spec`**（console=True，剔除 PyQt5，产物远小于桌面版）+ 双 PyInstaller 配置
- 新增打包脚本：`scripts/build_windows_cli.ps1` / `build_linux_cli.sh` / `build_uos.sh`（.deb）/ `build_android.sh`（Termux+APK）
- 新增文档：《平台适配与命令行集成说明_v10_0.md》《命令行使用指南.md》+ 四份平台使用指南（UOS / Android_APK / Windows_CLI / Linux_CLI）
- 八份 V10.0 评审/API 文档（安全 / HR / 美术 / 资深 / GitHub / 创造力 / API / 提交指南）
- 自测 751 → **779 项**（+28 项平台检测 / CLI 引擎用例全绿）
- **PyInstaller 真实构建验证**：桌面版（starrystar.spec）+ 命令行版（starry_cli.spec）均通过
- 版本号四处一致 **10.0.0**

## [9.0.0] - 2026-10-31

### 最前端（新增）：外部学习工作流
- 真实下载 **WorkBuddy Linux 版**（v5.6.2，Electron+Chromium）并解包调研，记录创新点
- 用 GitHub 爆火项目 **REA（Reverse Engineer Anything, MIT）** 复刻逆向能力，写入本项目
- 检索热门项目（Cherry Studio V2 / LobeChat / Open WebUI / Jan / LM Studio / AnythingLLM）学习创新功能
- 调研归档：`docs/创新功能调研_v9_0.md`

### 新功能：🌀 深度思考可视化升级
- 悬浮球 THINKING 态新增「液态玻璃折射 + 微光扫掠」覆盖层（`ui/floating_ball.py:_paint_glass_overlay`）
- 球上方「液态玻璃字幕卡 + 微光」实时呈现思考片段（`ThinkingCaption` / `show_thinking_text`），思考过程可见、可缩小成悬浮球形态

### 新功能：🔍 REA 逆向工程集成（core/rea.py）
- REA 的 MCP 预设（`enabled=False` / `trusted=False` 默认关闭）、分析目标清单、证据驱动提示构造、按 name 去重并入
- 设置页 MCP 区「添加 REA 预设」一键接入；命令面板 `rea` 入口；底层引擎（Ghidra/IDA）用户自备，与 REA 设计一致

### 新功能：🧪 产物预览 Artifacts
- 聊天窗 🧪 按钮 + 命令面板 `artifacts`：提取最近回复的 ```html 块，落地临时文件后用浏览器预览（对齐 Cherry Studio / LobeChat / Open WebUI）

### 质量与工程
- 自测 727 → **751 项**（+24 项 REA / 思考字幕 / 产物提取用例，全绿）
- `starrystar.spec` 补隐藏导入 `core.rea`
- 八份评审/API/调研文档（`docs/*_v9_0.md`）；版本号四处一致 9.0.0
- PyInstaller 真实构建验证通过（同 spec Windows 即产 `星语Starry.exe`）

## [8.0.0] - 2026-10-30

### 最前端：整体项目 + 打包成 exe + 代码结构方便提交
- 新增 `docs/项目结构与提交指南_v8_0.md`：V8.0 模块增量 + 提交清单 + **每版独立版本化文件夹约定**（`星语Starry-vX.Y.Z/`，自包含、可独立构建/打包，并附同名 zip）
- `starrystar.spec` 显式声明新增隐藏导入 `core.memory` / `core.reasoning` / `ui.memory_dialog`

### 新功能：🧠 长期记忆系统（core/memory.py）
- 跨会话持久化「用户画像 / 偏好 / 事实 / 项目背景」，落盘 `memory.json` 权限 `0o600`
- 写入前**提示注入护栏** `is_safe_entry`：拒空 / 超长(>240) / HTML 标签 / `ignore previous instructions` 类指令诱导；去重 + 容量上限 300
- 对话结束后启发式学习（仅用户侧白名单句式），按相关性 `relevant()` 召回并 `build_memory_block()` 注入系统提示
- `ui/memory_dialog.py` 记忆管理对话框：分类查看 / 逐条「忘记」/ 清空 / 一键开关；标题栏 🧠 按钮带实时计数角标
- 新增 `ui.chat_window.memory_requested` 信号与 `set_memory_count()`

### 新功能：🧩 深度思考（推理）引擎（core/reasoning.py）
- `split_think_content` 一次性解析 + `StreamingThinkSplitter` 流式分片，统一分离 `<think>…</think>` 思考与正文
- `ReasoningTrace` 思考轨迹累积与截断摘要；接入 `app/assistant._on_content`，思考增量进气泡折叠块、流结束 `flush()` 收尾

### 工作流（安全 → HR → 美术 → 资深 → GitHub → 反复优化 → 创造力 → API 文档）
- 代码安全性评估 v8.0（评级 B+）：S1–S5 维持；新增 S6 记忆提示注入护栏 + 0o600 记忆落盘 + 学习来源收敛 + 推理无执行面
- HR 复审 v8.0（评级 A）：认可「关系化留存」商业价值
- 美术复审 v8.0（评级 A-）：新增元素全落既有设计系统
- 资深程序员评审响应 v8.0（评级 A）：修复 3 个真实 bug（思考解析反转 / list 类型 / 中文分词）并写回归
- GitHub 复审 v8.0（评级 B+）：开源基建齐备 + 版本化分发净加分
- 创造力复审评价 v8.0（9.2/10）：记忆关系化 + 思考可视化
- 自测 693 → **727 项**（新增 V8.0 记忆 / 推理用例 34 项，全绿）

## [7.6.0] - 2026-10-28

### 最前端：整体项目 + 打包成 exe + 代码结构方便提交
- 补齐开源治理：`CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` / `docs/项目结构与提交指南_v7_6.md`
- 打包验证：`starrystar.spec` 经 PyInstaller 真实构建（Linux 产出 134MB 单文件，入口 / 隐藏导入 / PyQt5 收集全通过），同一 spec 在 Windows 经 `scripts/build_windows.ps1` 产出 `星语Starry.exe`
- 新增 `docs/API开放文档_v7_6.md`：MCP 接入契约、`register_tool` 扩展点、自动化规则、网关 / 多站点、配置合规、构建打包六类对外接口
- `.gitignore` 加固：新增 `.env` / `.env.*` / `*.key` / `*.pem` / `secrets.json` / `credentials.json`

### 工作流（安全 → HR → 美术 → 资深 → GitHub → 反复优化 → 创造力 → API 文档）
- 代码安全性评估 v7.6：S1–S5 回归维持；提交结构 / 打包 / API 文档在密钥隔离、构建产物隔离、隐藏导入完整性、文档无泄露四维实证
- HR 复审 v7.6（评级 A）：认可「从能跑到能交」的跨越
- 美术复审 v7.6（评级 A-）：视觉体系稳，建议安装包图标 / 欢迎页纳入 v7.7 美术验收
- 资深程序员评审响应 v7.6：前轮必办项（MCP 护栏 / 毛玻璃厚度 / CONTRIBUTING）全部闭环；坦白 Windows .exe 未在真机跑、许可仍客户端校验
- GitHub 复审 v7.6（评级 B+）：开源基建六项齐备，差 Release 自动签名临门一脚
- 创造力复审评价 v7.6（9.0/10）：整合力 + 诚实交付 + 方法论沉淀
- 自测 666 → **693 项**（新增提交就绪 27 项）

## [7.5.0] - 2026-10-27

### 工作流（最前端加代码安全性评估，再走复审 → 反复优化）
按用户要求，本轮工作流顺序为：**代码安全性评估 → HR复审 → 美术复审 →
资深程序员复审 → GitHub复审 → 再次反复优化**。五份评审文档归档于 `docs/`：
`代码安全性评估_v7_5.md`、`HR复审_v7_5.md`、`美术复审_v7_5.md`、
`资深程序员评审响应_v7_5.md`、`GitHub复审_v7_5.md`。

### 安全（🛡 代码安全性评估落地，全为真实代码 + 自测覆盖）
- **EULA 防篡改令牌**：接受时写入 `sha256(EULA正文 + APP_VERSION)`，
  主程序门禁改为「布尔位 + 令牌匹配」；直编 `config.json` 已无法绕过许可。
- **许可密钥离线校验**：`validate_license_key` 确定性校验位
  （`XXXX-XXXX-XXXX-XXXX`，末 4 位为 `sha256(盐+前12位)[:4]`），伪造串被拒；
  关于页授权卡改为可编辑 + 即时校验（未填写·试用版 / 已验证正版 / 格式无效）。
- **配置权限收敛**：`config.json` 落盘后 posix 平台 `chmod 0o600`。
- **MCP 启动命令校验**：启动前 `shutil.which` 前置校验，失败早返回清晰错误；
  明确列表式 `Popen`（无 `shell=True`）**无命令注入面**。

### 新增 —— MCP 危险工具动作护栏（🔒，资深程序员复审「下轮必办」闭环）
- `classify_destructive` 词元级识别写/执行类工具（`delete/rm/write/exec/run…`）；
- `McpManager(confirm_cb=...)`：非信任服务器的危险工具默认**拒绝执行**并返回提示，
  仅 `trusted=True` 或会话内批准才放行；设置页 MCP 标签页新增「信任此服务器」勾选。

### 视觉（🪟 美术复审）
- `FrostGlass` 新增**底部内阴影**，玻璃更显浮起、有厚度（液态玻璃关键细节）。

### 工程
- `APP_VERSION` 7.4.0 → **7.5.0**，自测断言同步更新。
- 自测 **666 项**全绿（v7.4 的 645 项 + 21 项：防篡改令牌 / 密钥校验 /
  配置 0o600 / MCP 命令校验 / 危险工具护栏端到端 / 玻璃厚度等），`pyflakes` exit=0。
- 依赖零增长（v7.3–v7.5 三轮未引入任何新第三方依赖）。

## [7.3.0] - 2026-10-27

### 前置：GitHub 开发者视角代码评审（docs/代码评审_v7_3.md）
以「假设自己是接手这个仓库的 GitHub 开发者」身份复审 v7.2，按 P0–P3 严重度
给出带 `文件:行号` 证据的定位与修复方案；本轮实现覆盖 P0-1（版本号
`APP_VERSION` 与文档口径不一致）、P0-2（缺企业商用 EULA / LICENSE）、
P1-1（伪玻璃：仅 alpha 填充、无背景虚化）、P1-2（动画句柄泄漏：重触发不停止旧
动画）、P1-3（常驻计时器隐藏时仍空转重绘）、P2-1/P2-2/P2-3（硬编码字体 / 圆角偏小
/ 关于页插件卡无样式）及 P3 杂项。

### 新增 —— 真·毛玻璃（Frosted Glass）
- `ui/frost.py`：`FrostGlass(QFrame)`——对窗口背后桌面做 5× 降采样 + 高斯模糊
  （PIL），再叠加主题色染色 / 顶部高光 / 1px 亮边 / 环境光晕，得到真正磨砂透视质感。
- 聊天窗主容器、划词迷你窗、关于页、EULA 对话框全部换用 `FrostGlass`
  （替换原液态玻璃伪玻璃）。
- offscreen / 合成器不可用环境自动降级为渐变伪玻璃，保证可移植与自测确定性。

### 新增 —— 资深级开屏动效
- 多层视差星尘（46 颗，近大远小、不同漂移速度）+ 极光弥散团 + 暗角聚焦。
- 三珠旋转 → 螺旋汇聚 + 星尘迸发 → 融合液态玻璃球；✦ 标志配多层 bloom 光晕与
  高光弧扫过。
- 标题**逐字 kinetic 上升淡入** + 流光扫过；副标题渐显。
- 全程底部**微光进度条** + 循环状态微文案；点击任意处可跳过；时长 3s。

### 新增 —— 企业商用合规
- 首启 **EULA 许可协议**门：`Accept` 写入 `accepted_eula` 持久化；
  `Reject` 直接 `sys.exit(0)`（`ui/eula_dialog.py` + `main.py` 最前端）。
- 仓库根 **LICENSE** 改为商业软件许可协议（源码沿用 MIT，二进制分发与商用需授权）。
- 关于页新增**商业授权卡**（商业授权说明 / 许可密钥字段 / 版权 / 条款入口）。
- `core/config.py` 新增 `accepted_eula` 与 `license_key` 默认值。

### 优化 —— 视觉与动效令牌
- 圆角加大为 `RADIUS_S/M/L = 10/14/20px`（原 8/12/16），更柔的现代玻璃感。
- 动画句柄复用：重触发时先 `stop()` 旧 `QVariantAnimation` 再建新，消除重叠竞争
  （`LiquidGlass` / `MetricRing` / `NumberRoll` / `Sparkline`）。
- 常驻计时器（球三态 / 脉冲）隐藏时 `isVisible()` 早退，杜绝空转 CPU。

### 修复
- `APP_VERSION` 3.0.0 → **7.3.0**，与文档口径一致。
- 开屏 `QColor` 混用 hex 串 / RGB 元组导致的类型错误（品牌色令牌统一走
  `QColor(str)` 构造），进度条 `fillRect` 缺 brush 参数修正。

### 质量
- 自测 **618 项**全绿（v7.2 的 600 项 + 18 项 v7.3 覆盖：圆角令牌 / 版本号 /
  毛玻璃构造绘制 / 动画句柄复用 / 聊天窗与划词窗毛玻璃 / 开屏逐字标题与进度条 /
  EULA 默认未同意 / EULA 接受持久化 / EULA 拒绝信号 / 关于页商业授权卡）。
- `starrystar.spec` 显式补充 `ui.frost`、`ui.eula_dialog` 懒加载声明。
- 评审文档 `docs/代码评审_v7_3.md` 归档。

## [7.4.0] - 2026-10-27

### 前置：GitHub 开源检索与补齐决策（docs/GitHub开源调研_v7_4.md）
检索 Moonwalker / Jini / TARS / DesktopAI / OpenClaw（393K★）/ Cherry Studio
（52.9K★）/ Jan.ai / AnythingLLM / Open Interpreter 等，读出五条趋势：
**MCP 成为工具生态事实标准** · **屏幕感知（Screen-aware）是新秀统一入口** ·
玻璃拟态已是及格线 · 语音正在本地化 · 动作护栏被认真对待。据此决定：
补 MCP、补看屏幕问答；**明确不做本地语音唤醒**（百 MB 级依赖，与 v7.2
轻量化方针冲突），理由写入调研文档。

### 新增 —— MCP 工具生态（🔌）
- `core/mcp.py`（450 行）：stdio 传输的 JSON-RPC 2.0 客户端
  （`initialize` → `tools/list` → `tools/call`），**纯标准库实现，零新依赖**。
- `McpManager`：批量连接、把外部工具以 `mcp_*` 注册进 `core.agent.tools`
  （自动出现在 OpenAI tools 清单）、状态视图、退出时断开并卸载。
- 设置页新增「MCP 工具」标签页：名称 / 启动命令 / 参数 / 启用 /
  **测试连接**（真实握手并列出工具名）。
- 启动零开销：`mcp_servers` 默认为 `[]`；已配置时延迟 1.2s 后台线程握手，
  主线程轮询收尾，不阻塞启动。退出时 `stop_all()` 断开子进程。

### 新增 —— 一键看屏幕问答（👁）
- `core/screen.py`（52 行纯函数）+ `ScreenshotController.capture_screen()`：
  一键抓全屏 → 生成图片附件 → 可填入预设问题（解释 / 翻译 / 诊断报错 / 总结）。
- 命令面板新增「👁 看屏幕问答」主命令 + 4 条预设（共 24 → 29 条命令）。

### 修复 / 一致性
- `APP_VERSION` 7.3.0 → **7.4.0**，自测断言同步更新（延续 v7.3 的 P0-1 纪律）。
- 命令面板计数断言 24 → 29。

### 质量
- 自测 **645 项**全绿（v7.3 的 618 项 + 27 项：MCP 纯函数 7 / MCP 端到端 5
  （真实起子进程走完 JSON-RPC 往返）/ 注册执行卸载 5 / 看屏幕纯逻辑 9 /
  命令计数 1）。
- pyflakes 对全部改动文件 exit=0。
- `starrystar.spec` 显式补充 `core.mcp`、`core.screen` 声明。

### 复审闭环
- `docs/资深程序员评审响应_v7_4.md`（含五条坦白清单：仅 stdio 传输 /
  中文名折叠潜在 id 冲突 / 测试连接同步阻塞 8s / Wayland 抓屏受限 /
  **MCP 工具缺少动作护栏**）。
- `docs/HR复审_v7_4.md`：评级 **A（独立闭环交付）**，关注点为安全护栏需提前半步。
- `docs/创造力复审评价_v7_4.md`：综合 **9.0/10（A：有判断力的创造）**。

## [7.2.0] - 2026-10-26

### 前置：竞品调研（docs/竞品调研_v7_2.md）
调研 Open WebUI 154k★ / AnythingLLM 66k★ / Cherry Studio 52k★ / LibreChat 45k★ /
Jan / Chatbox / Clippy（2026 新）/ AI Desktop Pet 等，结论：
「网页版免 Key + 网关观测 + 多专家会诊」为独占组合；
「划词提问、桌面拟人化、单文件轻量」是竞品验证过的高频体验，本轮补齐。

### 新增 —— 划词提问（Selection Assistant）
- `core/quickask.py`：6 个动作（解释/翻译/总结/润色/挑错/行动项）+ 文本清洗
  （压缩空行、6000 字截断）+ 提示词合成（支持目标语言与补充要求），全部纯函数。
- `ui/quick_ask.py`：液态玻璃迷你窗——预览选中内容、动作网格、目标语言、
  补充要求输入；代码片段自动把「挑错」设为强调动作。
- 全局热键 **Ctrl+Shift+Q**（独立于唤起热键，可配置）；命令面板新增「划词提问」。
- 选区读取：Linux/X11 优先鼠标选区，其余平台读剪贴板；空内容明确提示。

### 新增 —— 桌面拟人化（漫游 + 提示气泡）
- 悬浮球**待机漫游**：闲置 8s 后开始，约 11s 一次，朝附近随机点缓动漂移并带
  弹簧微浮动；用户一有动作立即停止（不抢注意力），可在命令面板开关并持久化。
- **随机提示气泡**：闲置 22s 后冒第一句、之后每 26s 一句；内容按时段问候 +
  功能提示 + 趣句混合，避免近期重复；淡入淡出、随球体定位、超时自动消失、
  不抢鼠标事件。
- `core/idle_tips.py`：提示语库与 `pick_tip(hour, history)` 纯函数（确定性可测）。

### 优化 —— 轻量化（代码更小、产物体积更可控）
- `starrystar.spec` 排除 15 个未使用 Qt 模块
  （WebEngine / Qml / Quick / 3D / Multimedia / Sql / Bluetooth / Svg 等）。
- 4 个存储类（会话/统计/资料库/自动化）重复的原子写入 `save()` 抽为
  `core/storage.py`（`save_json` / `load_json`），一份实现。
- 新增功能全部落在小而集中的模块，未向大文件堆代码。

### 修复
- 退出路径补全：`quit()` 现在会停止划词热键、关闭迷你窗与提示气泡
  （此前只停主热键，偶发线程残留）。
- 自测稳定性：注册真实全局热键导致的
  「QThread: Destroyed while thread is still running」（SIGABRT 134）
  —— 自测内隔离热键注册，并在输出后显式 `os._exit`，连续三次 600/0 稳定。
- 迷你窗与气泡的 emoji 字形/文字截断问题（纯中文按钮 + 气泡自适应换行）。

### 质量
- 自测 **600 项**全绿（v7.1 的 558 项 + 42 项 v7.2 覆盖：划词纯逻辑 13 /
  迷你窗交互 3 / 提示语 6 / 漫游与气泡 10 / 主控制器接线 3 / 存储去重 9）。
- 截图：v7.2 三张（划词窗 / 提示气泡 / 漫游态）目检通过。
- Xvfb 真实环境冒烟 5/5；pyflakes exit=0。
- 本地 PyInstaller 实测：Linux 单文件 **134MB**，进程启动 12s 存活无报错。

## [7.1.0] - 2026-10-25

### 新增 —— 动效增强（视觉细节再上一个台阶）
- **液态玻璃光泽扫过（sheen）**：`LiquidGlass` 新增 sheen 属性与
  `animate_sheen()`——hover / 点击玻璃卡片时一道斜向高光带从左下
  扫到右上（深色 44 / 浅色 62 alpha），旗舰玻璃的「手感」来源。
- **悬浮球待机极光弧**：一道锥形渐变弧环绕球体缓慢旋转
  （particle_mid / particle_bright 双色带），待机态也有生命感。
- **输出态均衡器峰值帽**：新增纯函数 `peak_hold(cur, level, dt)`
  （瞬时上冲 8.0/s、缓慢下落 1.1/s）——音频表标志性语言，三轨各一
  颗缓落小白点；非输出态平滑归零。
- **思考态反向细弧**：旋转弧之外加一道反向慢速细弧（双引擎感）。
- **圆环流星尾**：`MetricRing` 进度弧头部新增白核 + 主题色晕光点。
- **背景微光粒子**：`GlowOrb` 新增 9 颗上浮微粒（摇曳 + 边缘渐隐）。
- **折线末端脉冲**：`Sparkline` 末端点双层呼吸光圈（200ms 轻量时钟，
  仅绘制完成后刷新）。
- **开屏星尘迸发**：三珠合并瞬间 12 粒微粒沿径向飞出渐隐。

### 新增 —— 生产链：CI 一键打包 Windows exe
- `.github/workflows/ci.yml` 新增 `build-windows` job
  （windows-latest，needs: test）：
  复用 `scripts/build_windows.ps1`（本地与 CI 同一命令、幂等）——
  venv → 依赖（含可选依赖，exe 开箱即用 TTS/热键/网页版 driver）
  → 品牌图标 → PyInstaller 单文件打包；
- exe 启动冒烟（8s 进程存活 / 退出码校验）+ `upload-artifact@v4`
  上传 `starry-windows-exe`（exe + README + 可选依赖清单，
  保留 14 天）；
- `starrystar.spec` 显式登记 v7 新增的 `core.web_sites`；
- 本地（Linux）已按 spec 实跑 PyInstaller 验证打包链路
  （需 --enable-shared 的 Python，见 README 构建说明）。

### 质量
- 自测 **558 项**全绿（v7.0 的 536 项 + 22 项 v7.1 覆盖：
  sheen 状态机 / 微粒 / 流星尾绘制 / 峰值保持纯函数四场景 /
  三态强制绘制 / 星尘绘制 / spec 登记）。
- v7.1 动效截图 4 张（光泽扫过 / 极光弧 / 峰值帽 / 星尘）目检通过。
- Xvfb 真实环境冒烟 5/5；pyflakes 门禁 exit=0。

## [7.0.0] - 2026-10-24

### 新增 —— 多站点网页接入（马具工厂）
- `core/web_sites.py`：网页站点注册表，当前收录 **DeepSeek（官方维护）**、
  **智谱清言 chatglm.cn（社区维护）**、**豆包 doubao.com（社区维护）** 三站。
  每站含 URL / 模型列表 / 9 键选择器 / 独立 profile 目录。
- 客户端类按站点动态生成并缓存（`_client_class`），配置段
  `web_zhipu` / `web_doubao` 独立管理无头模式、超时、profile 与选择器。
- 设置 → 网页接入页新增**站点下拉框**（社区维护站点带标注），命令面板新增
  「登录智谱清言网页版」「登录豆包网页版」入口（命令面板扩至 22 个）。
- 服务商总数 **19 → 21 家**。

### 新增 —— 选择器覆盖编辑器（不再手改 config.json）
- 设置 → 网页接入页为每站提供 **9 键选择器编辑器**（输入框 / 发送按钮 /
  回答块 / 回答文本 / 思考区 / 停止按钮 / 新建对话 / 已登录 / 未登录），
  每键一个输入框，留空即用默认值（placeholder 显示默认选择器），
  中英文逗号均可分隔多候选。
- 一键「恢复默认」；覆盖为**整体替换该键**，站点改版后产品内即可修复。

### 新增 —— 网关每日 Token 预算告警
- 每家服务商可设每日 token 预算（`~/.starry/gateway_budgets.json` 持久化），
  仪表盘按 24h 窗口汇总今日用量，三档状态：ok（<80%）/ ⚠ warn（≥80%）/
  ⛔ over（≥100%），详情区彩色进度条 + 服务商卡片角标同步显示。
- **旁路设计**：仅统计与提示，绝不拦截主对话链路。

### 优化 —— 网关健康检查并行化（HR v6 复审遗留 O-1）
- `check_providers_parallel`：ThreadPoolExecutor 8 并发探活，
  19 家 × 4s 超时的串行最坏 76s → 约 12s；逐完成回调实时刷新进度，
  可随时中止（关闭窗口即停）。

### 优化 —— 一键安装内核适配 venv / conda（坦白清单第 3 条）
- `install_chromium(install_playwright=None)` 两阶段自足安装：
  自动判断当前环境是否已装 playwright 包，缺包时先
  `sys.executable -m pip install playwright` 再
  `sys.executable -m playwright install chromium`——两步均跟随当前解释器，
  venv / conda 环境天然适配。

### 优化 —— GitHub Actions 三平台 CI（HR v6 复审遗留 O-3）
- `.github/workflows/ci.yml`：test job 跨 ubuntu / macos / windows
  三平台矩阵（pyflakes 门禁 + offscreen 全量自测）；
  browser-e2e job（仅 ubuntu）真实 Playwright 端到端 12 项。
- 新增 PR 模板 / Issue 模板（bug + feature）/ SECURITY.md，
  开源协作基础件齐备。
- ⚠ 状态说明：静态门禁命令已在沙箱按 CI 原命令验证全绿
  （含修复 pyflakes `--count` 误用与两处 F401）；
  三平台真机（windows / macos / ubuntu runner）尚未触发，
  首次 push 后需观察结果并按需修整。

### 评审闭环修复 —— HR v7 五条问题 + 静态门禁（交付前）
- **社区站点标注**（P0-1）：设置页站点下拉与状态行、README 站点表均标注
  「社区维护 · 未经真机验证」，并给出选择器编辑器修复 / Issues 反馈路径。
- **预算口径与语义**（P1-1/P1-2）：仪表盘预算行明示「仅统计本助手请求 ·
  本地估算值」「超支不会拦截对话，仅作提醒」，输入框 tooltip 同步口径。
- **CI 静态门禁两处修复**（P2-1 暴露的真实缺陷）：`core/hotkey.py` 的
  pynput 探测改用 `importlib.util.find_spec`（消除「imported but unused」）；
  `core/agent/tools.py` 的注册导入显式收集引用；`ci.yml` 的
  `pyflakes . --count` 改为 `pyflakes .`（pyflakes 无 --count 参数，
  原命令会直接报错退出）——门禁现已在沙箱按 CI 原命令验证全绿。
- **液态玻璃竞态防御**：仪表盘卡片级联 glow 动画的 `QTimer.singleShot`
  在对话框删除后触发会对已销毁 C++ 对象创建 QVariantAnimation，
  PyQt 未捕获即 abort（自测 SIGABRT 134）；`liquid._val_anim` 与卡片
  lambda 双重防御，连续两次全量自测稳定通过。

### 质量
- 自测 **536 项**全绿（v6 的 463 项 + 73 项 V7 覆盖：并行检查 / 预算三档 /
  多站点注册与工厂 / 选择器编辑器全流程 / venv 安装三场景 / CI 文件合法性 /
  命令面板新增项 / HR v7 五条闭环回归 / 静态门禁与竞态修复回归）。
- v7 截图 2 张（网关预算告警 / 多站点选择器编辑器），目检通过。
- 三轮评审闭环：HR 评估 → 程序员响应 → HR 复审（结论 GA）。

## [6.1.0] - 2026-10-23

### 修复 —— HR v6 评审五条问题闭环
- 设置 → 网页接入页新增「⬇ 一键安装浏览器内核」按钮：产品内执行
  `playwright install chromium`，安装输出实时显示（P0-1）。
- 网关仪表盘健康检查显示实时进度（「🩺 检查中 n/18…」），单家超时
  6s → 4s，消除最坏情况的「假死」感知（P1-1）。
- 网页版服务商卡片副标题改为「浏览器接入 · 登录态持久化 · 免 API Key」，
  不再显示「0 个 Key」这类自我拆台的计数（P1-2）。
- PyInstaller spec 收集 Playwright node driver（368 个文件），
  README 明示安装包边界（P2-1）。
- 切换到网页版时立即探测环境，未就绪明确提示且不阻断切换（P2-2）。

### 优化
- 全项目 pyflakes 清零（修复 `core/modelscope.py` 下载前取消会抛
  `NameError` 的真实缺陷，清理 30 余处无用导入/死变量）。
- README 与代码一致性核对：19 家服务商 / 463 项自测 / 20 个命令面板命令。
- `verify_v6_browser.py` 与 `fixture_deepseek.html` 随项目分发，
  路径改为相对定位，任意目录可直接运行。

### 质量
- 自测 **463 项**全绿（新增 13 项对应五条修复回归）。
- 浏览器端到端 12/12；Xvfb 真实环境冒烟 5/5。
- 三轮评审闭环：HR 评估 → 程序员响应 → HR 复审（结论 GA）。

## [6.0.0] - 2026-10-23

### 新增 —— 网页版接入（浏览器 Harness）
- **DeepSeek 网页版接入**：通过 Playwright 驱动真实浏览器打开 chat.deepseek.com，
  像人一样输入问题、点击发送、盯着回答逐字出现，把网页版「套上马具」包装成
  与 API 完全一致的流式客户端。无需 API Key，网页版免费额度 / R1 深度思考 /
  联网搜索均可使用；登录态随浏览器 profile 持久化，一次登录长期有效。
- `core/browser_llm.py`：通用浏览器 harness（线程亲和会话管理、登录态检测、
  多重备选选择器、流式增量抓取、随时停止、登录引导）。
- `core/web_deepseek.py`：DeepSeek 站点适配器（选择器按站点优先级定制）。
- 设置 → 「网页接入」页：环境就绪度检测、一键登录引导、无头模式、超时配置。
- 选择器可在配置中整体覆盖，站点改版后无需升级即可修复。

### 新增 —— 网关仪表盘（Gateway Dashboard）
- `core/gateway.py`：请求统计（服务商/模型/耗时/token/成败，分钟级时序）、
  密钥池（多 Key 轮询 + 失败退避冻结）、健康检查、路由策略
  （自动 / 最低延迟 / 手动指定）。
- `ui/gateway_dialog.py`：液态玻璃旗舰界面——全局指标环、服务商通道卡片、
  60 分钟延迟折线、密钥池管理、实时请求日志流。
- 每次对话请求旁路记录统计（绝不影响主链路，失败静默降级）。

### 新增 —— 液态玻璃视觉语言
- `ui/liquid.py`：LiquidGlass 玻璃面板 / LiquidCard 交互卡片 / GlowOrb 流动光斑 /
  StatusDot 呼吸状态灯 / MetricRing 圆环指标 / Sparkline 时序折线 /
  NumberRoll 数字滚动。纯 QPainter 自绘 + QVariantAnimation，四主题全适配。

### 优化
- 服务商列表新增「DeepSeek 网页版（浏览器接入）」。
- 路由策略 fastest / manual 在下次请求时自动切换服务商并提示。
- 网页版模式自动禁用工具调用（网页版无函数调用能力），降级为普通对话。
- 退出时自动关闭浏览器 harness。

### 质量
- 自测扩充至 **450 项**（新增 73 项 v6 覆盖：浏览器全链路 fixture 验证 /
  网关统计与密钥池 / 液态玻璃组件 / 仪表盘交互 / 主控制器接线）。
- `verify_v6_browser.py`：12 项浏览器端到端验证（本地 fixture 页模拟
  DeepSeek DOM，真实 Playwright 链路）全部通过。

## [5.1.0] - 2026-10-23

### 新增
- 天蓝主体风格（light/sky/dark/sky_dark 四主题）。
- 阿里魔塔 ModelScope 模型市场（GGUF 下载 / llama.cpp 托管 / 分卷提示）。
- 细分参数：思考强度（8 家服务商下发 reasoning.effort）、上下文大小
  （CJK 感知估算 + 状态栏实时用量）、模型级参数覆盖。
- 创新功能：命令面板（Ctrl+K，18 条命令）、TTS 语音朗读、对话分支（①②③）、
  资料库引用角标。
- 三平台一键打包脚本 + PyInstaller spec（33 个懒加载模块显式登记）。

## [5.0.0] - 2026-10-22

### 新增
- 云端 API 多服务商接入（20+ 家，含免费额度服务商）。
- 智能体框架（技能 + 插件市场 + 11 个内置工具）。
- 液态玻璃开屏动画、新手引导、保留配置、竞品对比功能。

## [4.0.0] - 2026-10-20

### 新增
- 悬浮球主界面、文件/图片/截图上传、免费模型自动更新、本地模型自动适配。

## [3.0.0] - 2026-10-19

### 新增
- WorkBuddy 式功能复刻：多会话、提示词库、用量统计、全局热键、Markdown 导出。

## [2.0.0] - 2026-10-18

### 新增
- 更酷炫动画、DeepSeek 桌面版风格界面、豆包式小悬浮窗。

## [1.0.0] - 2026-10-17

### 新增
- 首个可用版本：Python 本地桌面 AI 助手，免费 API 接入、模型切换、
  思考过程实时呈现、Markdown 转富文本。
