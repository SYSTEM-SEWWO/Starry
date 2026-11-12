# Linux / 统信 UOS deb 使用指南 · v13.1.0

> 产物：`releases/assets/v13.1.0/linux/星语Starry-CLI-v13.1.0.deb`
> （构建输出：`dist/星语Starry-CLI-v13.1.0.deb`）
> 由纯标准库 `scripts/build_deb.py` 手写 `ar` 归档生成，不依赖 `dpkg-deb`。

## 1. 安装

```bash
sudo dpkg -i 星语Starry-CLI-v13.1.0.deb
starry --version        # 星语 Starry 13.1.0（命令行版）
```

安装内容：

| 路径 | 内容 |
| --- | --- |
| `/usr/bin/starry` | 启动器（调用 `/opt/starry/starry_cli.py`） |
| `/opt/starry/core/` | 全部纯逻辑模块，含 **`core/hub.py`** |
| `/opt/starry/skills/` | ★ 随包示例技能（3 份 `SKILL.md` + README） |
| `/opt/starry/docs/` | 使用指南与文档 |
| `/usr/share/applications/starry-cli.desktop` | 桌面入口 |
| `/usr/share/icons/hicolor/128x128/apps/starry.png` | 图标（存在时） |

`Package: starry-cli` / `Version: 13.1.0` / `Architecture: all`；
本版 data 文件 **66 个**、ar 成员 **3 个**（`debian-binary` / `control.tar.gz` / `data.tar.gz`）。

## 2. v13.1 新功能：Skills Hub

装完即可用，无需联网、无需额外下载：

```bash
starry --hub                                   # 列出随包与本机已装的技能
starry --hub-search api                        # 搜索
starry --hub-info release-checklist            # 查看正文
starry --hub-source ~/my-skills --hub          # 追加本地技能源
starry --hub-update --hub-manifest hub.json    # 技能更新判定
starry --hub-import release-checklist          # 导入技能库（写 config.json）
```

自动扫描位置：

| 生态 | 路径 |
| --- | --- |
| 随包示例 | `/opt/starry/skills/` |
| Claude Code | `~/.claude/skills/`、`<project>/.claude/skills/` |
| GitHub / Copilot | `.github/skills/`、`<repo>/skills/` |
| WorkBuddy | `~/.workbuddy/skills/`、`<project>/.workbuddy/skills/` |

> `/opt/starry/skills/` 由 `core.hub.bundled_skills_dir()` 自动定位：
> 源码运行取项目根，PyInstaller onefile 取 `sys._MEIPASS`，deb 安装后取 `/opt/starry`。

## 3. 保留能力（v12 / v13.0）

```bash
starry --doctor
starry --budget 4096
starry --archive 备份.starry
starry --restore 备份.starry
starry --project "调研并撰写发版方案" --parallel --workers 4
starry --project-load p.starryproj --parallel
starry --workbench
starry --update-check --update-manifest update.json
```

全部离线纯逻辑，不消耗 token、不需要 API Key。

## 4. 结构自检（不安装也能验）

```bash
ar t 星语Starry-CLI-v13.1.0.deb
ar p 星语Starry-CLI-v13.1.0.deb control.tar.gz | tar tzf -
ar p 星语Starry-CLI-v13.1.0.deb data.tar.gz   | tar tzf - | grep -E 'core/|skills/'
```

预期能看到 `core/hub.py`、`core/project.py`、`core/parallel.py`、
`core/updatecheck.py`、`skills/claude-code-style/SKILL.md` 等条目。

也可用项目自带脚本做构建期自检（`build_deb.py` 已内置 ar 魔数 / 三个成员校验）：

```bash
python scripts/build_deb.py
python scripts/check_core_parity.py --expect-version 13.1.0
```

## 5. 中文输出与编码

deb 走系统 Python，输出编码由 locale 决定。若终端 / CI 管道出现中文乱码，
可显式指定：

```bash
PYTHONIOENCODING=utf-8 starry --hub
```

v13.1 的 `starry_cli.py` 会尊重 `PYTHONIOENCODING`；未设置时沿用
v11.5 的「只放宽 errors、不改变原编码」策略，保证 GBK / cp1252 环境不秒退。

## 6. 与 Windows EXE 的差异

| | Linux deb | Windows EXE |
| --- | --- | --- |
| 形态 | 系统安装包（`dpkg -i`） | 单文件 EXE，免安装 |
| GUI 桌面版 | 本 deb 是 CLI 版；GUI 需 `python main.py`（PyQt5） | 另有 `星语Starry.exe`（console=False） |
| Python | 使用系统 Python 3 | 内嵌 Python，无需安装 |
| `skills/` | `/opt/starry/skills/` | 内嵌在 onefile 的 `_MEIPASS/skills/` |

## 7. 卸载与校验

```bash
sudo dpkg -r starry-cli
sha256sum 星语Starry-CLI-v13.1.0.deb    # 与 SHA256SUMS-v13.1.0.txt 比对
```

下载的 deb 请与 `releases/SHA256SUMS-v13.1.0.txt` 核对后再安装。
`update.json` 里的资产哈希由 `update-manifest.yml` 在 Release 发布后重算，
以 Release 资产中的清单为准。
