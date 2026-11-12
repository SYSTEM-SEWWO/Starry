# 发布说明 · 星语 Starry v12.0.0

**发布日期**：2026-11-07　**上一版本**：v11.5.0　**版本主题**：安卓闪退根因修复 ＋ 三端同源工程化 ＋ 完整 Releases 交付体系

---

## 一、为什么有这个大版本

用户的指令链里反复出现「Apk 安装之后会闪退，把这个问题马上解决」「安卓端还是闪退，你再检查一下」「保证 apk 所有核心功能可以用并且测试完成」。v11.5 及之前几轮都在改 `android/starryandroid/app.py` 的界面逻辑，但**没有验证过打进 APK 的到底是什么**，也没有核对过 Android 端调用与真实 `core` 的签名是否一致。

v12.0 换了一条路径：**先鉴定、再定位、后修复**。把已有 51MB 签名 APK 完整解包，静态核对 Chaquopy 资源、字节码、依赖元数据；再用「真实 core + 严格 UI 替身」的集成测试复现问题。由此找到多处**可实证**的缺陷，并顺带完成三端同源、发版体系和电脑端新功能。

## 二、安卓闪退与核心功能：实证结论

### 2.1 鉴定结果（可复跑：`python scripts/verify_apk.py --apk <APK>`）

对 v11.5 的真实 APK 实测：**21 项通过 / 1 项失败 / 2 项提示**。

| 项目 | 实测 |
| --- | --- |
| v1 (JAR) + v2/v3 (APK Signing Block) 签名 | 均存在，签名块头尾长度自洽（head=tail=4088） |
| Chaquopy / CPython 3.11 | `libpython3.11.so` 三 ABI；`build.json` python_version=3.11；`.pyc` magic=3.11 |
| `app.imy` 完整性 | SHA1 与 `build.json` 记录一致（4b632f61…），43 个模块 |
| 应用版本 | `starryandroid-11.5.0.dist-info` 存在，= 11.5.0 |
| 权限 / 后端 | INTERNET 已声明；`[toga.backends]` 仅注册 `android` |
| **唯一 FAIL** | **toga 0.2.15 元包 与 toga_core 0.5.7 / toga_android 0.5.7 混装**，还带入 `toga_gtk 0.2.15` |

完整原始输出保存在 `docs/APK鉴定报告_v11_5_实测.txt`。

### 2.2 应用代码级缺陷（文件:行号 + 复现依据）

| 编号 | 缺陷 | 证据 | 后果 |
| --- | --- | --- | --- |
| **F1** | `AppConfig.load()` 在 `startup()` 的 try 之外；`core/config.py::get_config_dir()` 的 `os.makedirs` 无任何保护 | v11.5 `app.py:55`、`config.py:303` | 任何磁盘/沙盒异常直接冒泡到 Toga → 进程被杀 = 闪退 |
| **F2** | 未使用 Android 应用私有目录 | `config.py` 仅有 win/darwin/linux 三分支 | 配置/记忆可能落到不可写路径 |
| **F3** | `toga.Selection(value=cfg.model())` 未校验值属于 items | 本机实测 Toga 0.5.7：`Selection(items=['a','b'], value='z')` → `ValueError: 'z' is not a current item in the selection` | 自定义模型或切换服务商后点「设置」即崩；`open_settings` 无 try |
| **F4** | `learn_from_conversation(prompt=..., answer=...)` 与真实签名不符 | 真实 `core/memory.py:216` 是 `(user_text, assistant_text)`；v11.5 `app.py:347` 用错关键字 | 真机必抛 TypeError，被 try 吞掉 → **长期记忆静默失效** |
| **F5** | `ScrollContainer.scroll_to_bottom()` 不存在 | 实测 Toga 0.5.7 只有 `vertical_position` / `max_vertical_position` | 长对话不自动滚动 |
| **F6** | 异常只写 logcat，失败即 `sys.exit(1)` | v11.5 `__main__.py` | 用户看不到原因，无法反馈 |
| **F7/F8** | UI 回调无隔离、单窗口约束靠人工记得 | `app.py` | 一个回调异常可拖垮循环；多窗口会崩 |

