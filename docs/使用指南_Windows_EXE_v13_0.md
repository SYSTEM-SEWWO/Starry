# Windows EXE 使用指南 · v13.0.0

> 产物：`releases/assets/v13.0.0/windows/星语Starry-CLI-v13.0.0.exe`（15,928,759 字节）
> 本地构建输出：`dist/星语Starry-CLI.exe`。PyInstaller 6.22.3 单文件 console 版，
> **无需安装 Python、无需 API Key、无需联网**即可跑通 v13 全部离线能力。

---

## 1. 拿到手先做三件事

在「命令提示符」或 PowerShell 中进入解压目录，执行：

```
星语Starry-CLI-v13.0.0.exe --version
星语Starry-CLI-v13.0.0.exe --platform
星语Starry-CLI-v13.0.0.exe --workbench
```

- 第一条应显示 `星语 Starry 13.0.0（命令行版）`
- 第二条显示平台、版本后缀与打包形态
- 第三条是一键体检：环境 + 项目 + 并行 + 更新，应输出「项目进度：**100%**」「波次：**2**」

看到这两行，说明 EXE 里的 `core.project` / `core.parallel` / `core.updatecheck`
都真实可用，而不是只打了个版本号。

> 本机实测：10 项子进程冒烟全部 RC=0，含 `--version` / `--platform` / `--doctor` /
> `--project` / `--project --parallel` / `--workbench` / `--update-check` /
> `--budget` / `--project-save` / `--archive`。

## 2. 建议先重命名为短名

```
copy 星语Starry-CLI-v13.0.0.exe starry.exe
starry.exe --workbench
```

后文命令统一用 `starry` 代替完整文件名。

## 3. v13 新功能（全部离线）

```
rem 整体项目 → 分波并行
starry.exe --project "调研并撰写发版方案"
starry.exe --project "调研并撰写发版方案" --parallel --workers 4

rem 保存 / 载入项目
starry.exe --project "写一本书" --parallel --project-save p.starryproj
starry.exe --project-load p.starryproj --parallel

rem 工作台总览
starry.exe --workbench

rem 更新检查
starry.exe --update-check
starry.exe --update-check --update-manifest update.json
starry.exe --update-check --update-url https://your.host/update.json
```

参数说明见 `docs/API开放文档_v13_0.md` §4。

## 4. v12 能力保留

```
starry.exe --doctor
starry.exe --budget 4096
starry.exe --archive 备份.starry
starry.exe --restore 备份.starry
starry.exe -p "你好，介绍一下你自己" --echo
```

## 5. 中文输出与控制台编码

EXE 是 console 版，Windows 控制台默认 cp936/GBK。
`starry_cli.py` 入口与 `core.cli._emit()` 有双层编码兜底（`errors="replace"`），
**不会因中文打印而秒退**——这是 v11.5 在 Wine 里实测修掉的问题，本版保持。

在 PowerShell 里若看到 `✦` 变成 `?`，属编码降级，信息完整。
若需 UTF-8 输出，先执行 `chcp 65001`，并把控制台输出编码设为 UTF-8。

> 用 Python `subprocess.run(..., capture_output=True)` 读取 EXE 输出时，
> 请按 `utf-8 → gbk → cp1252` 顺序尝试解码，不要只按 UTF-8。
> 本轮冒烟就曾因只按 UTF-8 解码而误判，EXE 本身无缺陷。

## 6. 数据目录与配置

- 配置/会话目录：`%APPDATA%\ai-desktop-assistant`
- `--doctor` 会打印实际目录、服务商就绪状态、依赖与三端同源结论。
- `--archive` / `--restore` 读写该目录下的会话与记忆；导入前自动备份为 `*.bak-时间戳`。
- 只想隔离网关统计/预算数据：设 `STARRY_DATA_DIR`。
  **不要只改 `HOME`**——Windows 上 `expanduser("~")` 读的是 `USERPROFILE`。

配置服务商后，`--execute` 可让 `chat` 类任务走真实模型；默认不需要。

## 7. 更新检查怎么用

`update.json` 随版本快照一起分发在 `releases/assets/v13.0.0/update.json`：

```
starry.exe --update-check --update-manifest update.json
```

输出要点：清单校验通过 / 当前版本 / 最新版本 / 可更新资产的名称、
大小、地址、SHA-256，以及「不自动下载」提示。

**请只用可信来源的清单**，核对哈希后再自行下载。
清单的 digest 与资产 sha256 是完整性校验，不是签名认证（见代码安全性评估）。

## 8. 常见问题

| 现象 | 处理 |
| --- | --- |
| 双击 EXE 一闪而过 | 这是命令行程序，请从命令提示符 / PowerShell 启动并带参数；或直接跑 `--workbench` |
| 首次启动慢几秒 | 单文件包自解压，正常 |
| `--doctor` 提示 markdown 未随 CLI 包分发 | 符合预期，markdown 只服务桌面渲染，CLI 不需要 |
| `--update-check` 说未配置 | 正常离线结论，未发起任何网络请求 |
| 杀毒软件误报 | PyInstaller 单文件包常见误报；可用 `SHA256SUMS-v13.0.0.txt` 核对哈希后加白名单 |
| 想用图形界面 | 桌面 GUI 版请用 `python main.py`（需 PyQt5），或用 `build_windows.ps1` 另打 GUI EXE |

## 9. 校验完整性

在 PowerShell 中：

```
Get-FileHash .\星语Starry-CLI-v13.0.0.exe -Algorithm SHA256
```

与 `releases/SHA256SUMS-v13.0.0.txt` 中
`assets/v13.0.0/windows/星语Starry-CLI-v13.0.0.exe` 一行比对。
