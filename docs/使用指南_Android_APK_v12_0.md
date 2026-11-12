# 星语 Starry v12.0.0 · 安卓 APK 使用指南

> 适用：Android（Toga 原生 UI + Chaquopy / CPython 3.11），最低目标 API 34。
> 本版主题就是**解决「安装后闪退」**，所以本指南先讲「怎么拿到包」，
> 再讲「怎么逐项确认核心功能真的可用」。

---

## 1. 先读这里：v12.0 签名 APK 的当前状态

| 项 | 状态 |
| --- | --- |
| 安卓源码修复（F1–F8 + 依赖钉版本） | ✅ 已完成，见 `APK鉴定与闪退根因报告_v12_0.md` |
| 本机集成回归（真实 `core` + 忠实 UI 替身） | ✅ 37/37 + 16/16 |
| **v12.0 签名 APK 二进制** | ⏳ **由 CI 在推 `v12.0.0` tag 时真实产出** |
| 真机 / 模拟器实测 | ⏳ 待设备验收 |

本机是 Windows，缺 JDK 17 / Android SDK / NDK / Gradle / `apksigner`，
**无法真实编译并签名**；直接替换历史 APK 内的 `app.imy` 会让 v1 摘要与
v2/v3 签名全部失效，得到一个装不上的包。因此本版**没有伪造 APK**。

获取方式：

```bash
git tag -a v12.0.0 -m "v12.0.0"
git push origin v12.0.0
# → GitHub Release 资产：星语Starry-Android-v12.0.0.apk
```

下载后放入 `releases/assets/v12.0.0/apk/`。开发者本地构建条件与命令见该目录的 `README.md`。

---

## 2. 安装

1. **先卸载旧版本**（v11.5 及更早）。签名密钥可能不同，覆盖安装会报
   `INSTALL_FAILED_UPDATE_INCOMPATIBLE`。卸载前建议先在旧版导出 `.starry` 存档。
2. 系统设置里允许「安装未知来源应用」（侧载必需）。
3. 点击 APK 安装；首次启动会请求网络权限（`INTERNET` / `ACCESS_NETWORK_STATE`）。
4. 冷启动应看到欢迎语：
   `你好，我是星语 Starry 12.0.0。已接入 …`，而不是黑屏或直接退回桌面。

> 如果仍出现退出：不要反复重装，直接看第 5 节「诊断页」把信息复制出来。

---

## 3. 首次配置

进入「设置」（**主窗口内内容切换，不会新开窗口**）：

| 项 | 说明 |
| --- | --- |
| 服务商 | 只列移动端可用的 API 型服务商；网页接入型在手机上不可用，已过滤 |
| 模型 | 随服务商联动刷新；自定义模型若不在列表里，会自动回落到首个选项而**不会崩溃**（F3 修复） |
| API Key | 保存在应用私有目录，随卸载清理 |
| 主题 | light / dark，与桌面主色对齐 |
| 字号 | 标准 1.0 / 大 1.15 / 超大 1.3 |
| 深度思考 | 显示推理分片 |
| 智能体 | 允许调用本地工具 |

配置目录由 `startup()` 把 Toga 的 `app.paths.config` 注入为
`STARRY_CONFIG_DIR`，落在**应用私有可写目录**；若该目录不可用，
`core/config.py::_safe_makedirs()` 会逐级回退到 `HOME/.config` 与临时目录，
**任何情况下都不会因读配置抛异常导致闪退**（F1 / F2 修复）。

---

## 4. 核心功能核对清单

用户要求「保证 APK 所有核心功能可以用并且测试完成」。以下逐项列出
**功能 → 实现方式 → 验证依据 → 是否还需真机确认**。

| # | 核心功能 | 实现 | 本机验证 | 真机待确认 |
| --- | --- | --- | --- | --- |
| 1 | 冷启动不闪退 | `startup()` 全程 try + 致命错误页 + `AppConfig.load()` 永不抛 | ✅ `[F1] startup 成功且未抛异常`、`启动流程无任何异常记录`、`不可写私有目录时仍返回可用路径` | 需 |
| 2 | 配置读写 | `STARRY_CONFIG_DIR` 注入 + 三级回退 + `save()` | ✅ `[F2] 配置目录落在 Android 私有目录`、`保存设置成功（api_key 写入）` | 需 |
| 3 | 普通对话 | `core.cli.build_client` / `_build_messages`，后台线程联网 | ✅ 集成回归覆盖提交与回答落库 | 需 |
| 4 | 深度思考分片 | 流式文本 + `_throttled()` 80ms 节流 | ✅ `[v12] 停止按钮`、分片回写 | 需 |
| 5 | 智能体多轮 | `core.agent.runtime.AgentRuntime` | ✅ 集成回归覆盖 agent 路径 | 需 |
| 6 | 长期记忆 | `MemoryStore.learn_from_conversation(user_text=…, assistant_text=…)` | ✅ `[F4] 真实 MemoryStore 未抛 TypeError` + 「旧错误调用确实会失败」 | 需 |
| 7 | 服务商 / 模型设置 | `_safe_value()` 成员校验 + 联动刷新 | ✅ `[F3] 自定义模型下打开设置页不抛 ValueError`、`服务商联动模型刷新` | 需 |
| 8 | 长对话滚动 | `vertical_position = max_vertical_position` | ✅ `[F5] 走到了 vertical_position 分支` | 需 |
| 9 | 停止 / 中断 | `_stop_flag` + 「停止」按钮 | ✅ `[v12] 停止按钮` | 需 |
| 10 | 崩溃可诊断 | 全局 `sys.excepthook` + `starry-crash.log` + 诊断页 | ✅ `[F6] 诊断页可打开 / 含版本号` | 需 |
| 11 | 单窗口约束 | 设置 / 诊断都是主窗口内容切换 | ✅ `[F8] 未新建第二个窗口` | 需 |
| 12 | 星尘卡（v12 新） | `core.stardust.build_echo_card`，每轮回答后自动附卡；导入失败则降级跳过 | ✅ 63 项单测含卡片生成与确定性 | 需 |
| 13 | 上下文预算（v12 新） | `core.stardust.plan_trim` | ✅ 37 项集成含裁剪计划 | 需 |
| 14 | `.starry` 存档（v12 新） | `pack_archive` / `unpack_archive`，篡改即拒 | ✅ 37 项集成含 round-trip 与篡改拒绝 | 需 |

