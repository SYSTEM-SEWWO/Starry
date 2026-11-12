# APK 鉴定与安卓闪退根因报告 · v12.0.0

> 原则：**先鉴定、再定位、后修复**。所有结论都指向可复跑的命令、文件或实测输出；
> 无法在本环境验证的部分明确标注，不臆断。

## 一、鉴定对象与方法

对象：`星语 Starry-11.5.0.apk`（51,980,670 字节，v11.5 分发的真实签名包）。
工具：`python scripts/verify_apk.py --apk <APK> --expect-version 11.5.0`
原始输出：`docs/APK鉴定报告_v11_5_实测.txt`。

APK 是 ZIP；Chaquopy 把 Python 代码打成 `assets/chaquopy/app.imy`（ZIP of `.pyc`），
把第三方依赖打成 `requirements-common.imy`，`build.json` 用 SHA1 记录资源摘要。

## 二、鉴定结论：21 通过 / 1 失败 / 2 提示

| 类别 | 实测 |
| --- | --- |
| 结构 | AndroidManifest.xml / resources.arsc / classes.dex 齐全 |
| 签名 | v1：`META-INF/STARRY.SF` + `STARRY.RSA`；v2/v3：APK Signing Block 偏移 51945456，头尾 size 均 4088（自洽） |
| 运行时 | `lib/arm64-v8a`、`armeabi-v7a`、`x86_64` 三套 `libpython3.11.so`；`.pyc` magic 对应 3.11 |
| 完整性 | `build.json` 中 `app.imy` 的 SHA1 = 实际 `4b632f61…`，一致 |
| 应用代码 | `starryandroid/app.pyc`、43 个 `core/*.pyc`；`starryandroid-11.5.0.dist-info` |
| 权限/后端 | INTERNET 已声明；`[toga.backends]` 只注册 `android` |
| **FAIL** | **`toga 0.2.15` 元包 与 `toga-core 0.5.7` / `toga-android 0.5.7` 混装，且带入 `toga-gtk 0.2.15`** |

### 关于混装的准确表述（避免过度归因）

实测显示 `[toga.backends]` 只有 `android = toga_android`，`toga/__init__.pyc` 也确实是 0.5.x 的
`toga_core_imports` 懒加载实现，所以**不能断言「后端选错导致闪退」**。可以确证的是：
裸 `toga` 元包被 pip 解析成 0.2.15，按它的 METADATA
（`Requires-Dist: toga-gtk; sys_platform=="linux"`）把 0.2.15 的 GTK 后端打进了 Android 包，
造成两代代码共存、产物不可复现。这是**构建链高危变量**，v12.0 已通过钉死依赖消除。

## 三、应用代码级根因（可复现，优先级高于构建链）

| # | 位置（v11.5） | 复现依据 | 用户可见现象 |
| --- | --- | --- | --- |
| F1 | `app.py:55` `self.cfg = AppConfig.load()` 在 try 外；`config.py:303` `os.makedirs` 无保护 | 构造只读/受限路径即可让异常冒泡 | 冷启动闪退，无提示 |
| F2 | `config.py` 只有 win/darwin/linux 三分支，无 Android 私有目录 | 代码审读 | 配置/记忆写入不可靠 |
| F3 | `app.py:390-399` `Selection(value=cfg.model())` | 本机实测 `toga 0.5.7`：`ValueError: 'z' is not a current item in the selection` | 自定义模型后点「设置」闪退 |
| F4 | `app.py:347` `learn_from_conversation(prompt=, answer=)` | 真实签名 `core/memory.py:216` 为 `(user_text, assistant_text)`；错误关键字必抛 TypeError | 长期记忆静默失效 |
| F5 | `app.py:229` `scroll_to_bottom()` | 实测 `hasattr(toga.ScrollContainer,'scroll_to_bottom') == False` | 长对话不滚动 |
| F6 | `__main__.py` 失败即 `sys.exit(1)`，仅 logcat | 代码审读 | 闪退后无线索 |
| F7/F8 | 回调无隔离 / 多窗口风险 | 代码审读 | 连锁崩溃 |

