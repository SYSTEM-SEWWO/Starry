# 星语 Starry · Android 版

> 基于 **BeeWare / Toga** 的原生安卓封装。对话、深度思考流、长期记忆、智能体工具
> 等全部能力**直接复用桌面版的纯 Python 核心 `core/`**，与桌面端、命令行端共用
> 同一份引擎代码——不是另写一套伪实现。

## 特性
- 原生安卓界面（聊天 + 思考可视化卡片 + 设置页）
- 流式「深度思考」呈现（模型推理过程实时滚动）
- 长期记忆本地持久化（`~/.config/ai-desktop-assistant/`）
- 智能体模式：调用内置工具（读文件 / 执行命令 / 搜索等）
- 接入十余家 OpenAI 兼容服务商（智谱、硅基、DeepSeek、阿里百炼、Groq…）
- 后台线程联网，主线程安全回写 UI（符合安卓严格的主线程网络限制）

## 目录
```
android/
├── pyproject.toml              # Briefcase 工程配置
├── starryandroid/              # Toga 原生 GUI 封装层（app.py）
│   ├── app.py                  # 主程序：聊天 / 思考可视化 / 设置
│   └── resources/starryandroid.png
├── core/                       # 从桌面版移植的纯 Python 核心（已剔除 PyQt 依赖）
└── .github/workflows/build-android.yml   # CI 一键构建签名 APK
```

## 本地构建 APK（需 Android SDK/NDK + JDK17）

> 工程固定使用 **Briefcase 0.4.7**（其 Gradle 模板要求 `compileSdk/build-tools 36`）。
> `briefcase package android` 产出的是**未签名** release APK，必须经过
> `zipalign` + `apksigner` 签名后才能安装。

```bash
export ANDROID_HOME=/opt/android-sdk
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
pip install "briefcase==0.4.7"

cd android
briefcase create android
briefcase build  android
briefcase package android -p apk          # 产物：dist/星语 Starry-<版本>.apk（未签名）

# 自签名（演示用；上架 Play 请换自有发布密钥）
BUILD_TOOLS=$ANDROID_HOME/build-tools/36.0.0
keytool -genkey -v -keystore starry-release.keystore -alias starry \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass starrypass -keypass starrypass \
  -dname "CN=Starry, OU=Starry, O=Starry, L=CN, S=CN, C=CN"
$BUILD_TOOLS/zipalign -p 4 dist/星语\ Starry-11.5.0.apk /tmp/starry-aligned.apk
$BUILD_TOOLS/apksigner sign --ks starry-release.keystore --ks-key-alias starry \
  --ks-pass pass:starrypass --key-pass pass:starrypass \
  --out dist/星语\ Starry-11.5.0.apk /tmp/starry-aligned.apk
$BUILD_TOOLS/apksigner verify dist/星语\ Starry-11.5.0.apk   # 应显示 VERIFY_OK
```
把签名后的 `.apk` 拷到手机，在「设置 → 安全 → 安装未知应用」中允许对应来源，
点击 APK 即可安装开箱使用。包名 `com.starry.starryandroid`，版本 11.5.0。

## 一键构建脚本
```bash
bash ../scripts/build_android_apk.sh     # 自动装 SDK/NDK + 签名，产出已签名 APK（首次需联网下载约 1.5GB）
```

## CI 自动发布（推荐）
推一个 tag 即可在 GitHub Actions 中自动构建、**签名**并发布到 Releases：
```bash
git tag v11.5.0 && git push --tags
```
详见 `.github/workflows/build-android.yml`。该流程在标准的 GitHub 运行器上
用 Briefcase 0.4.7（Chaquopy + Gradle）真实编译 Python 核心，并显式用
`zipalign + apksigner` 自签名，产出**可直接侧载安装**的 APK——这是本项目
「像 GitHub Releases 一样好用」的官方分发方式。

## 测试与质量保障

### 闪退根因与修复（安卓必读）
安卓 APK 曾长期**安装后闪退（启动即崩）**，经过真机等价环境（APK 内真实
toga 0.5.7 + android/core）逐步排查，确认并修复了三类根因：

