# 星语 Starry · v11.4.0 发布说明（GitHub Releases 风格）

> 包名 `com.starry.starryandroid` ｜ 版本 **11.4.0** ｜ 桌面/安卓/CLI 版本号一致
> 发布日期：2026-11-06 ｜ 上一版：v11.3.0（安卓闪退根治 + 收藏/总结/批量导出）
> 本版主题：**电脑端新增功能 —— 消息引用（Quote）/ 分支对话（Branch）**，并延续全链路复审与多端分发。

---

## ✨ 本版新增

### 💬 消息引用（Quote）
- 可把**任意一条历史消息**格式化为 Markdown 引用块，作为新问题上下文一起发给模型，让回答"针对引用作答"
- 自动过滤系统提示 / 空内容、超长截断（300 字）、多行逐行 `>` 前缀、多模态消息取文本部分
- 命令面板两条入口：**「💬 引用消息追问」**（消息选择器选任意一条 + 输入框提问）、**「↩️ 引用最后回复」**（一键引用末条 AI 回复）

### 🌿 分支对话（Branch）
- 从会话**某条消息（含）处**复制前缀历史，生成一条全新会话继续对话，**原会话不变**
- 逐条浅拷贝隔离、继承标签、收藏按下标过滤、记录 `branched_from` 溯源、自动切换到新会话
- 命令面板两条入口：**「🌿 分支对话」**（选分支点开新会话）、**「🌱 分支列表」**（查看并跳转派生分支）

> 全部逻辑落在 `core/sessions.py`，**桌面与安卓同源共用、零 Qt / 零安卓依赖**；`core/sessions.py` 与 `android/core/sessions.py` 保持字节一致。

## 🧪 测试与验证

| 项目 | 结果 |
|------|------|
| `test_v11_4_pc.py` | **9/9 全绿**（引用格式化/过滤/截断/多行/多模态、组合提示各分支、越界、分支复制前缀/元数据继承/深拷贝隔离/持久化/向后兼容） |
| `test_v11_3_pc.py` 回归 | 4/4 全绿 |
| 安卓 core 全量编译 | 通过（`android/core/*.py` 全量 `py_compile`） |
| UI 无头验证 | `MessagePickerDialog` 引用/分支两模式 Qt offscreen 导入与渲染通过 |
| CLI `--version` | 打印 `星语 Starry 11.4.0（命令行版）` |
| `core/sessions.py` AST | 33 个类方法归属正确，模块级纯函数独立，`delete/append/messages` 未游离出类 |

## 🔧 版本号统一（四处一致 11.4.0）

`APP_VERSION`（桌面/安卓 `core/config.py`）、`CLIENT_INFO.version`（桌面/安卓 `core/mcp.py`）、
`android/pyproject.toml`（2 处）、`selftest.py`（4 处断言）全部同步；CLI 与 `--version` 输出一致。

## 📱 安卓 APK（继续保障"开箱可用"）

- 在 v11.3 **安卓闪退根治**基础上，沿用已验证的干净重建链路：
  `rm -rf build` → 系统 **JDK17**（`JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`）→
  gradle **wrapper 9.5.0** → `assembleRelease` → `zipalign -p 4` → `apksigner sign`（别名 `starry`）
- 产出可安装签名包 **`星语 Starry-11.4.0.apk`**（v2/v3 签名校验通过）
- 核验 APK 内 `core/config.pyc` 版本为 **11.4.0**，全新 `core/sessions.py`（含引用/分支逻辑）已打入
- `android/README.md` 与 `docs/使用指南_Android_APK.md` 的安装/签名命令同步到 11.4.0

## 📦 分发物（每版独立带后缀文件夹 + zip）

| 文件夹 / zip | 关键内容 |
|---|---|
| `星语Starry-v11.4` | 整体项目（源码 + 全部 docs/md + 主文件 + README/CHANGELOG） |
| `星语Starry-v11.4-android` | 含**已签名 APK**（单独拎到 `android/` 根 + `android/dist/`） |
| `星语Starry-v11.4-linux-cli` | 含 Linux CLI 二进制（已冒烟测试可运行） |
| `星语Starry-v11.4-windows-cli` | 含 `build_windows_cli.ps1`（无 Wine 环境未出 exe，与历史一致） |
| `星语Starry-v11.4-uos` | 含 UOS / Debian `.deb` 安装包 |

> 历史大版本 **v7.6 / v8.0 / v9.0 / v10.0 / v11.0 / v11.1 / v11.2 / v11.3** 文件夹与 zip 全部保留。

## 🚀 提交与 Releases

- `git commit` + `tag v11.4.0`（源码/文档/脚本入库，APK 与虚拟环境按 `.gitignore` 忽略）
- `.github/workflows/build-android.yml`：推送 `v*` tag 即在 GitHub 运行器**真实编译并签名 APK、自动发布 Releases**

## 📄 全链路评审文档

`docs/` 下：`代码安全性评估_v11_4.md`、`HR复审_v11_4.md`、`美术复审_v11_4.md`、
`资深程序员复审_v11_4.md`、`GitHub复审_v11_4.md`、`创造力复审_v11_4.md`、
`API开放文档_v11_4.md`、`评审纪要_v11_4.md`、`RELEASE_NOTES_v11_4.md`。

## ⬆️ 升级方式

1. 卸载旧包 → 安装 `星语 Starry-11.4.0.apk`（安卓）；或替换桌面 / CLI 工程目录
2. 桌面端按 `Ctrl+K` 打开命令面板，输入「引用」或「分支」即见新增命令
3. 旧 `sessions.json` **无需迁移**：新增 `branched_from` 字段缺省读取，历史数据完全兼容
