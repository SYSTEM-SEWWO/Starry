# 使用指南 · 统信 UOS 版（星语Starry-v10.0-uos）

> 面向统信 UOS（及麒麟等国产 Debian 系发行版）用户：以合规 `.deb` 形态分发与安装。

## 1. 平台识别

星语会在启动时自动检测 UOS（读 `/etc/os-release` 的 `ID=uos` 或 `UnionTech`）。
命令行版可执行 `python3 starry_cli.py --platform`，输出应为「统信 UOS / 版本后缀 uos」。

## 2. 安装方式一：deb 安装包（推荐，符合应用商店分发）

```bash
# 在具备 dpkg 的 Debian/Ubuntu/UOS 主机上构建 .deb
bash scripts/build_uos.sh 10.0.0

# 安装
sudo dpkg -i dist/星语Starry-CLI-UOS.deb
```

安装后二进制位于 `/opt/starry/bin/星语Starry-CLI`，并在开始菜单/启动器生成终端入口。

## 3. 安装方式二：直接运行源码

```bash
python3 -m pip install -r requirements.txt
python3 starry_cli.py "你好"
```

UOS 终端如需语音朗读，可装 `espeak`；其余纯文本场景无需额外系统库（命令行版无 Qt 依赖）。

## 4. 配置 API Key

- 配置文件：`~/.config/ai-desktop-assistant/config.json`（权限 0o600）。
- 或命令行覆盖：`python3 starry_cli.py --provider deepseek --api-key sk-xxx "你好"`。

## 5. 与桌面版的关系

本文件夹为「统信 UOS 版」发布包（后缀 `uos`），含**完整工程**。
UOS 上的图形界面（毛玻璃悬浮球）由桌面 GUI 版提供（需 Qt 运行库，见 `scripts/build_linux.sh`）。
完整命令行参数见《命令行使用指南.md》。
