# 星语 Starry · API 开放文档（V12.0.0）

> 适用版本：**12.0.0**（2026-11-07）。本版新增三层对外能力：
> **`core/stardust.py` 星尘纯逻辑层**、**`core/config.py` 平台与配置契约**、
> **CLI 新命令 + 工程化脚本的命令行接口**。
>
> 所有纯逻辑零 GUI 框架依赖、零网络、零第三方依赖，桌面 / CLI / Android 的
> `core/` 与 `android/core/` 字节一致（由 `scripts/sync_core.py` 同步，CI 门禁保证），
> 外部可直接 `import` 使用，无需启动 Qt 或 Toga。
> 历史接口（`core/insights.py` 等）继续有效，见 `API开放文档_v11_5.md`。

---

## 1. `core.stardust` —— 星尘纯逻辑层（新建）

导入：

```python
from core import stardust                      # 走 PEP 562 懒导出
# 或
from core.stardust import (estimate_tokens, build_echo_card, plan_trim,
                           pack_archive, unpack_archive, archive_digest)
```

设计约定：**只用标准库**（`hashlib` / `json` / `re`）；不读写文件、不访问全局状态；
时间戳等外部信息由调用方传入以保证确定性；不修改入参，返回新对象。

| 常量 | 值 | 说明 |
| --- | --- | --- |
| `ARCHIVE_MAGIC` | `"STARRY-ARCHIVE"` | 存档信封魔数 |
| `ARCHIVE_VERSION` | `1` | 当前存档格式版本；高于此值一律拒绝 |

### 1.1 `estimate_tokens`

```python
estimate_tokens(text) -> int
```

粗略离线估算：CJK（含日文假名 / 韩文）每字 1 token，其余按 4 字符 ≈ 1 token。
`None` / 空串返回 `0`。

> **不是任何模型的精确计费值**，仅用于量级参考与裁剪计划。
> 与 `core/insights.py::estimate_tokens` 口径一致（此处独立实现一份，
> 避免 `import sessions` 造成循环依赖）。

### 1.2 `build_echo_card`

```python
build_echo_card(title="本轮问答", reasoning="", answer="", prompt="",
                branched_from=None, ts=None, max_answer_chars=400) -> str
```

把一次问答收成一张可复制的 Markdown 小卡，**不调用模型、零 token、零联网**。

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `title` | str | 卡片标题 |
| `reasoning` | str | 本轮思考过程全文（可为流式分片拼接结果），按空行切片取首/末句 |
| `answer` | str | 最终回答，摘录上限由 `max_answer_chars` 控制 |
| `prompt` | str | 用户提问，只取首句（≤120 字符） |
| `branched_from` | str / None | 分支来源会话 id，无则 `None` |
| `ts` | str / None | 时间戳字符串，**由调用方传入**；不传则省略时间行（保证纯函数确定性） |
| `max_answer_chars` | int | 回答摘录长度上限，默认 400 |

返回 Markdown 字符串；同输入必得同输出。输出骨架：

```
✦ 星尘卡

**本轮问答**
`2026-11-07 17:40:00`

- **问**：…
- **思考起点**：…
- **思考落点**：…
- **答**：…

> 思考分片 3 · 约 128 tokens · 分支锚点 无
```

### 1.3 `plan_trim`

```python
plan_trim(messages, max_tokens, policy="keep_recent", keep_system=True) -> dict
```

给出「保留哪些消息」的**确定性计划**，只返回下标，**不修改入参、不发请求、不真正裁剪**。

| 参数 | 说明 |
| --- | --- |
| `messages` | `[{"role": ..., "content": ...}, ...]`；元素也允许是普通字符串 |
| `max_tokens` | 预算上限；`<= 0` 一律按 `0` 处理 |
| `policy` | `"keep_recent"`（默认，从最新往前保）/ `"keep_first"`（从最旧往后保）/ `"keep_ends"`（先保尾部 3/4 预算再补头部两条） |
| `keep_system` | `True` 时 `role=="system"` 的消息优先保留并计入预算 |

返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `keep_indices` | list[int] | 升序，建议保留的原始下标 |
| `drop_indices` | list[int] | 升序，建议丢弃的原始下标 |
| `kept_tokens` | int | 保留部分的估算 token |
| `total_tokens` | int | 全部消息的估算 token |
| `trimmed` | bool | 是否存在被丢弃的消息 |
| `policy` | str | 本次采用的策略 |
| `max_tokens` | int | 生效的预算 |

每条消息成本 = `estimate_tokens(content) + 4`（角色 / 分隔开销）。