### 为什么之前「16/16 全绿」却还在闪退

`android/test_app_logic.py`（v11.5）的 fake 层同时替换了 UI **和核心逻辑**：

```python
class FakeMemory:
    def learn_from_conversation(self, prompt=None, answer=None):  # 复刻了错误签名
        pass
class FakeWidget:
    def scroll_to_bottom(self): pass                              # 真实 Toga 没有
# Selection 完全不校验 value ∈ items
```

于是 F3/F4/F5 三个真机缺陷全部被 fake 抹平。v12.0 的处理：
1. 新增 `tests/test_android_v12.py`：**真实 core 模块**，只 fake UI，且 fake 忠实复刻
   Toga 0.5.7 的 `Selection` ValueError、无 `scroll_to_bottom`、App.loop 只读等；
2. 修正旧测试的 fake 签名与文本断言，使其不再造假（修正后 16/16）；
3. 用例「旧的错误关键字调用确实会失败」把 F4 固化为回归证据。

## 四、修复清单与验证映射

| 修复 | 文件 | 对应用例 |
| --- | --- | --- |
| F1 启动零抛出 + 配置目录永不抛异常 | `core/config.py`、`android/starryandroid/app.py` | `[F1] startup 成功且未抛异常` / `启动流程无任何异常记录` / `不可写私有目录时仍返回可用路径` / `AppConfig.load() 永不抛异常` / `致命错误走应用内错误页` |
| F2 注入私有目录 | `app.py::startup` | `[F2] 配置目录落在 Android 私有目录` |
| F3 Selection 值校验 | `app.py::_safe_value` | `[F3] 自定义模型下打开设置页不抛 ValueError` |
| F4 真实签名 | `app.py::_commit_answer` | `[F4] 真实 MemoryStore 未抛 TypeError` / `旧的错误关键字调用确实会失败` |
| F5 正确滚动 API | `app.py::_scroll_bottom` | `[F5] 走到了 vertical_position 分支` |
| F6 诊断页 + excepthook | `app.py`、`__main__.py` | `[F6] 诊断页可打开 / 含版本号` |
| F7/F8 节流与单窗口 | `app.py` | `[v12] 停止按钮` / `[F8] 未新建第二个窗口` |

**实测结果**：`tests/test_android_v12.py` 37/37，`tests/test_v12_features.py` 63/63，
`android/test_app_logic.py` 16/16，`scripts/check_core_parity.py` 全通过。

## 五、构建链修复

`android/pyproject.toml`：

```toml
# v11.5：裸 "toga" → Chaquopy(sys.platform=="linux") 解析成 0.2.15
requires = ["toga", "requests", "markdown", "beautifulsoup4"]

# v12.0：钉死内核，杜绝元包与后端漂移
requires = ["toga-core==0.5.7", "requests==2.32.3", "markdown==3.7",
            "beautifulsoup4==4.12.3"]
[tool.briefcase.app.starryandroid.android]
requires = ["toga-android==0.5.7"]
permissions = ["INTERNET", "ACCESS_NETWORK_STATE"]
```

CI 在签名后新增 `verify_apk.py --strict` 门禁，会检查签名块自洽、`build.json` SHA1、
`.pyc` 版本、toga 主版本一致性、应用版本与权限，任何 FAIL 阻断发版。

## 六、验证边界（重要）

- 已验证：源码级缺陷、真实 core 集成流程、依赖解析、APK 静态结构与签名。
- **未验证**：真机安装与 UI 渲染（本机无 Android 设备 / 模拟器 / `/dev/kvm`）。
- **未产出**：v12.0 修复版签名 APK 二进制。原因是本机缺 JDK 17 / Android SDK / Gradle /
  `apksigner`；替换 `app.imy` 会使 v1 摘要与 v2/v3 签名全部失效，必须重签。
  修复版由 `.github/workflows/build-android.yml` 在推 `v12.0.0` tag 时真实编译产出。
- 因此本报告**不声称「真机不再闪退」**，只声称「8 项可实证缺陷已修复并有回归测试」。
