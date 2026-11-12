# 使用指南 · Windows 命令行版（星语Starry-v10.0-windows-cli）

> 面向 Windows 用户：在无图形依赖的前提下，于命令提示符 / PowerShell 中调用星语 Starry。

## 1. 运行环境

- Windows 10 / 11（x64）
- Python 3.10+（建议从 python.org 安装并勾选「Add to PATH」）
- 依赖：`pip install -r requirements.txt`

## 2. 直接以源码运行

```powershell
# 在项目根目录
python -m pip install -r requirements.txt
python starry_cli.py "你好，介绍一下你自己"
python starry_cli.py --platform
python starry_cli.py --agent "列出当前目录有哪些文件"
```

## 3. 打包为独立 exe（无需 Python 环境）

```powershell
# 在管理员/普通 PowerShell 中执行
powershell -File scripts\build_windows_cli.ps1
```

产物：`dist\星语Starry-CLI\星语Starry-CLI.exe`（控制台程序）。

双击或命令行调用：

```powershell
.\星语Starry-CLI.exe "今天几号？"
.\星语Starry-CLI.exe --json "写一句诗" | findstr answer
```

## 4. 配置 API Key

- 推荐先在**桌面版**设置里填好 Key（GUI 版与 CLI 版共用配置）。
- 或命令行覆盖：`python starry_cli.py --provider deepseek --api-key sk-xxx "你好"`
- 配置位置：`%APPDATA%\ai-desktop-assistant\config.json`（权限 0o600，仅本人可读）。

## 5. 与桌面版的关系

本文件夹为「Windows 命令行版」发布包（后缀 `windows-cli`），包含**完整工程**：
全部源码、所有 `docs/*.md`、主文件 `starry_cli.py` / `main.py`、README、CHANGELOG。
需要图形界面（毛玻璃悬浮球、思考可视化）请使用桌面 GUI 版（后缀无，或见 `scripts/build_windows.ps1`）。

更完整的命令行参数见《命令行使用指南.md》。
