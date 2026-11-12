# -*- coding: utf-8 -*-
"""星语 Starry v13.2 · 企业级 API 错误治理单测。

运行：python tests/test_enterprise_api.py   （退出码 0 = 全绿）

背景：真实 GUI 鼠标测评（隔离配置 + 本地 mock 401）复现了「启动即报 HTTP 401、
错误一闪而过、用户无法自助排查」。本测试锁死修复结果：
  * HTTP / 异常错误分类与可操作建议；
  * 脱敏（绝不输出 API Key / Bearer Token / 上游原文）；
  * 诊断记录（内存环形缓冲 + 可选审计落盘，脱敏）；
  * 指数退避与重试策略；
  * 配置目录显式覆盖（企业部署 / 便携模式 / 测试隔离硬门禁）；
  * 启动自动刷新失败静默降级，不打扰用户；
  * GUI 诊断面板与命令面板入口。

全部离线、确定性；不联网、不读取用户真实配置、不打印任何密钥。
"""
import io
import json
import os
import sys
import tempfile
from unittest.mock import Mock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 任何配置读写都落进临时目录；同时验证 STARRY_DATA_DIR 在 Windows 也生效
_TMP = tempfile.mkdtemp(prefix="starry_ent_test_")
os.environ["STARRY_DATA_DIR"] = os.path.join(_TMP, ".starry")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from core import api as api_mod                     # noqa: E402
from core import apidiag                            # noqa: E402
from core import apierrors as ae                    # noqa: E402
from core import config as cfg_mod                  # noqa: E402
from core import cli as cli_mod                     # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS" if cond else "FAIL"), "-", name, extra)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


# ===========================================================================
# 1) 错误分类
# ===========================================================================
check("401 → auth", ae.status_kind(401) == ae.KIND_AUTH)
check("402 → quota", ae.status_kind(402) == ae.KIND_QUOTA)
check("403 → forbidden", ae.status_kind(403) == ae.KIND_FORBIDDEN)
check("404 → not_found", ae.status_kind(404) == ae.KIND_NOT_FOUND)
check("429 → rate_limit", ae.status_kind(429) == ae.KIND_RATE_LIMIT)
check("500/502/503 → server",
      all(ae.status_kind(c) == ae.KIND_SERVER for c in (500, 502, 503)))
check("非法状态码不抛异常", ae.status_kind("oops") == ae.KIND_UNKNOWN)
check("每种分类都有元信息",
      all(k in ae.KIND_META for k in ae.KINDS))

e401 = ae.from_http(401, '{"error":"Invalid key"}', "list_models")
check("401 结构化字段齐备", all(
    k in e401 for k in ("kind", "title", "advice", "action", "retryable",
                        "backoff", "detail", "operation")))
check("401 不可重试且引导去设置",
      not e401["retryable"] and e401["action"] == "open_settings")
check("401 建议可操作", any("Base URL" in a for a in e401["advice"]))
check("429 可重试", ae.from_http(429)["retryable"])
check("5xx 可重试", ae.from_http(503)["retryable"])
check("操作名被记录", e401["operation"] == "list_models")

net = ae.from_exception(TimeoutError("connect timeout"), "chat")
check("超时归 network", net["kind"] == ae.KIND_NETWORK)
dns = ae.from_exception(OSError("Name or service not known"), "chat")
check("DNS/连接失败归 network 或 unknown（不抛）",
      dns["kind"] in (ae.KIND_NETWORK, ae.KIND_UNKNOWN))
js = ae.from_exception(ValueError("Expecting value: JSON decode"), "chat")
check("JSON 解析失败归 parse", js["kind"] == ae.KIND_PARSE)
check("空异常不抛", isinstance(ae.from_exception(None), dict))

conf = ae.config_error("未配置 API 地址")
check("配置缺失归 config", conf["kind"] == ae.KIND_CONFIG)

# ===========================================================================
# 2) 脱敏（硬性安全边界）
# ===========================================================================
secret_cases = [
    "Bearer sk-live-ABCDEF123456",
    'api_key: "sk-proj-abcdef123456"',
    "Authorization: Bearer my-secret-token-9999",
    "https://x/v1?api_key=HUNTER2SECRET&a=1",
]
leaked = False
for s in secret_cases:
    out = ae.redact(s)
    for token in ("sk-live-ABCDEF123456", "sk-proj-abcdef123456",
                  "my-secret-token-9999", "HUNTER2SECRET"):
        if token in out:
            leaked = True
check("脱敏不泄露任何测试密钥", not leaked)
check("脱敏保留结构可读性", "***" in ae.redact(secret_cases[0]))
check("脱敏截断超长文本", len(ae.redact("A" * 5000)) <= ae.MAX_DETAIL + 1)
check("redact 对任意输入不抛", ae.redact(object()) in ("", "<无可用详情>")
      or isinstance(ae.redact(object()), str))
