# 发布说明 · 星语 Starry v11.5.0

**发布日期**：2026-11-07
**版本主题**：**Windows 真 `.exe` 闭环** ＋ **对话洞察三件套**（分支对比 / 会话合并 / 统计）
**上一版本**：v11.4.0（消息引用 / 分支对话）

---

## 一、为什么有这个版本

整条指令链里「**打包成点 exe**」是唯一一个横跨 v7.6–v11.4、每轮都被
「本机无 Wine，仅提供 `.ps1` 脚本」跳过的硬缺口。v11.5 把它作为攻坚主线，
不再停留在脚本，而是**真正交付可运行的 Windows 可执行文件**，并接入
GitHub Releases 自动发布。同时按「电脑端增加更多新功能」的持续诉求，
顺着 v11.4 的「分支对话」继续深化出三组洞察能力。

## 二、攻坚主线：Windows 真 EXE

| 交付 | 内容 |
|---|---|
| **真 exe** | 本机 Wine（`wine64` + Windows Python 3.11 embeddable + PyInstaller 6.22.3）编译出 `星语Starry-CLI.exe`，**PE32+ console x86-64，12MB**，随版本文件夹分发 |
| **CI 自动发版** | 新增 `.github/workflows/build-windows.yml`：推 `v*` tag → `windows-latest` 打包 → `--version`/`--platform` 自检 → Artifact → **追加到 Releases**；一个 tag 同时产出 APK + EXE |
| **本地一键** | `scripts/build_windows_cli.ps1` 改为幂等 venv + 版本打印 + 自检校验退出码 + 随包文档 |
| **使用指南** | 新增 `docs/Windows_EXE_构建指南.md`（三种构建方式、Wine 踩坑、验证清单、FAQ） |

### 实测修复：Windows 中文控制台秒退

首次 Wine 冒烟**真实复现崩溃**：

```
UnicodeEncodeError: 'charmap' codec can't encode characters ...
  File "core\cli.py", line 144, in _emit
  File "encodings\cp1252.py", line 19, in encode
```

英文代码页 cp1252 无法编码中文，`out.write()` 抛异常使 exe 退出。双层兜底：

1. `starry_cli.py` 入口 `sys.stdout/stderr.reconfigure(errors="replace")`；
2. `core/cli.py::_emit` 捕获 `UnicodeEncodeError` → 按目标流编码 `replace` 重写 → 最后退 ASCII。

验证结果（Wine 实测）：UTF-8 控制台与**默认 cp1252 控制台**下
`--version` / `--platform` **退出码均为 0**；中文 Windows 的 GBK 控制台
可正常显示中文，纯英文代码页退化为 `?` 但绝不崩溃。桌面 / 安卓
`core/cli.py` 同源同步，Linux CLI 与 deb 同样受益。

> Wine 侧踩坑：直接 `wine64 python.exe script.py` 会报
> `Fatal Python error: init_sys_streams ... [WinError 6] Invalid handle`；
> 必须走 `wine64 cmd /c C:\xxx.bat` 由 cmd 提供真实控制台。已写入构建指南。

## 三、电脑端新功能：对话洞察三件套

纯逻辑全部落在新建的 **`core/insights.py`**（零 GUI 框架依赖、不 import
sessions 避免循环依赖、绝不修改入参），桌面与 `android/core/insights.py`
**字节一致**。

| 功能 | 接口 | 命令面板 |
|---|---|---|
| 🔀 分支对比 | `diff_sessions` / `common_prefix_len` / `format_diff_markdown` | 「🔀 分支对比」 |
| 🧬 会话合并 | `merge_messages` / `SessionStore.merge_into` | 「🧬 会话合并」 |
| 📊 对话统计 | `message_content` / `estimate_tokens` / `session_stats` / `overview_stats` / `format_stats_markdown` | 「📊 对话统计洞察」 |

- **分支对比**：以最长共同前缀为锚点（V11.4 分支的自然延伸），给出同位置
  差异 `modified`、各自尾部 `a_only`/`b_only`、相似度与是否完全一致。
- **会话合并**：自动跳过分支共同前缀避免重复；`starred` 收藏下标按
  `mapping` 重映射、tags 合并、来源会话**保留可回溯**、target 自动置为当前。
- **对话统计**：消息数 / 角色分布 / 字符数 / 估算 tokens / 收藏 / 分支 /
  标签 / 置顶，单会话与全局聚合，附 Markdown 渲染。

