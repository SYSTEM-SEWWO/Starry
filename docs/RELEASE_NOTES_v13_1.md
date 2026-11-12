# 发布说明 · 星语 Starry v13.1.0

> 主题：**GUI 版 EXE + Skills Hub（兼容 GitHub / Claude Code / WorkBuddy）+ 技能更新功能**
> 上一版 v13.0.0 的全部能力、文档与历史快照完整保留。
> 兼容矩阵、接口签名与安全边界见 `docs/API开放文档_v13_1.md`。

## 1. 用户诉求与本版交付

| 用户原话 | 本版交付 |
| --- | --- |
| 「还有gui版本的exe」 | `dist/星语Starry.exe`（`console=False`，双击即用、托盘常驻）；`starrystar.spec` 真实构建；随 tag 进 GitHub Releases |
| 「加入hub兼容GitHub跟claud code等主流 Skills」 | `core/hub.py` 统一模型；兼容 `SKILL.md` + YAML frontmatter、`hub.json`、星语自有 JSON；自动扫描 `~/.claude/skills/`、`.github/skills/`、`~/.workbuddy/skills/` 等；`ui/hub_dialog.py` 桌面技能中心 |
| 「更新功能」 | 两条独立更新线：程序版本更新（`update.json`，v13.0 已有）与**技能更新**（`hub.json`，本版新增）；CLI / GUI / CI 全链路接入 |

## 2. 新增能力

### 2.1 Skills Hub（纯逻辑，`core/hub.py`）

- 零第三方依赖：手写极简 YAML frontmatter 解析器，三端（EXE / deb / Android）同源可跑。
- 支持内联逗号、YAML 列表续行、内联数组、`|` / `>` 块标量、一层嵌套映射。
- 统一 Skill 模型：`id / name / description / body / source / format / path / tools / version / tags / meta / sha256`。
- 多源发现 `default_sources()` / `scan_dir()` / `scan_sources()`，按 id 去重、按来源排序。
- 清单 `build_hub_manifest()` / `validate_hub_manifest()`（magic / schema / digest / sha256 严格校验）。
- 更新判定 `diff_skills()` / `check_hub_update()`：新增 / 变更 / 移除 / 未变四分类。
- `Hub` 门面类：注册源 → 发现 → 搜索 → 归一化 → 更新判定。
- `bundled_skills_dir()`：源码 / PyInstaller onefile / deb 三种形态统一取到 `skills/`。

### 2.2 桌面与 CLI 接入

- `ui/hub_dialog.py`：左右分栏技能中心（搜索 / 详情 / 添加源 / 导入 / 检查更新 / 导出清单），
  与 v13.0 工作台共用同一套浅色 QSS。
- 命令面板新增 `hub` / `hub_update` 两条命令。
- CLI 7 个新参数：`--hub` / `--hub-search` / `--hub-info` / `--hub-update` /
  `--hub-manifest` / `--hub-source` / `--hub-import`。
- `skills/` 三份示例技能（Claude Code 风格 / GitHub Copilot 风格 / 扁平 `*.skill.md`）。

### 2.3 GUI EXE 与可自动化验证（本版重点）

- `starrystar.spec` 补齐 v12/v13/v13.1 懒加载模块并把 `skills/` 打进 `datas`。
- `main.py` 新增 `--version` / `--selftest --out r.json`：窗口程序无需控制台也能自证。
- `scripts/smoke_gui_exe.py`：启子进程、读落盘结果、逐项断言；自检包含
  「随包 `skills/` 已打进产物」，防住「EXE 能启动但 Hub 是空的」。
- `scripts/smoke_cli_exe.py`：CLI EXE 14 项子进程冒烟（含 v13.1 全部 Hub 参数）。
- `.github/workflows/build-windows.yml` 新增 `build-gui-exe` job，两份 EXE 一同进 Release。

### 2.4 自动更新清单修正

`gen_update_manifest.py` 此前「同平台取体积最大者」，本版 windows 同时发布
CLI EXE 与 GUI EXE 时会把 CLI 悄悄丢掉。现改为**收录全部正式资产**
（仅按文件名排除 debug / 临时包），并按「平台顺序 + 文件名」稳定排序；
`--update-check` 同步改为列出该平台全部资产，不再只显示第一个。

## 3. 修复的真实缺陷（12 项，详见评审纪要）

1. `allowed-tools: Read, Bash, Grep` 被解析成字符串 → 统一归一化。
2. `metadata.version` 嵌套映射未读取 → 回退读取。
3. 清单条目被加 `remote:` 前缀重造 id → 往返比对全部错位 → 改为沿用原 id。
4. 用空正文**重算**的 sha256 比对 → 每个技能都判变更 → 改用清单声明的摘要。
5. 扁平 `*.skill.md` 文件名覆盖 frontmatter `name` → 调整优先级。
6. `_as_list(dict)` 产生垃圾条目 → 拒绝 dict。
7. 「缺文件」用例因参数未接入而**假绿** → 接入后核实真实报错。
8. spec 接入断言过松 → 收紧为精确匹配 4 个模块 + datas + workflow。
9. CLI EXE 中文输出为 cp936，冒烟按 UTF-8 解码导致 6/14 误判 →
   EXE 尊重 `PYTHONIOENCODING`，冒烟多编码候选解码 → 14/14。
10. v13.0 遗留 **P0-2 测试与发版号耦合** → 改 SemVer 下限断言，
    `release.yml` 生成器自测改动态注入版本，本版关闭该 P0 项。