```python
msgs = [{"role": "system", "content": "你是助手"},
        {"role": "user", "content": "第一轮问题很长……"},
        {"role": "assistant", "content": "回答……"},
        {"role": "user", "content": "第二轮"}]
p = plan_trim(msgs, 40, policy="keep_ends")
# {"keep_indices": [0, 2, 3], "drop_indices": [1],
#  "kept_tokens": ..., "total_tokens": ..., "trimmed": True, ...}
```

### 1.4 存档三函数

```python
archive_digest(payload) -> str                      # 规范化 JSON 的 SHA-256 hex
pack_archive(sessions=None, memory=None, meta=None) -> str   # .starry 文本（UTF-8 JSON）
unpack_archive(text) -> dict                       # 解析 + 校验，失败抛 ValueError
```

- `pack_archive` 接受 dict 或 list，深拷贝进信封，**不修改入参**；
  返回带缩进的 JSON 字符串，可直接写文件。
- `unpack_archive` 接受 str / bytes / dict；成功返回
  `{"version", "sessions", "memory", "meta"}`（新字典，深拷贝）。
- **失败一律 `ValueError`**，错误信息区分：非法 JSON / 根节点非对象 /
  magic 不匹配 / 版本不支持 / payload 结构损坏 / 校验失败 / 缺字段。

### 1.5 `.starry` 文件格式规格

```json
{
  "magic": "STARRY-ARCHIVE",
  "version": 1,
  "payload": {
    "sessions": {},
    "memory": {},
    "meta": {}
  },
  "checksum": "<sha256 of canonical payload>"
}
```

`checksum` 计算方式（跨端一致的关键）：

```python
canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

> **信任边界**：`checksum` 是**完整性校验**（防传输损坏 / 误编辑 / 版本错配），
> **不是认证**。攻击者可改 `payload` 后重算 `checksum`。若需防恶意构造，
> 应引入 HMAC 或数字签名——本版刻意不引入，以保持零依赖、零配置、三端互导。

### 1.6 边界与行为契约

| 场景 | 行为 |
| --- | --- |
| `messages=[]` / `messages=None` | 返回 `trimmed=False`、两个下标列表为空、token 全 0 |
| `max_tokens` 小于任一 system 消息成本 | system 仍优先占用（超出部分通过 `budget == 0` 分支处理），不抛异常 |
| `policy` 传未知值 | 退化为 `keep_recent`，不抛异常 |
| `messages` 元素非 dict | 按 `str(m)` 计入成本，`keep_system` 对其不生效 |
| 存档被改一个字符 | `unpack_archive` 抛 `ValueError("存档校验失败（内容被修改或传输损坏）")` |
| 存档 `version=99` | 抛 `ValueError("不支持的存档版本：99")` |
| 非 `.starry` JSON | 抛 `ValueError("不是 .starry 存档（magic 不匹配）")` |
| 纯逻辑层依赖 | 仅标准库；AST 门禁保证无 PyQt / Toga / requests import |

---

## 2. `core.config` —— 平台与配置契约（v12.0 改写）

```python
from core import config as cfg