**测试合计**：`tests/test_android_v12.py` **37/37**、
`tests/test_v12_features.py` **63/63**、`android/test_app_logic.py` **16/16**、
`check_core_parity.py` 全通过。

> **诚实边界**：以上为「真实 `core` + 忠实复刻 Toga 0.5.7 行为的 UI 替身」
> 的本机集成回归，**不是真机测试**。UI 渲染、系统 WebView/字体、
> 网络栈与省电策略仍需设备验收。本报告**不声称「真机不再闪退」**。

---

## 5. 诊断页（闪退排查首选）

主窗口 →「诊断」，可看到：

- 应用版本（应显示 `12.0.0`）
- 平台信息
- 配置目录实际路径
- 本次运行捕获的异常条数
- 可复制的异常日志

另外全局 `sys.excepthook` 会把未捕获异常追加写到 `starry-crash.log`。
**用户无需 adb / 无需连电脑**即可把信息复制给开发者
（v11.5 是只写 logcat、失败即 `sys.exit(1)`，用户什么都看不到）。

复制前请自行抹掉 API Key 等敏感字段。

---

## 6. 本版修了什么（F1–F8 速查）

| 编号 | v11.5 的问题 | 用户可见现象 | v12.0 修复 |
| --- | --- | --- | --- |
| F1 | `AppConfig.load()` 在 `try` 外；`os.makedirs` 无保护 | 冷启动直接闪退 | 配置层永不抛异常；`startup()` 全程包裹 + 应用内错误页 |
| F2 | 未用 Android 私有目录 | 配置 / 记忆写入不可靠 | 注入 `STARRY_CONFIG_DIR` |
| F3 | `Selection(value=...)` 未校验 | 自定义模型后点「设置」即崩 | `_safe_value()` 成员校验 + 设置页整体兜底 |
| F4 | `learn_from_conversation(prompt=, answer=)` 签名错误 | 长期记忆静默失效 | 改回 `(user_text, assistant_text)` 真实签名 |
| F5 | 调用不存在的 `scroll_to_bottom()` | 长对话不滚动 | 改 `vertical_position = max_vertical_position` |
| F6 | 异常只写 logcat，失败即 `sys.exit(1)` | 闪退后无线索 | excepthook + crash.log + 诊断页 |
| F7 | UI 回调无隔离 | 一个回调异常拖垮循环 | 每个回调单独 try；80ms 节流；可中断 |
| F8 | 多窗口风险 | 切页面可能崩 | 设置 / 诊断都是主窗口内容切换 |

**构建链**：`android/pyproject.toml` 去掉裸 `"toga"`，钉死
`toga-core==0.5.7` / `toga-android==0.5.7` 及全部依赖版本，
消除 v11.5 实测的 `toga 0.2.15 + toga-core 0.5.7 + toga-gtk 0.2.15` 混装；
CI 新增 `verify_apk.py --strict` 门禁拒绝混装包进入 Release。

---

## 7. 到货验收（拿到 APK 后三条都要过）

```bash
apksigner verify --verbose 星语Starry-Android-v12.0.0.apk
python scripts/verify_apk.py --apk 星语Starry-Android-v12.0.0.apk \
       --expect-version 12.0.0 --strict
# 然后按第 4 节清单在真机逐项点一遍
```

`--strict` 下任何 FAIL 或 WARN 都视为不通过；检查项含 v1/v2/v3 签名、
APK Signing Block 长度自洽、`build.json` 中 `app.imy` 的 SHA1、
`.pyc` magic 对应 CPython 3.11、toga 主版本一致、应用版本、INTERNET 权限。

---

## 8. 已知限制

1. 本机未产出 v12.0 签名 APK 二进制（原因见第 1 节），**未伪造**。
2. 无真机 / 无模拟器，不能声称真机实测不闪退。
3. `starry-crash.log` 只追加、无轮转，长期使用会增长；日志未做敏感字段掩码。
4. 主题依赖应用内 `theme` 配置，未跟随 Android 系统夜间模式自动切换。
5. 大字号（1.3 倍）下部分长按钮文案可能需要真机复核是否换行。
