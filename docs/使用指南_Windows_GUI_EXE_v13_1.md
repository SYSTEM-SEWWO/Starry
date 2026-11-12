# Windows GUI 版 EXE 使用指南 · 星语 Starry v13.1.0

> 产物：`dist/星语Starry.exe`（发布资产名 `星语Starry-GUI-v13.1.0.exe`）
> 与 `星语Starry-CLI.exe` 是**两个不同的程序**：GUI 版双击即用、有窗口和托盘；
> CLI 版带控制台、适合脚本与管道。v13.1 起两者都随 Release 一起发布。

## 1. 直接运行

双击 `星语Starry.exe`：

1. 首次启动会弹出 EULA（企业商用授权）对话框，同意后进入；
2. 液态玻璃开屏动画结束后显示悬浮球，单击展开对话窗口；
3. 关闭窗口**不会退出程序**，托盘图标常驻，右键菜单可退出。

系统要求：Windows 10/11 x86-64；无需安装 Python、无需装依赖、无需 API Key 即可
使用 Skills Hub、整体项目工作台等全部离线功能（对话需自行配置服务商 Key）。

## 2. 打开 Skills Hub

- `Ctrl+K` → 「🧩 打开 Skills Hub」
- 或 `Ctrl+K` → 「🔄 检查技能更新」直接调起清单选择

窗口分左右两栏：左侧按来源列出技能（来源 / 名称 / 版本 / 说明），
右侧显示技能详情与**指令正文原文**（便于复制与核对，不做 Markdown 渲染吞字符）。

| 按钮 | 作用 |
| --- | --- |
| 🔄 刷新 | 重新扫描全部技能源 |
| 📁 添加源 | 选一个本地目录作为新技能源 |
| ⬇ 导入为星语技能 | 把选中技能写入 `config.json` 的技能库 |
| 🔄 检查技能更新 | 选 `hub.json` 做离线校验与版本比对 |
| 📤 导出 hub.json | 生成一份可分发的技能清单 |

开箱即带 `skills/` 里的 3 个示例技能（Claude Code 风格 / GitHub 风格 / 扁平单文件），
也会自动发现 `~/.claude/skills/`、`~/.workbuddy/skills/`、项目内 `.github/skills/`。

## 3. 无显示器自检（重要）

GUI EXE 是 `console=False` 的窗口程序，双击时看不到 `--version` 的输出，
`sys.stdout` 在窗口子系统下也可能为 `None`。因此本版把自检结果**写入文件**：

```bat
星语Starry.exe --version --out version.txt
星语Starry.exe --selftest --out selftest.json
```

`selftest.json` 示例：

```json
{
  "app": "星语Starry-GUI",
  "version": "13.1.0",
  "passed": 15,
  "total": 15,
  "checks": [{"name": "随包 skills/ 已打进产物", "ok": true}, ...]
}
```

自动化冒烟（本机与 GitHub Actions 共用）：

```bash
set QT_QPA_PLATFORM=offscreen
python scripts/smoke_gui_exe.py --exe dist/星语Starry.exe --expect-version 13.1.0
```

脚本会启动两次子进程、读取两个落盘文件、逐项断言，退出码 0 = 全通过。
它验证的不只是「进程没崩」，还包括：版本真源、`core.hub` 可用、
随包 `skills/` 真的被打进 EXE、HubDialog 与 WorkbenchDialog 能 offscreen 装配。

> 这项设计是为了避免「校验全绿但产物是假的」：如果打包时漏了 `skills/`，
> `--selftest` 会直接失败，而不是让 EXE 表面上能启动。

## 4. 本地构建

```bash
pip install -r requirements.txt
pip install "pyinstaller==6.22.3"
python -m PyInstaller starrystar.spec --noconfirm --clean
python scripts/smoke_gui_exe.py --exe dist/星语Starry.exe --expect-version 13.1.0
```

`starrystar.spec` 要点：

- 入口 `main.py`，`console=False`，图标 `assets/icon.ico`（存在时）；
- `datas` 包含 `skills/`、`README.md`、`requirements.txt` 与 Playwright 的 node driver；
- `hiddenimports` 显式声明 v12/v13/v13.1 的懒加载模块：
  `core.stardust` / `core.project` / `core.parallel` / `core.updatecheck` /
  `core.hub` / `ui.workbench_dialog` / `ui.hub_dialog`；
- 浏览器内核（约 150MB）**不内嵌**，由「设置 → 网页接入 → 一键安装浏览器内核」按需下载；
- llama.cpp 二进制同样不内置，由「模型库 → 运行时状态条」引导放置。

## 5. 与 CLI EXE 的分工

| | `星语Starry.exe`（GUI） | `星语Starry-CLI.exe`（CLI） |
| --- | --- | --- |
| 控制台 | 无 | 有 |
| 典型用法 | 双击 / 托盘 / 命令面板 | `--hub` / `--project` / `--workbench` / 管道 |
| 自检 | `--selftest --out r.json` | `--version` / `--doctor` / `--hub` |
| 退出 | 托盘菜单退出 | 命令结束即退出 |

两个 EXE 共用同一份 `core/` 纯逻辑与同一份 `skills/`，行为一致。

## 6. 故障排查

| 现象 | 排查 |
| --- | --- |
| 双击后没有窗口 | 看托盘；或跑 `--selftest --out r.json` 读结果 |
| 首次启动反复弹 EULA | 同意后需能写 `%USERPROFILE%\.starry`，检查目录权限 |
| `--selftest` 报 `随包 skills/` 失败 | 打包时 `datas` 漏了 `skills/`，重新用本版 spec 构建 |
| 技能列表为空 | 用「📁 添加源」指定目录，或确认 `skills/` 随包存在 |
| 中文乱码 / 秒退 | v11.5 起已有 GBK / cp1252 编码兜底；如仍出现请提交 `--selftest` 输出 |

## 7. 发布与校验

推 `v13.1.0` tag 后，`.github/workflows/build-windows.yml` 会在 `windows-latest`
同时构建 CLI 与 GUI 两份 EXE，各自冒烟通过后以 `append_body` 追加到 GitHub Releases。
`update-manifest.yml` 在 Release 发布后重新生成权威 `update.json`（含真实哈希与大小）。
下载的 EXE 请与 `SHA256SUMS-v13.1.0.txt` 核对后再运行。