check("one_line 不含上游原文",
      "Invalid key" not in ae.one_line(e401))
check("full_text 含逐条建议与退避说明",
      "建议：" in ae.full_text(e401) and "可重试" in ae.full_text(e401))
check("full_text 对非法输入不抛", "诊断" in ae.full_text(None))

# ===========================================================================
# 3) 退避策略
# ===========================================================================
check("auth 退避为 0", ae.backoff_seconds(e401, 3) == 0)
r429 = ae.from_http(429)
check("429 指数退避 30/60/120",
      [ae.backoff_seconds(r429, i) for i in (1, 2, 3)] == [30, 60, 120])
check("退避有上限", ae.backoff_seconds(r429, 99) == ae.MAX_BACKOFF)
check("非法 attempt 不抛", ae.backoff_seconds(r429, "x") == 30)

# ===========================================================================
# 4) 诊断记录
# ===========================================================================
apidiag.clear()
check("清空后无记录", apidiag.summary()["total"] == 0)
apidiag.record("list_models", e401, scope="startup",
               provider="zhipu", note="Key sk-SHOULD-NOT-APPEAR")
apidiag.record("chat", ae.from_http(429), scope="runtime")
s = apidiag.summary()
check("诊断记录计数", s["total"] == 2)
check("诊断按分类汇总", s["by_kind"].get("auth") == 1
      and s["by_kind"].get("rate_limit") == 1)
recent = apidiag.recent(1)
check("recent 返回最新一条", recent[0]["kind"] == "rate_limit")
text = apidiag.text_report()
check("诊断文本脱敏", "sk-SHOULD-NOT-APPEAR" not in text)
check("诊断文本含建议", "建议" in text)
check("诊断记录不含 api_key 字段",
      all("api_key" not in x and "key" not in x
          for x in apidiag.recent(10)))
check("空记录文本友好", "暂无" in (apidiag.clear() or apidiag.text_report()))

audit = os.path.join(_TMP, "audit.jsonl")
os.environ["STARRY_API_LOG"] = audit
apidiag.record("list_models", e401, scope="audit")
os.environ.pop("STARRY_API_LOG", None)
check("审计日志可落盘", os.path.isfile(audit))
audit_text = open(audit, "r", encoding="utf-8").read()
check("审计日志为合法 JSONL", isinstance(json.loads(audit_text.strip()), dict))
check("审计日志不含密钥", "sk-live" not in audit_text)

# ===========================================================================
# 5) core.api 统一错误出口（真实 mock，不发网络请求）
# ===========================================================================
def fake_response(status, text='{"error":{"message":"Invalid key sk-ABCDEF123"}}'):
    r = Mock()
    r.status_code = status
    r.text = text
    return r


apidiag.clear()
for code, kind in ((401, ae.KIND_AUTH), (429, ae.KIND_RATE_LIMIT),
                   (502, ae.KIND_SERVER)):
    with patch("core.api.requests.get", return_value=fake_response(code)):
        try:
            api_mod.list_models("http://127.0.0.1:9/v1", "sk-TOPSECRET-123")
            raised = False
        except api_mod.ChatError as exc:
            raised = True
            msg = str(exc)
            detail = getattr(exc, "detail", {})
    check("list_models HTTP %d 抛 ChatError" % code, raised)
    check("HTTP %d 消息含中文建议" % code, "建议：" in msg)
    check("HTTP %d 消息不泄露上游原文" % code, "sk-ABCDEF123" not in msg)
    check("HTTP %d detail 分类正确" % code, detail.get("kind") == kind)

with patch("core.api.requests.get",
           side_effect=api_mod.requests.exceptions.ConnectionError(
               "connection refused (os error 10061)")):
    try:
        api_mod.list_models("http://127.0.0.1:9/v1", "sk-TOPSECRET-123")
        net_raised = False
    except api_mod.ChatError as exc:
        net_raised = True
        net_msg = str(exc)
check("网络失败收敛为 ChatError", net_raised)
check("网络失败消息为中文且可操作", "建议" in net_msg or "网络" in net_msg)

with patch("core.api.requests.get", return_value=Mock(status_code=401, text="")):
    try:
        api_mod.list_models("", "")
        cfg_raised = False
    except api_mod.ChatError:
        cfg_raised = True
check("未配置地址被拒绝", cfg_raised)
check("失败均写入诊断", apidiag.summary()["total"] >= 4)

# 连接/读取超时分离
pair = api_mod._timeout_pair(15)
check("超时分离 (5,15)", tuple(pair) == (5.0, 15.0))
check("短超时不被放大", tuple(api_mod._timeout_pair(3)) == (3.0, 3.0))
check("元组超时原样保留", tuple(api_mod._timeout_pair((2, 9))) == (2, 9))

