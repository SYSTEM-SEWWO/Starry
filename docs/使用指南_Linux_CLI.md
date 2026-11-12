# 使用指南 · Linux 命令行版（星语Starry-v10.0-linux-cli）

> 面向 Linux 桌面 / 服务器 / WSL 用户：在无图形依赖的前提下使用星语 Starry。

## 1. 运行环境

- 任意主流发行版（Debian/Ubuntu/Fedora/Arch…）
- Python 3.10+，`pip install -r requirements.txt`
- 服务器无桌面的场景尤为适合（零 Qt 依赖）。

## 2. 直接以源码运行

```bash
python3 -m pip install -r requirements.txt
python3 starry_cli.py "用一句话解释容器是什么"
python3 starry_cli.py --platform
python3 starry_cli.py --agent "统计当前目录代码行数"
```

## 3. 打包为独立二进制

```bash
bash scripts/build_linux_cli.sh
```

产物：`dist/星语Starry-CLI/星语Starry-CLI`（ELF，控制台）。直接运行：

```bash
./星语Starry-CLI --json "生成一句 Slogan"
```

## 4. 配置 API Key

- 与桌面版共用：`~/.config/ai-desktop-assistant/config.json`（权限 0o600）。
- 或命令行覆盖：`python3 starry_cli.py --provider openrouter --api-key sk-xxx "你好"`。

## 5. 服务器 / CI 场景

```bash
# 静默批量
for q in "总结要点" "给建议"; do
  python3 starry_cli.py --no-reasoning --json "$q"
done
```

## 6. 与桌面版的关系

本文件夹为「Linux 命令行版」发布包（后缀 `linux-cli`），含**完整工程**。
图形界面版（毛玻璃悬浮球、思考可视化）请使用桌面 GUI 版（见 `scripts/build_linux.sh`）。
完整参数见《命令行使用指南.md》。
