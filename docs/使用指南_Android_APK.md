# 使用指南 · 星语 Starry 安卓 APK（v11.5.0）

> 面向**手机用户**：如何拿到 APK、安装、配置并用上「深度思考 / 长期记忆 / 智能体」。
> 开发者侧载与源码构建见文末「从源码构建 APK」。

## 1. 星语安卓版是什么

- 一个**原生安卓 App**（基于 BeeWare / Toga 封装），直接装在手机上，无需电脑。
- 与桌面版、命令行版**同一套 AI 引擎**：把各家大模型（DeepSeek、智谱、硅基、阿里百炼…）
  接进来，支持**流式对话、深度思考过程可见、长期记忆、智能体工具调用**。
- 界面简洁：顶部状态栏 + 对话区 + 思考卡片 + 底部输入框与开关。

## 2. 获取 APK

**方式 A · 从 Releases 下载（推荐，开箱即用）**
1. 打开项目 GitHub 仓库的 **Releases** 页面。
2. 找到最新 `v11.5.0`（或更新）条目，下载 `星语 Starry-11.5.0.apk`。
3. 该 APK 由仓库 CI 在 GitHub 运行器上**真实编译并签名**，可直接侧载。

**方式 B · 自己构建（开发者）**：见第 6 节。

## 3. 安装（侧载）

1. 把 `.apk` 传到手机（微信文件传输 / 数据线 / 网盘）。
2. 点击 APK → 若提示「禁止安装未知应用」，按提示进入**设置 → 允许来自此来源的应用**。
3. 返回继续安装，约几秒完成；桌面出现「星语 Starry」图标。

> 侧载是安卓通行做法，仅本次安装来源需授权；装完可在设置收回。

## 4. 首次配置（必做）

1. 点底部 **设置** 按钮。
2. **服务商**：选一个（如「智谱 AI · GLM-4-Flash（免费）」或「硅基流动（免费）」）。
3. **API Key**：去对应官网免费注册并创建 Key 后粘贴：
   - 智谱：https://open.bigmodel.cn/usercenter/apikeys
   - 硅基：https://cloud.siliconflow.cn/account/ak
   - DeepSeek：https://platform.deepseek.com/api_keys
4. **模型**：选该服务商下的模型（默认已填）。
5. **思考强度**：`off / low / medium / high`。
6. 点 **保存**；状态栏显示「已就绪 · 服务商 …」。

## 5. 日常使用

- **对话**：底部输入问题 → 发送，回答流式出现。
- **深度思考**：开启「深度思考」开关，回答前显示「✦ 思考中…」并实时滚动推理过程。
- **智能体**：开启「智能体」开关，可调用内置工具（读文件 / 执行命令 / 搜索）。
- **长期记忆**：自动开启，记忆存于应用私有目录，不上传。

### 常见问题

| 问题 | 处理 |
|------|------|
| 保存后仍「未配置」 | 确认 Key 已填且服务商/模型非空 |
| 点发送没反应 | 检查网络；确认未在上一条处理中 |
| 思考卡片不出现 | 模型需支持 `reasoning_content`（如 deepseek-reasoner / qwq / glm-z1） |
| 智能体执行命令失败 | 手机沙盒限制；文件/命令类工具在安卓可用但有系统约束 |
| 安装后打开异常/白屏 | v11.3 起启动异常不再静默闪退，会显示「⚠ 错误窗口 + logcat 提示」，按屏上说明排查并反馈 |

## 6. 从源码构建 APK（开发者）

前置：Linux/macOS + JDK 17 + Android SDK/NDK（约 1.5GB 下载）。

```bash
export ANDROID_HOME=/opt/android-sdk
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
pip install briefcase
bash scripts/build_android_apk.sh        # 自动装 SDK/NDK 并产出 APK
# 或直接：briefcase create android && briefcase build android && briefcase package android
```

产物：`android/dist/星语 Starry-11.5.0.apk`（已用 `zipalign` + `apksigner` 做 v2/v3 签名，可直接安装）。
> 干净重建要点（v11.3 起固化）：`rm -rf build bin logs` 消除陈旧缓存 → 系统 **JDK 17**（briefcase 步骤期间**不要**设 `_JAVA_OPTIONS`，否则 javac 版本探测被污染）→ 用 gradle **wrapper 9.5.0**（`./gradlew assembleRelease`，非系统 9.3.0）→ `zipalign -p 4` → `apksigner sign`。详见 `android/README.md`。

**CI 自动发版**：推 tag 即在 GitHub Actions 自动构建并发布到 Releases：
```bash
git tag v11.5.0 && git push --tags
```

## 7. 与桌面 / 命令行版的关系

三端共用同一份 `core/` 引擎，能力一致，差异仅在 UI 与运行环境。桌面「液态玻璃悬浮球」
在安卓端以「思考卡片」近似还原，未来可用 WebView 做 1:1 玻璃拟态。