# ===========================================================================
# 6) 配置目录显式覆盖（实测发现的隔离失效修复）
# ===========================================================================
saved = os.environ.get("STARRY_DATA_DIR")
tmp_dir = os.path.join(_TMP, "isolated_profile")
os.environ["STARRY_DATA_DIR"] = tmp_dir
try:
    d = cfg_mod.get_config_dir()
    check("STARRY_DATA_DIR 直接作为配置目录",
          os.path.normcase(d) == os.path.normcase(tmp_dir))
    check("隔离目录被自动创建", os.path.isdir(d))
finally:
    if saved is None:
        os.environ.pop("STARRY_DATA_DIR", None)
    else:
        os.environ["STARRY_DATA_DIR"] = saved
check("get_config_dir 永不抛异常", isinstance(cfg_mod.get_config_dir(), str))

# ===========================================================================
# 7) 启动自动刷新静默降级（真实 ModelController + 假窗口）
# ===========================================================================
try:
    from PyQt5.QtWidgets import QApplication
    from app.model_controller import ModelController
    app = QApplication.instance() or QApplication(sys.argv[:1])

    class FakeWindow:
        def __init__(self):
            self.hints = []

        def show_hint(self, text):
            self.hints.append(str(text))

    cfg = cfg_mod.AppConfig({
        "provider": "zhipu", "api_keys": {"zhipu": "INVALID-TEST-KEY"},
        "base_urls": {"zhipu": "http://127.0.0.1:9/v1"},
        "auto_refresh_models": True})
    win = FakeWindow()
    mc = ModelController(cfg, win)
    mc._on_models_failed_detail(ae.from_http(401))
    mc._on_models_failed("HTTP 401")
    check("自动刷新失败不弹打扰式提示", win.hints == [])
    check("自动刷新失败后本次会话退避", mc._auto_refresh_disabled)
    check("失败次数被记录", mc._refresh_failures == 1)
    mc.refresh_models()                       # 应被退避直接跳过
    check("退避后不再发起自动请求", mc._fetcher is None)
    mc._manual_refresh = True
    mc._on_models_failed_detail(ae.from_http(401))
    mc._on_models_failed("HTTP 401")
    check("手动刷新给出可操作提示",
          len(win.hints) == 1
          and ("建议" in win.hints[0] or "API Key" in win.hints[0]))
except Exception as exc:                              # noqa: BLE001
    check("ModelController 静默降级：%r" % (exc,), False)

# ===========================================================================
# 8) GUI 诊断面板 / 命令面板 / CLI 接入
# ===========================================================================
try:
    from ui.api_diag_dialog import offscreen_check as diag_check
    diag_res = diag_check()
    check("ApiDiagDialog offscreen 全通过",
          all(ok for _, ok in diag_res), "%d 项" % len(diag_res))
except Exception as exc:                              # noqa: BLE001
    check("ApiDiagDialog offscreen：%r" % (exc,), False)

mc_src = read(os.path.join("app", "model_controller.py"))
check("启动自动刷新失败后静默退避",
      "self._auto_refresh_disabled = True" in mc_src)
check("ModelController 兼容旧版无 failed_detail 的 fetcher",
      'hasattr(fetcher, "failed_detail")' in mc_src)
check("启动重复刷新有防抖", "isRunning" in mc_src)

assistant_src = read(os.path.join("app", "assistant.py"))
check("命令面板含 api_diag", '"api_diag"' in assistant_src)
check("AssistantApp 有 open_api_diag", "def open_api_diag" in assistant_src)
check("GUI spec 声明 ui.api_diag_dialog",
      '"ui.api_diag_dialog"' in read("starrystar.spec"))
check("CLI spec 声明 core.apierrors/apidiag",
      '"core.apierrors"' in read("starry_cli.spec")
      and '"core.apidiag"' in read("starry_cli.spec"))
check("core 懒导出 apierrors/apidiag",
      '"apierrors": "core.apierrors"' in read(os.path.join("core", "__init__.py"))
      and '"apidiag": "core.apidiag"' in read(os.path.join("core", "__init__.py")))
check("main.py 自检含 401 分类断言",
      "401 归为鉴权类" in read("main.py"))
check("e2e 隔离门禁存在",
      "隔离门禁失败，拒绝启动 GUI" in read(
          os.path.join("scripts", "e2e_session.py")))
# v13.3 起不再钉死单一发版号：每次更新都会升后代版本，只校验 SemVer 下限
_vtuple = tuple(int(x) for x in cfg_mod.APP_VERSION.split(".")[:3])
check("版本真源符合 SemVer 且不低于 13.3.0",
      len(cfg_mod.APP_VERSION.split(".")) == 3 and _vtuple >= (13, 3, 0),
      cfg_mod.APP_VERSION)

total = len(RESULTS)
passed = sum(1 for _, ok, _ in RESULTS if ok)
print("\n==== v13.2 企业级错误治理单测：%d/%d 通过 ====" % (passed, total))
for name, ok, extra in RESULTS:
    if not ok:
        print("  x", name, extra)
sys.exit(0 if passed == total else 1)