配套 `ui/insight_dialog.py`（只读面板，可复制 / 另存 `.md`，
`setMarkdown` 不可用时自动退化纯文本）。

## 四、测试与验证

| 项目 | 结果 |
|---|---|
| **全量 `selftest.py`（offscreen）** | **780 通过 / 0 失败** |
| `test_v11_5_pc.py` | **22/22 全绿** |
| 回归 `test_v11_4_pc.py` + `test_v11_3_pc.py` + `test_search_export.py` | **40/40 全绿** |
| 安卓逻辑回归 `test_app_logic.py` | **16/16 全绿** |
| AST 类归属 / 零 GUI 依赖校验 | 通过（34 个类方法，`delete/append/messages` 仍在类内） |
| 安卓 core 全量 `py_compile` | 通过 |
| Qt 无头渲染 `InsightDialog` | 通过 |
| Windows exe `--version` / `--platform`（UTF-8 + cp1252） | 退出码 0 |
| Linux CLI `--version` / UOS deb `Version` | 11.5.0 |
| APK 内部版本 / 新逻辑 / 签名 v2+v3 | 见发布验收 |

### 反复优化补记：全量自测揪出的检索精度 bug

首次跑全量自测得 **776 通过 / 3 失败**。其中两处是 V11.3 起就没跟上的
硬编码断言（命令面板数写死 31、实际 43；「导出」搜索期望 1 条、V11.3 起
因「批量导出全部会话」变成 2 条），已改成结构不变量断言。

第三处 `搜索无结果` 是**真实缺陷**：`core/sessions.py::_tokenize` 把中文拆成
单字，导致搜「不存在的关键词xyz」时标题里的高频虚词「的」也会得分，
无关会话被误召回。修复：

- `_tokenize` 改为按**连续 CJK 片段**切分，片段长度 ≥2 时整段入 token，
  并保留片段内相邻二元组，**丢弃单字**；
- `search_ranked` 在「无有效 token」时返回 `[]`，不再 `return self.list()`。

「重命名」仍能命中「重命名后的会话」（整段短语 token），而虚词噪音被消除。
修复后 780/780 全绿。因 `core/sessions.py` 变更，**APK / CLI / deb /
Windows exe 全部重新构建**，版本文件夹与 zip 一并重新生成。

## 五、交付物清单

- **源码**：`core/insights.py`（新）、`core/sessions.py`（+`merge_into`）、
  `core/cli.py` 与 `starry_cli.py`（编码兜底）、`ui/insight_dialog.py`（新）、
  `app/assistant.py`（3 条命令）、`test_v11_5_pc.py`（新）
- **安卓同源**：`android/core/{insights,sessions,cli,config,mcp}.py` 同步
- **Windows**：`dist/星语Starry-CLI.exe`、`build-windows.yml`、
  `build_windows_cli.ps1`、`docs/Windows_EXE_构建指南.md`
- **文档**：`docs/` 下 9 份 `_v11_5`（评审 6 项 + API + 纪要 + 发布说明）
- **分发**：5 个带后缀完整项目文件夹 + 5 个 zip
- **提交**：`git commit` + `tag v11.5.0`

## 六、升级与安装

- **Windows**：从 Releases 下载 `星语Starry-CLI.exe`，或在本地跑
  `powershell -ExecutionPolicy Bypass -File scripts\build_windows_cli.ps1`。
  执行 `.\星语Starry-CLI.exe --version` 验证。
- **安卓**：卸载旧包后安装 `星语 Starry-11.5.0.apk`（v2/v3 签名可侧载）。
- **Linux / UOS**：`星语Starry-CLI` 二进制或 `星语Starry-CLI-UOS.deb`。
- **桌面**：`Ctrl+K` 输入「统计 / 对比 / 合并」体验新功能。

## 七、已知限制

- exe 未做代码签名，首次运行可能触发 SmartScreen（选择「仍要运行」）。
  正式分发建议购买代码签名证书。
- `estimate_tokens` 为离线相对估算，不代表任何模型的精确计费。
- GUI 桌面版 exe 仍由 `.github/workflows/ci.yml` 的 windows job 构建
  （本版聚焦无图形依赖、开箱即用的 CLI 版）。
- 历史大版本 v7.6–v11.4 全部保留，未曾覆盖。