#### ① 首要根因：`app.py` 的 toga 导入在 toga 0.5.7 下直接 `ImportError`（模块加载即失败）
> 旧代码：`from toga.style import Pack, Column, Row`
> 但 **toga 0.5.7 已从 `toga.style` 移除 `Column` / `Row`**（`direction` 只接受
> 字符串 `"column"` / `"row"`；`LEFT/RIGHT/CENTER/BOLD` 改由 `toga.style.pack` 导出）。
> 该 import 在真机会抛 `ImportError: cannot import name 'Column' from 'toga.style'`
> → **模块根本加载不出来，连 `startup()` 都进不去**，更到不了之前修的 `visibility`
> 那一步。这也是前几版「修了 visibility 还是闪退」的真正原因。

> 修复：`from toga.style import Pack` + `from toga.style.pack import LEFT, RIGHT, CENTER, BOLD`
> + `from toga import Column, Row`，并把 `direction=Column/Row` 改为 `direction="column"/"row"`。
> 已用 APK 内真实 toga 0.5.7 做权威 import 验证，确认模块可加载。

#### ② 设置页新建第二个窗口 → `RuntimeError`（安卓仅允许一个窗口）
> 安卓 `toga_android` 的 `Window.set_app` 在 `len(app.windows) > 1` 时直接抛
> `RuntimeError("Secondary windows cannot be created on Android")` → 一旦点「设置」即崩。
> 修复：不再 `toga.Window(...)`，改为**主窗口内页面切换**（聊天页 ↔ 设置页，带「返回」），
> 永远只存在一个窗口。

#### ③ 事件循环被孤儿循环覆盖 → 发消息后界面无反应
> 旧代码 `self.loop = asyncio.get_event_loop()` 会另起一个**从未运行的孤儿循环**，
> 导致 `call_soon_threadsafe` / `run_in_executor` 的回调永远不被调度（发送后界面不动）。
> 修复：直接使用 Toga 提供的运行循环 `self.loop`（`self._impl.loop`，安卓为 AndroidEventLoop），
> 不重新赋值。

#### 附带修复的同类隐患（v11.0 已修，避免功能失效）
- `visibility=False` → `visibility="hidden"`（0.5.7 仅接受 `"visible"`/`"hidden"`）。
- `Switch` / `Selection` 回调用 `on_change`（非 0.4.x 的 `on_toggle`/`on_select`）。
- 「发送」`on_send` 改为同步函数，内部用 `loop.run_in_executor` 跑网络。

### 自动化逻辑测试
`test_app_logic.py` 用轻量 fake `toga` 替换界面层，**跑真实的 `core` 逻辑**，
覆盖：启动构建（原崩溃点）、普通流式对话、深度思考开关、智能体模式发送、
设置窗口与保存。运行：
```bash
cd android && python3 test_app_logic.py     # 期望：14/14 通过
```

### 真机自测清单（沙盒无 /dev/kvm，无法跑模拟器，需真机或带 KVM 的环境验证 UI 渲染）
1. 安装签名 APK，桌面出现「星语 Starry」图标，点击**不闪退**、进入聊天主界面。
2. 未配置 Key 时状态栏显示「未配置」，首屏有欢迎语。
3. 「设置」填入服务商 + API Key + 模型 → 保存 → 状态栏变为「已就绪」。
4. 输入问题 → 点「发送」→ 出现「我：…」气泡与「星语：…」回答（联网正常时）。
5. 开启「深度思考」→ 思考卡片显示推理过程；开启「智能体」→ 可调用工具。
6. 旋转屏幕 / 切后台再回前台，界面不崩、状态保持。

## 与桌面版的关系
| 能力 | 桌面版 (PyQt5) | 命令行版 | 安卓版 (Toga) |
|------|---------------|----------|---------------|
| 流式对话 | ✅ | ✅ | ✅ |
| 深度思考可视化 | ✅ 液态玻璃悬浮球 | 文本流 | ✅ 思考卡片 |
| 长期记忆 | ✅ | ✅ | ✅ |
| 智能体工具 | ✅ | ✅ | ✅ |
| 网页接入(Playwright) | ✅ | ✗ | ✗（移动端不适用）|
| REA 逆向工程 | ✅(宿主) | ✅(宿主) | 说明见设置（需 Node 环境）|