**最关键的发现**：v11.5 的 `android/test_app_logic.py` 报「16/16 全绿」，但它把 **核心逻辑也 fake 掉了**，而且 fake 的签名是按 `app.py` 写的：`FakeMemory.learn_from_conversation(self, prompt=None, answer=None)` 恰好复刻了 F4 的错误调用，把真机必现的 TypeError 伪装成通过；`FakeWidget` 的 Selection 不校验 value、还自带 `scroll_to_bottom()`，于是 F3 / F5 也测不出来。**这是「测试通过但功能不可用」的直接原因。**

### 2.3 修复（8 项，全部落在真实源码）

- F1：`core/config.py` 新增 `is_android()`（判据取 Toga 0.5.7 官方做法 `sys.getandroidapilevel`）、`_safe_makedirs()` 逐级回退；`AppConfig.load()` 永不抛异常；`startup()` 全程包裹，失败显示应用内错误页。
- F2：`startup()` 把 `app.paths.config` 注入 `STARRY_CONFIG_DIR`。
- F3：新增 `_safe_value()`，所有 Selection 的 value 先做成员校验；`open_settings` / `on_save_settings` / `on_provider_select` 全部兜底。
- F4：改回 `learn_from_conversation(user_text=..., assistant_text=...)`，并新增回归用例**证明旧调用确实抛 TypeError**。
- F5：改用 `vertical_position = max_vertical_position`。
- F6：全局 `sys.excepthook` + crash.log + 应用内「诊断」页（版本/平台/配置目录/异常条数）。
- F7：每个 UI 回写回调单独 try；`_throttled()` 每 80ms 节流；「停止」按钮可中断。
- F8：设置页/诊断页都是主窗口内容切换，永远只有一个 Window。

### 2.4 构建链修复

`android/pyproject.toml` 去掉通用 `requires` 里的裸 `"toga"`，改为钉死 `toga-core==0.5.7`（并把 requests / markdown / beautifulsoup4 全部锁版本）。原因：Chaquopy 在 Android 上 `sys.platform=="linux"`，裸 `toga` 被解析为 0.2.15 元包，其 METADATA 的 `toga-gtk; sys_platform=="linux"` 连带装入 0.2.15 的 GTK 后端，形成实测到的两代混装。现在每个 tag 构建出的 `requirements-common.imy` 可复现，且 CI 新增 `verify_apk.py --strict` 门禁会拒绝任何混装。

## 三、电脑端新功能

`core/stardust.py`（纯标准库、零 GUI / 零网络、三端字节一致）：

| 能力 | 接口 | 三端入口 |
| --- | --- | --- |
| ✦ 星尘卡 | `build_echo_card` | 桌面「生成本轮星尘卡」/ CLI `--echo` / 安卓每轮回答后自动附卡 |
| 📐 上下文预算 | `plan_trim` | 桌面「上下文预算裁剪」/ CLI `--budget N` |
| 📦 `.starry` 存档 | `pack_archive` / `unpack_archive` | 桌面「导出/导入」/ CLI `--archive` / `--restore` |
| 🩺 环境自检 | `core.cli._run_doctor` | 桌面「运行环境自检」/ CLI `--doctor` |

存档带 `magic / version / payload / SHA-256 checksum`，篡改、版本不符、结构损坏一律拒绝；导入前自动备份原文件为 `*.bak-<时间戳>`。CLI 与桌面共用同一份实现，避免口径漂移。

## 四、三端同源与发版工程化

