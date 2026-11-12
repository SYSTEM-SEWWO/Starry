# Windows EXE 构建与使用指南（V11.5）

> 本指南对应「打包成点 exe」诉求的完整闭环。V11.5 之前，Windows 端只有
> `scripts/build_windows_cli.ps1` 构建脚本、从未真正交付过 `.exe`；本版起
> **真产出单文件 exe**，并把它接入 GitHub Releases 自动发布。

## 一、三种获得 exe 的方式

| 方式 | 适用场景 | 产物 |
|---|---|---|
| **GitHub Releases（推荐）** | 推 `v*` tag 自动构建，无需本地环境 | Release 资产 `星语Starry-CLI.exe` |
| **Windows 本地一键构建** | 想在自己机器上编译 | `dist\星语Starry-CLI\星语Starry-CLI.exe` |
| **Linux + Wine 复现** | 无 Windows 机器的维护者 | 同样的 PE32+ exe（本版实测通过） |

### 1. GitHub Releases 自动发布

```bash
git tag v11.5.0
git push --tags
```

`.github/workflows/build-windows.yml` 会在 `windows-latest` 上：

1. 安装 Python 3.11 + `requirements.txt` + PyInstaller；
2. 用 `starry_cli.spec` 打出单文件 exe；
3. 跑 `--version` / `--platform` 冒烟自检（退出码非 0 即失败）；
4. 上传 Actions Artifact（保留 30 天）；
5. **追加资产到 GitHub Releases**（与 `build-android.yml` 并行，只追加不覆盖）。

一个 tag 同时产出 **Android APK + Windows EXE**，Release 里一并下载。

### 2. Windows 本地一键构建

在项目根目录用 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows_cli.ps1
```

脚本幂等（venv 存在则复用），会读取 `core/config.py` 的版本号打印，
打包后自动跑 `--version` / `--platform` 自检，并把产物连同文档整理到
`dist\星语Starry-CLI\`。

### 3. Linux + Wine 复现（本版实测路线）

适用于没有 Windows 机器的维护者，步骤与 CI 等价：

```bash
# 1) Wine（Ubuntu 22.04+）
apt-get install -y --no-install-recommends wine64
WINEPREFIX=/tmp/wineprefix WINEARCH=win64 /usr/lib/wine/wine64 wineboot --init

# 2) Windows 版 Python 3.11 embeddable，放进 C: 盘
unzip python-3.11.9-embed-amd64.zip -d $WINEPREFIX/drive_c/py311
sed -i 's/^#import site/import site/' $WINEPREFIX/drive_c/py311/python311._pth

# 3) 装 pip + PyInstaller（务必通过 cmd /c 运行，见下方「坑」）
#    用 .bat（CRLF）包一层：C:\py311\python.exe -m pip install pyinstaller ...
# 4) 打包（同样走 cmd /c）
#    cd /d Z:\workspace\ai-assistant
#    C:\py311\python.exe -m PyInstaller starry_cli.spec --noconfirm --clean
```

> **坑（V11.5 实测）**：直接用 `wine64 python.exe script.py` 会报
> `Fatal Python error: init_sys_streams ... OSError: [WinError 6] Invalid handle`。
> 原因是无控制台时 Wine 无法给 Windows 程序分配标准句柄。
> **解法**：一律通过 `wine64 cmd /c C:\xxx.bat` 运行，并把输出重定向到
> Windows 路径下的日志文件，由 `cmd.exe` 提供真实控制台。

## 二、V11.5 实测修复：中文控制台秒退

首次在 Wine 里打出 exe 后冒烟 `--version` **真实复现了一个崩溃**：

```
UnicodeEncodeError: 'charmap' codec can't encode characters ...
  File "core\cli.py", line 144, in _emit
  File "encodings\cp1252.py", line 19, in encode
```

英文代码页（cp1252）无法编码 `星语 Starry` 等中文，`out.write()` 直接抛异常
导致 exe 秒退。已在两处做兜底：

| 位置 | 修复 |
|---|---|
| `starry_cli.py` 入口 | `sys.stdout/stderr.reconfigure(errors="replace")`，兼容所有平台 |
| `core/cli.py::_emit` | 捕获 `UnicodeEncodeError`，按目标流编码 `replace` 重写，最后再退 ASCII |

效果（Wine 实测）：

- `--version`：退出码 **0**，输出 `... Starry 11.x.x ...`（纯英文代码页中文退化为 `?`，**绝不崩溃**）
- `--platform`：退出码 **0**
- 中文 Windows（GBK / cp936 控制台）中文可正常显示，无退化

> 这条修复同时惠及 Linux / UOS 的 CLI 二进制与安卓核心（三端 `core/cli.py` 同源）。

## 三、使用与验证清单

下载或构建出 `星语Starry-CLI.exe` 后：

```powershell
.\星语Starry-CLI.exe --version     # 应打印版本号，退出码 0
.\星语Starry-CLI.exe --platform    # 应打印平台 / 打包形态，退出码 0
.\星语Starry-CLI.exe "你好"         # 正常对话（需已在设置里配置服务商密钥）
.\星语Starry-CLI.exe -f prompt.txt --json
```

| 验收项 | 期望 |
|---|---|
| 文件类型 | `PE32+ executable (console) x86-64, for MS Windows` |
| `--version` | 退出码 0，含当前 `APP_VERSION` |
| `--platform` | 退出码 0，含「平台 / 打包形态」 |
| 中文输出 | 不抛 `UnicodeEncodeError` |
| 免安装 | 单文件、无需 Python 运行时 |

## 四、常见问题

- **SmartScreen / 杀软拦截**：exe 未经代码签名，首次运行可能提示「未知发布者」，
  选择「仍要运行」即可；正式分发建议购买代码签名证书。
- **控制台中文乱码**：执行 `chcp 65001` 或设置 `$env:PYTHONIOENCODING="utf-8"`；
  即便不设置也不会崩溃（退化为 `?`）。
- **首次启动慢**：PyInstaller 单文件需自解压，通常 1–3 秒，属正常现象。
- **GUI 桌面版**：`ci.yml` 的 windows job 会用 `starrystar.spec` 打
  `星语Starry.exe`（PyQt5 图形界面）并上传 Actions Artifact；本指南聚焦
  无图形依赖、开箱即用的 CLI 版。

## 五、相关文件

```
starry_cli.py                          CLI 入口（含编码兜底）
starry_cli.spec                        PyInstaller 配置（console=True）
scripts/build_windows_cli.ps1          本地一键构建（幂等 + 自检）
scripts/build_windows.ps1              GUI 版构建
.github/workflows/build-windows.yml    推 tag 自动构建 + 发布 Release
.github/workflows/build-android.yml    推 tag 自动构建 + 发布 APK
```