cfg.APP_VERSION            # "12.0.0"
cfg.is_android()           # bool
cfg._safe_makedirs(path)   # -> str，绝不抛 OSError
cfg.get_config_dir()       # -> str，自动创建，永不抛异常
cfg.AppConfig.load()       # -> AppConfig，永不抛异常
```

| 接口 | 契约 |
| --- | --- |
| `is_android()` | 以 `sys.getandroidapilevel`（Toga 0.5.7 官方判据）为主，辅以 `ANDROID_ROOT` / `ANDROID_DATA` 兜底；只读，无副作用 |
| `_safe_makedirs(path)` | 候选顺序：`path` → `tempfile.gettempdir()/APP_ID` → `./.starry-data/APP_ID`；每级 `os.makedirs(exist_ok=True)` + `os.access(W_OK)`；全部失败返回最后一个候选路径，**绝不抛异常** |
| `get_config_dir()` | Android：`STARRY_CONFIG_DIR`（由 Toga `app.paths.config` 注入）→ `HOME/.config` → tempdir；Windows `APPDATA`；macOS `~/Library/Application Support`；Linux `XDG_CONFIG_HOME` 或 `~/.config` |
| `AppConfig.load()` | 读 `get_config_dir()/config.json`；任何磁盘 / 解析 / 合并异常退化为 `AppConfig()` 默认配置 |
| `AppConfig.save()` | 写 `config.json`，POSIX 下 `chmod 0o600`（含 API Key 与许可密钥） |

**环境变量**：

| 变量 | 设置方 | 作用 |
| --- | --- | --- |
| `STARRY_CONFIG_DIR` | `StarryApp.startup()` | 把配置 / 记忆 / 会话落到 Android 应用私有可写目录，随卸载清理 |
| `ANDROID_ROOT` / `ANDROID_DATA` | 系统 | `is_android()` 兜底判据 |
| `APPDATA` / `XDG_CONFIG_HOME` / `HOME` | 系统 | 桌面端配置根目录 |
| `STARRY_DATA_DIR` | 可选（调用方 / 测试） | v12.0：覆盖网关统计与预算的数据目录；**未设置时仍为 `~/.starry`，行为逐字不变、不迁移用户数据** |
| `PLAYWRIGHT_BROWSERS_PATH` | 可选 / 系统 | Playwright 浏览器内核根目录，供 `chromium_kernel_available()` 探测 |

**`core.gateway._data_dir()` → str**（v12.0 新增）：返回网关数据目录，
按 `STARRY_DATA_DIR` → `~/.starry` 顺序取值；`_stats_path()` /
`_budgets_path()` 均基于它。纯路径计算，不创建目录、不抛异常，
供自测与嵌入场景做数据隔离。设计取舍：Windows 上
`os.path.expanduser("~")` 读 `USERPROFILE`，传统 `HOME` 隔离对它无效，
因此提供显式注入点而非改动默认路径。

**`core.browser_llm.chromium_kernel_available()` → bool**（v12.0 新增）：
检查 `playwright install chromium` 下载的**内置**内核是否已就绪，
与只找系统 Chrome 的 `find_chromium()` 互补。纯文件系统探测，
不启动 driver、不联网；供设置页「一键安装内核」在已就绪时直接反馈，
避免重复下载 100+ MB。

**`core/__init__.py` 懒导出**（PEP 562）：`from core import stardust` 等按需
`importlib.import_module`，避免 `import core` 拉起全部模块；桌面专属模块
（`attachment` / `hotkey` / `models` / `workers`）在安卓端未分发，
此时抛出的不是裸 `ImportError`，而是带中文说明的 `AttributeError`：

```
core.hotkey 在当前平台不可用（core.hotkey 未随本端分发）
```

---

## 3. CLI 新命令（`starry_cli.py` / EXE / deb 中的 `starry`）

所有新命令均为**本地执行、零联网**，执行完即退出。

| 参数 | 签名 | 行为 | 退出码 |
| --- | --- | --- | --- |
| `--doctor` | flag | 运行环境 / 版本一致性自检：打印版本、平台、配置目录、依赖状态、三端同源状态 | 0 |
| `--archive PATH` | 路径 | 把全部会话 + 长期记忆导出为 `.starry` 存档 | 0 / 1（写入失败） |
| `--restore PATH` | 路径 | 从 `.starry` 导入；校验失败一律拒绝；覆盖前备份 `*.bak-<时间戳>` | 0 / 1（校验或写入失败） |
| `--budget N` | int | 对当前会话给出 token 上限 N 的上下文裁剪计划（空会话也输出计划标题） | 0 |
| `--echo` | flag | 在 `chat` / `agent` 对话结束后附加打印一张本地生成的星尘卡 | 0 |

```bash
starry --version                      # 12.0.0
starry --doctor
starry --budget 800
starry --archive backup.starry
starry --restore backup.starry
starry --echo --ask "解释一下上下文预算"  # 对话后附星尘卡
```

**实测**（重建后的 `dist/星语Starry-CLI.exe`）：
`--version` / `--platform` / `--doctor` / `--budget 800` / `--archive` / `--restore`
六项退出码全部 `0`；`--archive` 生成 912 字节存档，`--restore` 回报
「导入完成：会话 1 个 · 记忆 0 条，原文件已备份 `*.bak-20261107-174303`」。

> `--doctor` 对 `markdown` 标为 CLI 可选依赖：它只用于桌面
> `core/markdown_render.py` 转 Qt 富文本，单文件 EXE 有意不收集；
> 单文件包中「三端同源」显示「跳过（由 CI 发布门禁保证）」。

---

## 4. 桌面命令面板（`Ctrl+K`）新增命令 id

| 命令 id | 图标 | 标题 | 行为 |
| --- | --- | --- | --- |
| `echo_card` | ✦ | 生成本轮星尘卡 | 取当前会话最后一轮 → `build_echo_card` → 可复制卡片 |
| `budget_plan` | 📐 | 上下文预算裁剪 | `plan_trim` → 展示保留 / 丢弃下标与 token 账 |
| `archive_export` | 📤 | 导出 .starry 存档 | 选路径 → `pack_archive` → 写文件 |
| `archive_import` | 📥 | 导入 .starry 存档 | 选路径 → `unpack_archive` → 校验通过才导入，先备份 |
| `doctor` | 🩺 | 运行环境自检 | 复用 `core.cli._run_doctor` |

分发入口：`app/assistant.py::_palette_commands()` 与 `_on_palette_command()`；
实现方法 `open_echo_card` / `open_budget_plan` / `open_archive_export` /
`open_archive_import` / `open_doctor`。CLI 与桌面共用同一份 `core.stardust`，
**不存在两套口径**。

---

## 5. 工程化脚本的命令行接口（可复跑，供 CI 与外部集成）

| 脚本 | 参数 | 退出码语义 |
| --- | --- | --- |
| `scripts/sync_core.py` | `--check` | 0 = 41 个文件一致 / 桌面专属 4 个按白名单排除；非 0 = 有漂移 |
| `scripts/check_core_parity.py` | `--expect-version X.Y.Z` | 0 = 三处版本声明一致 + 三端同源 + 全量 AST 语法通过；非 0 阻断发版 |
| `scripts/verify_apk.py` | `--apk PATH`（必需）、`--expect-version X.Y.Z`、`--json`、`--strict` | `--strict` 下 WARN 也视为失败；用于 CI 签名后门禁 |
| `scripts/build_deb.py` | `--out PATH` | 0 = 构造并通过 ar / control / data 自检 |
| `scripts/make_release.py` | `--version X.Y.Z`（必需）、`--no-zip`、`--summary TEXT` | 0 = 快照 + zip + MANIFEST + checksums + 索引生成完成；发现敏感文件直接非 0 中止 |

`verify_apk.py` 检查项：AndroidManifest / resources.arsc / classes.dex、
v1 JAR 签名、v2/v3 APK Signing Block 长度自洽、Chaquopy 资源、
`build.json` 中 `app.imy` 的 SHA1、`.pyc` magic 对应 CPython 3.11、
toga 元包与 `toga-core` 主版本一致（拒绝 0.2/0.5 混装）、应用版本、INTERNET 权限。

```bash
python scripts/sync_core.py --check
python scripts/check_core_parity.py --expect-version 12.0.0
python scripts/verify_apk.py --apk app.apk --expect-version 12.0.0 --strict
python scripts/make_release.py --version 12.0.0
```

> `verify_apk.py` 是**静态结构鉴定**，不执行 APK、不校验证书链可信度，
> 不替代 `apksigner verify` 与真机安装测试。

---

## 6. 向后兼容

| 场景 | 行为 |
| --- | --- |
| v11.5 及更早的 `config.json` | `AppConfig.load()` 走既有 `_deep_merge`，无需迁移 |
| v11.5 的会话 / 记忆文件 | 原样读取；`--archive` 可导出，`.starry` 是**新增**格式，不替换原文件 |
| 旧 `core.insights` / `SessionStore` 接口 | 完全保留，见 `API开放文档_v11_5.md` |
| 桌面专属模块在安卓端 `import` | 抛带中文说明的 `AttributeError`，不再是裸 `ImportError` |
| `stardust` 在安卓端不可用 | `app.py` 用 `try/except` 降级为 `stardust=None`，不阻断启动 |
| 存档 `version` 未来升级 | 当前 `> 1` 一律拒绝；升级时提高 `ARCHIVE_VERSION` 并写迁移分支 |

---

## 7. 最小完整示例

```python
from core.stardust import (build_echo_card, plan_trim,
                           pack_archive, unpack_archive)

# 1) 星尘卡（零 token）
card = build_echo_card(
    title="上下文预算问答",
    reasoning="先看预算定义。\n再决定保留策略。\n最后返回下标计划。",
    answer="plan_trim 只返回下标，不修改入参，也不发请求。",
    prompt="上下文预算是怎么算的？",
    ts="2026-11-07 17:40:00",
)
print(card)

# 2) 裁剪计划（先看计划，再决定是否执行）
msgs = [{"role": "system", "content": "你是助手"},
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "回答一"},
        {"role": "user", "content": "第二轮"}]
plan = plan_trim(msgs, 40, policy="keep_ends")
kept = [msgs[i] for i in plan["keep_indices"]]      # 由调用方决定执行

# 3) 存档往复 + 篡改检测
text = pack_archive(sessions={"current": "s1"}, memory={"hobby": "天文"},
                    meta={"app_version": "12.0.0"})
data = unpack_archive(text)
print(data["memory"])                                # {'hobby': '天文'}

import json
env = json.loads(text)
env["payload"]["memory"]["hobby"] = "被改过"
try:
    unpack_archive(json.dumps(env, ensure_ascii=False))
except ValueError as e:
    print("拒绝导入：", e)                            # 存档校验失败…
```