- `scripts/sync_core.py`：把 `core/` 同步到 `android/core/`，白名单排除 4 个桌面专属模块；`--check` 供 CI 用。实测 **41 个文件完全一致、0 漂移**。
- `scripts/check_core_parity.py`：版本单一真源（3 处声明）+ 同源 + 全量语法门禁；`--expect-version` 校验 tag。
- `scripts/make_release.py`：产出 `releases/星语Starry-v12.0.0/`（全部源码、主文件、全部 docs/*.md、.github、构建脚本）+ 同名 zip + `MANIFEST.md` + `checksums.txt` + `RELEASES.md` 索引；白名单排除 `config.json` / `*.keystore` / `.env`。
- `.github/workflows/release.yml`：tag `vX.Y.Z` → 门禁 → 全量自测 → 快照 → Release；三个 workflow 共用 `concurrency` 串行化，一律 `append_body`，tag 规则收紧为 `v*.*.*`。

## 五、产物与验证

| 产物 | 状态 | 验证 |
| --- | --- | --- |
| `dist/星语Starry-CLI.exe` | **本机真实构建**（PyInstaller 6.22.3，PE32+ 16MB） | `--version/--platform/--doctor/--budget/--archive/--restore` 退出码全 0；GBK 中文控制台正常 |
| `dist/星语Starry-CLI-v12.0.0.deb` | **本机真实构建**（纯标准库 ar+tar.gz，173KB） | 独立解析 ar / control / data / md5sums / wrapper 全通过 |
| Android 修复版 APK | **源码已修复，二进制由 CI 产出** | 见下节「已知限制」 |
| v11.5 历史 APK | 完整保留（51,980,670 字节） | 鉴定报告 21 通过 / 1 失败（依赖混装） |

**测试**：`selftest.py` 桌面全量 **779 通过 / 0 失败**、`tests/test_android_v12.py` 37/37、`tests/test_v12_features.py` 63/63、`android/test_app_logic.py` 16/16、`scripts/check_core_parity.py` 全通过；EXE 6 项冒烟全 0。合计 **895 项回归全绿**。

## 六、已知限制（如实说明，不做虚假承诺）

1. **本机无法重新编译并签名 APK**。当前环境是 Windows，没有 JDK 17、Android SDK / NDK、Gradle 与 `apksigner`；APK 一旦替换内部 `app.imy`，v1 的 `MANIFEST.MF` 摘要与 v2/v3 APK Signing Block 都会失效，必须重签。交付一个我无法验证能安装的签名 APK，比诚实说明更糟，因此**没有伪造 v12.0 APK**。修复后的签名 APK 由 `.github/workflows/build-android.yml` 在推 `v12.0.0` tag 时于 GitHub 运行器真实编译产出（含 `apksigner verify` + `verify_apk.py --strict`）。
2. **无真机 / 无模拟器**，因此不能声称「真机实测不闪退」。可保证的是：8 项缺陷均有文件行号与本机复现依据，且用**真实 core + 忠实复刻 Toga 0.5.7 行为的 UI 替身**跑通 37 项集成回归；真机 UI 渲染仍需设备验证。
3. **deb 形态变化**：v11.5 的 deb 内是 PyInstaller 编译的 20MB ELF 二进制（免 Python 依赖）；本机无法交叉编译 Linux ELF，v12.0 deb 改为「v12.0 真实源码 + 系统 python3 启动器」，`control` 显式声明 `python3-requests / bs4 / markdown`。免依赖 ELF 版由 CI 的 ubuntu job 产出。
4. **私钥**：`android/starry-release.keystore` 曾随源码分发；v12.0 的发布快照已按白名单排除，CI 改用仓库 Secret。
5. **【已解决】全量自测曾长期报 12 项失败，现已定位并修复为 779 / 0**。
   早期把它判为「运行环境依赖」是**错误的**：装好 Playwright Chromium 后失败依旧
   （767 / 12），补 `USERPROFILE` 隔离后仍剩 5 项。真实根因是 `core/gateway.py`
   把统计 / 预算固定在 `~/.starry`，而 Windows 上 `os.path.expanduser("~")` 读
   `USERPROFILE`，自测里 `HOME=tmp` 的隔离完全无效，测试读到真实用户目录的累计数据。
   v12.0 收尾修复：
   - 新增**可选** `STARRY_DATA_DIR` 注入点（未设置时路径逐字不变、不迁移用户数据），
     自测各段独立隔离；
   - 新增 `chromium_kernel_available()`，使「一键安装内核」在已装好 Playwright
     内置 Chromium 时直接反馈、不再重复下载 100+ MB；
   - 桌面全量自测 **779 通过 / 0 失败**，无需任何外部环境变量即可复现。
   CI 仍保留 `playwright install chromium`。详见 `docs/评审纪要_v12_0.md` P6 / P7。

## 七、升级指引

- Windows：直接用新的 `星语Starry-CLI.exe`；`--archive 备份.starry` 可先导出旧数据。
- Linux / UOS：`sudo dpkg -i 星语Starry-CLI-v12.0.0.deb`，`starry --version` 应输出 12.0.0。
- 安卓：安装新签名 APK 前**先卸载旧包**（签名密钥可能不同）；首次启动若异常，点「诊断」查看日志。
- 历史大版本 v11.5.0 完整快照保存在 `releases/星语Starry-v11.5.0/`，未覆盖、未删除。