11. **v13.0 快照内 `RELEASE_NOTES.md` 只有一行占位文本**（已核实历史文件）：
    发版脚本拼的是 `RELEASE_NOTES_v13_0_0.md`，项目实际命名为
    `RELEASE_NOTES_v13_0.md`，名字不匹配时静默退化成占位；
    而 `release.yml` 用这个文件作为 GitHub Release 正文 → 完整发布说明没进产物。
    现改为三级回退（三位版本 → 两位版本 → 根目录说明），并补单测锁死。
12. `make_release.py` 目录白名单漏 `skills/` → 快照会缺示例技能；已补入并加断言。

## 4. 工程化

| 项 | 结果 |
| --- | --- |
| 版本单一真源 | `13.1.0`（`core/config.py` / `core/mcp.py` / `android/pyproject.toml` 三处） |
| 三端同源 | `sync_core.py` 同步 **45 个文件**，`--expect-version 13.1.0` 门禁通过 |
| CLI EXE | 单文件，PyInstaller 6.22.3；`PYTHONIOENCODING` 兼容；14/14 子进程冒烟 |
| GUI EXE | 单文件 `console=False`；13/13 子进程冒烟（含 offscreen 自检 14/14） |
| Linux deb | 纯标准库 ar；66 个 data 文件 / 3 个 ar 成员；含 `core/hub.py` 与 `skills/` |
| workflow | 5 个 YAML 全部解析通过；`build-windows.yml` 新增 GUI job |
| 快照白名单 | `make_release.py` 补入 `skills/`，避免「完整快照缺示例技能」 |
| 完整快照 | `releases/星语Starry-v13.1.0/` **395 个文件** + 同名 zip（约 112 MB；含 90 MB GUI EXE，精确字节以 `SHA256SUMS-v13.1.0.txt` 首行为准）；历史三版保留 |
| 发布快照终验 | `scripts/verify_release.py --version 13.1.0` → **31/31 通过**（zip CRC / 逐文件哈希 / SHA256SUMS 6 条 / 敏感文件 0 / 索引 / 非占位发布说明） |

## 5. 实测回归

| 套件 | 结果 |
| --- | --- |
| `selftest.py`（offscreen 桌面全量） | **779 通过 / 0 失败** |
| `tests/test_v12_features.py` | 63/63 |
| `tests/test_v13_features.py` | 172/172 |
| `tests/test_v13_1_hub.py` | **131/131** |
| `tests/test_android_v12.py` | 37/37 |
| `android/test_app_logic.py` | 16/16 |
| GUI EXE 子进程冒烟 | 13/13（内含自检 14/14） |
| CLI EXE 子进程冒烟 | 14/14 |
| 合计源码级回归 | **1198 项通过，0 失败** |

逐项哈希与资产字节数见 `releases/SHA256SUMS-v13.1.0.txt` 与
`docs/交付资产与财务清单_v13_1.md`。

## 6. 资产

| 资产 | 位置 |
| --- | --- |
| Windows CLI EXE | `releases/assets/v13.1.0/windows/星语Starry-CLI-v13.1.0.exe` |
| **Windows GUI EXE（新增）** | `releases/assets/v13.1.0/windows/星语Starry-GUI-v13.1.0.exe` |
| Linux / UOS deb | `releases/assets/v13.1.0/linux/星语Starry-CLI-v13.1.0.deb` |
| 离线更新清单 | `releases/assets/v13.1.0/update.json`（windows ×2 + linux ×1） |
| Android APK | `releases/assets/v13.1.0/apk/` **仅 README，不含 APK 二进制** |
| 完整快照 | `releases/星语Starry-v13.1.0/` + 同名 zip |

历史 `v11.5.0` / `v12.0.0` / `v13.0.0` 快照与资产**全部保留**。

## 7. 已知限制（不得写成「已完成」）

1. 本机缺 JDK 17 / Android SDK / NDK / Gradle / apksigner，**不产出 v13.1 签名 APK**；
   不伪造、不重签、不拿历史包冒充。真机 / 模拟器未跑，不能声称实测不闪退。
2. 当前目录**不是 git 仓库**；workflow 已备好，需用户 `git init` + 首次提交 + remote + tag 才触发。
3. `releases/星语Starry-v11.5.0/` 含历史 `starry-release.keystore`，**公开分发前必须移除或轮换**。
4. `hub.json` / `update.json` 的 `digest` 是**完整性校验，不是签名认证**；Hub 不自动下载 / 安装技能。
5. GUI 自检是 offscreen 装配验证，**未做真人交互点击测试**。
6. frontmatter 解析器是有意限定的 YAML 子集，不支持锚点 / 复杂嵌套。
7. 两个新对话框尚未跟随暗色主题（美术复审登记）。

## 8. 复审结论

代码安全性评估（通过，2 项已知限制）· HR 复审（A）· 美术复审（A-）·
资深程序员复审（通过，5 个标识类缺陷靠往返测试逼出）· GitHub 复审（通过）·
创造力复审与评价（**A**，上版 A-）· API 开放文档 · 使用指南三份 ·
交付资产与财务清单（APK 单列）· 项目结构与提交指南 · 评审纪要。

## 9. 升级方式

无需迁移配置：v13.1 只新增模块与参数，旧 `config.json`、`.starryproj`、
`.starry` 存档、`update.json` 格式全部兼容。直接替换 EXE / 安装新 deb 即可。
