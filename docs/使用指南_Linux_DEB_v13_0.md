# Linux / 统信 UOS deb 使用指南 · v13.0.0

> 产物：`releases/assets/v13.0.0/linux/星语Starry-CLI-v13.0.0.deb`（195,294 字节）
> 纯标准库构造的真实 `.deb`（ar + control.tar.gz + data.tar.gz），
> 59 个 data 文件，`Package: starry-cli` / `Version: 13.0.0` / `Architecture: all`。

---

## 1. 安装

```bash
sudo dpkg -i 星语Starry-CLI-v13.0.0.deb
# 若报缺依赖
sudo apt-get install -f
```

control 声明依赖：`python3 (>= 3.9)`、`python3-requests`、
`python3-bs4`、`python3-markdown`。适用于 Debian / Ubuntu / 统信 UOS /
银河麒麟等 dpkg 系发行版。

安装后：

```bash
starry --version      # 星语 Starry 13.0.0（命令行版）
starry --platform
starry --workbench    # 一键体检：环境 + 整体项目 + 分波并行 + 更新
```

`/usr/bin/starry` 是启动器，实际执行 `python3 /opt/starry/starry_cli.py "$@"`。
源码在 `/opt/starry/`，含完整 `core/`（v13 三个新模块都在内）、
`README.md`、`CHANGELOG.md` 与使用指南。

## 2. v13 新功能

```bash
# 整体项目 → 多线并行
starry --project "调研并撰写发版方案"
starry --project "调研并撰写发版方案" --parallel --workers 4
starry --project "..." --parallel --timeout 10 --retries 2

# 项目存档
starry --project "写一本书" --parallel --project-save p.starryproj
starry --project-load p.starryproj --parallel

# 工作台总览
starry --workbench

# 更新检查
starry --update-check
starry --update-check --update-manifest /path/to/update.json
STARRY_UPDATE_URL=https://your.host/update.json starry --update-check
```

默认完全离线，不需要 API Key、不发起网络请求。

## 3. v12 能力保留

```bash
starry --doctor
starry --budget 4096
starry --archive 备份.starry
starry --restore 备份.starry
starry -p "你好" --echo
```

## 4. 验证包内容（不安装也能查）

```bash
ar t 星语Starry-CLI-v13.0.0.deb
# debian-binary  control.tar.gz  data.tar.gz

ar p 星语Starry-CLI-v13.0.0.deb control.tar.gz | tar tzf -
ar p 星语Starry-CLI-v13.0.0.deb data.tar.gz   | tar tzf - | grep 'core/'
```

应能看到 `core/project.py`、`core/parallel.py`、`core/updatecheck.py` 三个 v13 新模块。
CI 的 `ci.yml::build-deb` 会把这段结构校验自动化。

## 5. 数据目录

按 `core.config.get_config_dir()` 的 XDG 规则落盘；`starry --doctor` 会打印实际路径。
隔离网关统计/预算数据用 `STARRY_DATA_DIR`。

## 6. 更新检查

`update.json` 在版本快照的 `assets/update.json`。
linux 资产条目包含 `.deb` 的真实 SHA-256 与大小：

```bash
starry --update-check --update-manifest update.json
sha256sum 星语Starry-CLI-v13.0.0.deb     # 与清单里的 sha256 比对
```

工具只给结论，不自动下载或替换；升级请自行下载后用 `sudo dpkg -i` 覆盖安装。

## 7. 卸载 / 升级

```bash
sudo dpkg -r starry-cli
sudo dpkg -i 新版本.deb      # 直接覆盖安装即升级，配置与会话保留
```

`.starry`（会话存档）与 `.starryproj`（项目存档）格式与 v12 兼容，不受升级影响。

## 8. 常见问题

| 现象 | 处理 |
| --- | --- |
| `dpkg -i` 报依赖错误 | `sudo apt-get install -f`；或按 control 手动装 python3-requests / bs4 / markdown |
| `starry: command not found` | 确认 `/usr/bin/starry` 存在且可执行；`postinst` 会 chmod，必要时手动加上执行权限 |
| 中文乱码 | 设置 `LANG=zh_CN.UTF-8` 或 `PYTHONUTF8=1` |
| 无图形环境 | 正常，这是 CLI 包；桌面 GUI 版需要 PyQt5 + X11/Wayland |
| 想看免依赖 ELF 版 | 由 `.github/workflows/release.yml` 在 ubuntu-latest 上产出；本机 Windows 无法交叉编译 Linux ELF |

## 9. 校验完整性

```bash
sha256sum 星语Starry-CLI-v13.0.0.deb
```

与 `releases/SHA256SUMS-v13.0.0.txt` 中
`assets/v13.0.0/linux/星语Starry-CLI-v13.0.0.deb` 一行比对。
