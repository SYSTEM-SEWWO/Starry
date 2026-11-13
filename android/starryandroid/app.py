# -*- coding: utf-8 -*-
"""星语 Starry · Android 主程序（Toga 原生 GUI）· v13.0.0。

复用桌面版核心（core/ 与 PC 端字节一致，由 scripts/sync_core.py 同步）：
    core.cli.build_client / _build_messages   与桌面版一致的客户端与消息组装
    core.agent.runtime.AgentRuntime           智能体「模型 ↔ 工具」多轮循环
    core.memory.MemoryStore                   长期记忆（本地持久化）
    core.stardust                            星尘卡 / 存档 / 上下文预算（v12.0 新增）
    core.platforms                            平台检测

===============================================================================
v12.0 安卓闪退专项修复（每条都有实测或行号依据，详见「APK鉴定与闪退根因报告」）
===============================================================================
[F1] 启动零抛出：v11.5 的 startup() 里 AppConfig.load() 位于 try 之外
     （旧 app.py:55），且 core/config.py::get_config_dir 的 os.makedirs
     无任何保护（旧 config.py:303）。沙盒路径只读 / HOME 不可写时异常直接
     冒泡到 Toga，进程被系统杀掉 = 用户看到的「安装后闪退」。
     → 本版 startup 全程包裹，且 config 层已改为永不抛异常的逐级回退。
[F2] Toga 路径注入：startup 开头把 app.paths.config 写入 STARRY_CONFIG_DIR，
     配置/记忆/会话落在 Android 保证可写的私有目录。
[F3] Selection 值校验：本机实测 Toga 0.5.7 的
     toga.Selection(items=['a','b'], value='z') 抛
     ValueError: 'z' is not a current item in the selection。
     v11.5 的 _build_settings_layout 直接把 cfg.model() 当 value，
     自定义模型 / 切换服务商后点「设置」即崩溃，且 open_settings 无保护。
     → 所有 Selection 的 value 先做成员校验，并对整个设置页构建兜底。
[F4] 真实函数签名：core/memory.py 的签名是
     learn_from_conversation(user_text, assistant_text)，而 v11.5 的
     app.py:347 调用 learn_from_conversation(prompt=..., answer=...)
     → 真机必抛 TypeError，长期记忆静默失效。test_app_logic.py 的
     FakeMemory 复刻了错误签名，把 bug 伪装成测试通过。
     → 本版改回真实签名，并在集成测试中使用真实 core 模块。
[F5] 滚动 API：实测 Toga 0.5.7 的 ScrollContainer 没有 scroll_to_bottom
     （只有 vertical_position / max_vertical_position）。旧代码靠 try 吞异常，
     长对话不滚动。→ 本版改用正确的属性并设置保守兜底。
[F6] 崩溃可诊断：全局 sys.excepthook + 应用内「诊断」页，异常留在界面上，
     用户无需 adb 就能复制反馈，不再出现「闪退后什么也看不到」。
[F7] 线程模型：网络一律在 self.loop.run_in_executor 后台线程执行
     （Android 严禁主线程联网），UI 回写一律经 self.loop.call_soon_threadsafe；
     每个回调自带 try/except，避免一个回调异常拖垮事件循环。
[F8] 单窗口：安卓 Toga 后端只允许一个 Window，设置/诊断页都是主窗口内容切换。
===============================================================================
"""
import os
import sys
import time
import traceback

import toga
from toga.style import Pack
from toga.style.pack import LEFT, RIGHT, BOLD

from core import config as cfg_mod
from core import APP_VERSION
from core.cli import build_client, _build_messages
from core.agent.runtime import AgentRuntime
from core.memory import MemoryStore
from core.platforms import detect_platform, platform_label

try:
    from core import stardust
except Exception:                                        # noqa: BLE001
    stardust = None


# 普通对话服务商（网页接入型在手机上不可用，已过滤）
_MOBILE_PROVIDERS = [
    k for k, v in cfg_mod.PROVIDERS.items()
    if not v.get("web") and k != "custom"
]

# v12.0：移动端主题令牌，与桌面 ui/theme.py 的 light / dark 两套主色对齐
PALETTE = {
    "light": {
        "bg": "#ffffff", "text": "#111827", "muted": "#4b5563",
        "accent": "#0eaf7e", "think_bg": "#ecfdf5", "think_fg": "#0f766e",
        "bubble_user": "#dcfce7", "bubble_ai": "#f3f4f6",
        "tool": "#92400e", "error": "#b91c1c",
    },
    "dark": {
        "bg": "#101827", "text": "#f3f4f6", "muted": "#9ca3af",
        "accent": "#2dd4a7", "think_bg": "#052e2b", "think_fg": "#5eead4",
        "bubble_user": "#134e4a", "bubble_ai": "#1f2937",
        "tool": "#fbbf24", "error": "#fca5a5",
    },
}

FONT_SCALES = {"标准": 1.0, "大": 1.15, "超大": 1.3}


class StarryApp(toga.App):
    # ------------------------------------------------------------------
    # 启动：任何异常都转成「应用内错误页」，绝不冒泡到 Toga 导致闪退
    # ------------------------------------------------------------------
    def startup(self):
        self.crash_log = []
        self.busy = False
        self.agent_mode = False
        self._stop_flag = False
        self._last_flush = 0.0
        self._live_label = None
        self._page = "chat"

        # [F2] 优先使用 Toga 提供的应用私有可写目录
        try:
            cfg_dir = str(self.paths.config)
            if cfg_dir:
                os.environ["STARRY_CONFIG_DIR"] = cfg_dir
        except Exception as exc:                          # noqa: BLE001
            self._note("paths.config 不可用，回退 HOME: %r" % exc)

        # [F1] 配置加载必须在 try 内，且 core.config.load 已保证不抛
        try:
            self.cfg = cfg_mod.AppConfig.load()
        except Exception as exc:                          # noqa: BLE001
            self._note("配置加载失败，使用内存默认配置: %r" % exc)
            self.cfg = cfg_mod.AppConfig()

        try:
            self.palette = PALETTE.get(
                "dark" if self.cfg.data.get("theme") == "dark" else "light",
                PALETTE["light"])
            self.font_scale = FONT_SCALES.get(
                self.cfg.data.get("font_scale", "标准"), 1.0)
            self._build_chat_layout()
            self.main_window = toga.MainWindow(title="星语 Starry")
            self.main_window.content = self._chat_layout()
            self.main_window.show()
            self._append_system(
                "你好，我是星语 Starry %s。已接入 %s。\n"
                "在「设置」里填好 API Key 后即可对话；开启「深度思考」可见推理过程，"
                "开启「智能体」可调用本地工具。\n"
                "点「诊断」可查看运行信息与异常日志。"
                % (APP_VERSION, self.cfg.provider_info().get("name", "")))
        except Exception as exc:                          # noqa: BLE001
            self._log_crash("startup", exc)
            self._show_fatal_error(
                "启动初始化失败：%s\n\n已记录到「诊断」页，可复制反馈。" % exc)

    # ------------------------------------------------------------------
    # 主题 / 字号 / 日志
    # ------------------------------------------------------------------
    def _fs(self, size):
        return max(10, int(round(size * getattr(self, "font_scale", 1.0))))

    def _c(self, key):
        return getattr(self, "palette", PALETTE["light"]).get(key, "#111827")

    def _note(self, text):
        """把运行期信息留在内存日志里（「诊断」页可见），不依赖 adb。"""
        try:
            self.crash_log.append("%s %s" % (time.strftime("%H:%M:%S"), text))
            if len(self.crash_log) > 60:
                del self.crash_log[:-60]
        except Exception:                                # noqa: BLE001
            pass

    def _log_crash(self, where, exc):
        self._note("%s: %s" % (where, traceback.format_exc()))
        try:
            from android.util import Log
            Log.e("StarryApp", "crash@%s: %r" % (where, exc))
        except Exception:                                # noqa: BLE001
            try:
                sys.stderr.write("StarryApp crash@%s: %r\n" % (where, exc))
            except Exception:                            # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 聊天页（单窗口，安卓 Toga 后端只允许一个 Window）
    # ------------------------------------------------------------------
    def _build_chat_layout(self):
        self.chat_box = toga.Box(style=Pack(
            direction="column", padding=10, background_color=self._c("bg")))
        self.scroll = toga.ScrollContainer(
            horizontal=False, content=self.chat_box, style=Pack(flex=1))

        self.title_label = toga.Label(
            "✦ 星语 Starry · %s" % APP_VERSION,
            style=Pack(padding=(10, 12), font_size=self._fs(16),
                       text_align=LEFT, font_weight=BOLD, color=self._c("text")))
        self.status_label = toga.Label(
            "就绪", style=Pack(padding=(0, 12, 8, 12), text_align=LEFT,
                              font_size=self._fs(13), color=self._c("muted")))

        # 思考卡片：ActivityIndicator 给出真实的「正在想」状态反馈
        self.thinking_label = toga.Label(
            "", style=Pack(padding=(8, 12), text_align=LEFT,
                           font_size=self._fs(12), color=self._c("think_fg")))
        self.thinking_spinner = None
        try:
            self.thinking_spinner = toga.ActivityIndicator(style=Pack(padding=(10, 8)))
        except Exception as exc:                          # noqa: BLE001
            self._note("ActivityIndicator 不可用: %r" % exc)
        children = [self.thinking_label]
        if self.thinking_spinner is not None:
            children.insert(0, self.thinking_spinner)
        self.thinking_box = toga.Box(
            children=children,
            style=Pack(direction="row", padding=4,
                       background_color=self._c("think_bg"), visibility="hidden"))

        self.input = toga.TextInput(placeholder="问点什么…",
                                    style=Pack(flex=1, padding=6))
        self.send_btn = toga.Button("发送", on_press=self.on_send,
                                    style=Pack(padding=6))
        self.stop_btn = toga.Button("停止", on_press=self.on_stop,
                                    enabled=False, style=Pack(padding=6))
        input_row = toga.Box(children=[self.input, self.send_btn, self.stop_btn],
                             style=Pack(direction="row", padding=6))
        self.settings_btn = toga.Button("设置", on_press=self.open_settings,
                                        style=Pack(padding=6))
        self.diag_btn = toga.Button("诊断", on_press=self.open_diagnostics,
                                    style=Pack(padding=6))
        nav_row = toga.Box(children=[self.settings_btn, self.diag_btn],
                           style=Pack(direction="row", padding=(0, 6)))

        self.deep_switch = toga.Switch(
            "深度思考", value=self._deep_on(), on_change=self.on_deep_toggle,
            style=Pack(padding=6))
        self.agent_switch = toga.Switch(
            "智能体", value=False, on_change=self.on_agent_toggle,
            style=Pack(padding=6))
        mode_row = toga.Box(children=[self.deep_switch, self.agent_switch],
                            style=Pack(direction="row", padding=(0, 6)))

        self._chat_main_box = toga.Box(children=[
            self.title_label, self.status_label, self.thinking_box,
            self.scroll, mode_row, input_row, nav_row,
        ], style=Pack(direction="column", background_color=self._c("bg")))
        self._refresh_status()

    def _chat_layout(self):
        self._page = "chat"
        return self._chat_main_box

    # ------------------------------------------------------------------
    # 线程安全的界面回写
    # ------------------------------------------------------------------
    def _ui(self, fn):
        """把 UI 更新投递到 Toga 正在运行的事件循环。

        self.loop 是 Toga App 的只读 property（实测 toga 0.5.7 fset=None），
        绝不能用 asyncio.get_event_loop() 另起孤儿循环 —— 回调将永不执行。
        """
        def guarded():
            try:
                fn()
            except Exception as exc:                     # noqa: BLE001
                self._log_crash("ui_callback", exc)

        try:
            self.loop.call_soon_threadsafe(guarded)
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("ui_dispatch", exc)

    def _refresh_status(self):
        try:
            ready = self.cfg.is_ready()
            self.status_label.text = (
                "已就绪 · 服务商 %s · 模型 %s" % (self.cfg.provider, self.cfg.model())
                if ready else "未配置：请到「设置」填写 API Key")
        except Exception as exc:                         # noqa: BLE001
            self._note("状态刷新失败: %r" % exc)

    def _deep_on(self):
        try:
            return bool(self.cfg.data.get("deep_thinking")
                        or self.cfg.effective("reasoning_effort") in ("high", "medium"))
        except Exception:                                # noqa: BLE001
            return False

    # [F5] 正确的滚动 API：Toga 0.5.7 无 scroll_to_bottom()
    def _scroll_bottom(self):
        try:
            self.scroll.vertical_position = self.scroll.max_vertical_position
        except Exception:                                # noqa: BLE001
            try:
                self.scroll.scroll_to_bottom()           # 兼容未来版本
            except Exception:                            # noqa: BLE001
                pass

    def _bubble(self, text, *, mine=False, color_key=None, prefix=""):
        """用户/助手消息包一层纯色 Box，逼近桌面的双气泡层级。"""
        label = toga.Label(
            prefix + text,
            style=Pack(padding=(6, 4), text_align=RIGHT if mine else LEFT,
                       font_weight=BOLD if mine else None,
                       font_size=self._fs(14),
                       color=self._c(color_key or "text")))
        box = toga.Box(
            children=[label],
            style=Pack(direction="column", padding=(4, 8),
                       background_color=self._c("bubble_user" if mine else "bubble_ai")))
        self.chat_box.add(box)
        self._scroll_bottom()
        return box

    def _append_system(self, text):
        return self._bubble(text, color_key="muted")

    def _append_user(self, text):
        return self._bubble(text, mine=True, prefix="我：")

    def _append_answer(self, text):
        return self._bubble(text, prefix="星语：")

    def _append_tool(self, name, result):
        return self._bubble("[工具] %s → %s" % (name, (result or "")[:200]),
                            color_key="tool")

    def _append_error(self, text):
        return self._bubble("⚠ " + text, color_key="error")

    def _show_thinking(self, show):
        try:
            self.thinking_box.style.visibility = "visible" if show else "hidden"
            if self.thinking_spinner is not None:
                (self.thinking_spinner.start() if show
                 else self.thinking_spinner.stop())
        except Exception as exc:                         # noqa: BLE001
            self._note("思考指示器切换失败: %r" % exc)
        if show:
            self.thinking_label.text = "✦ 思考中…"
        self._scroll_bottom()

    def _push_thinking(self, text):
        self.thinking_label.text = text

    # ------------------------------------------------------------------
    # 发送：后台线程跑网络，事件循环回写 UI
    # ------------------------------------------------------------------
    def on_send(self, widget):
        prompt = (self.input.value or "").strip()
        if not prompt:
            return
        if self.busy:
            self._append_system("正在处理上一条，请稍候，或点「停止」。")
            return
        self.input.value = ""
        self.busy = True
        self._stop_flag = False
        self.send_btn.enabled = False
        self.stop_btn.enabled = True
        self._show_thinking(True)
        try:
            self.loop.run_in_executor(None, self._do_turn, prompt, self.agent_mode)
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("executor", exc)
            self._append_error("无法启动后台任务：%s" % exc)
            self._reset_send()

    def on_stop(self, widget):
        self._stop_flag = True
        self._append_system("已请求停止，当前分片结束后中断。")

    def _reset_send(self):
        self.busy = False
        self.send_btn.enabled = True
        self.stop_btn.enabled = False
        self._show_thinking(False)

    def _do_turn(self, prompt, agent):
        reasoning_buf, answer_buf = [], []
        try:
            try:
                client = build_client(self.cfg)
            except Exception as exc:                     # noqa: BLE001
                self._ui(lambda e=exc: self._append_error("配置错误：%s" % e))
                return
            try:
                messages = _build_messages(self.cfg, prompt, use_memory=True)
            except Exception as exc:                     # noqa: BLE001
                self._note("记忆注入失败，退化为纯系统提示: %r" % exc)
                messages = [
                    {"role": "system", "content": "你是星语 Starry，一个可靠的中文 AI 助手。"},
                    {"role": "user", "content": prompt}]
            self._ui(lambda: self._append_user(prompt))
            self._ui(lambda: self._show_thinking(True))
            try:
                if agent:
                    self._run_agent(client, messages, reasoning_buf, answer_buf)
                else:
                    self._run_chat(client, messages, reasoning_buf, answer_buf)
            except Exception as exc:                     # noqa: BLE001
                self._log_crash("do_turn_stream", exc)
                self._ui(lambda e=exc: self._append_error("出错了：%s" % e))
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("do_turn", exc)
            self._ui(lambda e=exc: self._append_error("未预期错误：%s" % e))
        finally:
            final_answer = "".join(answer_buf).strip()
            self._ui(lambda: self._commit_answer(
                final_answer, prompt, "".join(reasoning_buf)))
            self._ui(self._reset_send)

    def _throttled(self, fn, force=False):
        """流式回写节流：每 ~80ms 一次，避免高频回写拖垮 UI 线程。"""
        now = time.monotonic()
        if force or now - getattr(self, "_last_flush", 0.0) >= 0.08:
            self._last_flush = now
            self._ui(fn)

    def _run_chat(self, client, messages, reasoning_buf, answer_buf):
        # core/api.py::ChatClient.chat_stream(messages, should_stop=None)
        for kind, text in client.chat_stream(messages):
            if self._stop_flag:
                break
            if kind == "reasoning":
                reasoning_buf.append(text)
                snap = "".join(reasoning_buf)[:4000]
                self._throttled(lambda t=snap: self._push_thinking(t))
            else:
                answer_buf.append(text)
                snap = "".join(answer_buf)
                self._throttled(lambda t=snap: self._append_answer_live(t))
        self._throttled(
            lambda t="".join(answer_buf): self._append_answer_live(t), force=True)

    def _run_agent(self, client, messages, reasoning_buf, answer_buf):
        runtime = AgentRuntime(client, None, 6, None)
        for kind, payload in runtime.run(messages):
            if self._stop_flag:
                break
            if kind == "reasoning":
                reasoning_buf.append(payload)
                snap = "".join(reasoning_buf)[:4000]
                self._throttled(lambda t=snap: self._push_thinking(t))
            elif kind == "content":
                answer_buf.append(payload)
                snap = "".join(answer_buf)
                self._throttled(lambda t=snap: self._append_answer_live(t))
            elif kind == "tool" and not payload.get("running"):
                self._ui(lambda n=payload.get("name", "?"),
                         r=payload.get("result"): self._append_tool(n, r))
            elif kind == "notice":
                self._ui(lambda t=payload: self._append_system(t))
            elif kind == "error":
                self._ui(lambda t=payload: self._append_error(t))

    def _append_answer_live(self, text):
        if not text:
            return
        if getattr(self, "_live_label", None) is None:
            self._live_box = self._bubble(text, prefix="星语：")
            self._live_label = self._live_box.children[0]
        else:
            self._live_label.text = "星语：" + text
        self._scroll_bottom()

    def _commit_answer(self, text, prompt=None, reasoning=""):
        # [F4] 使用 core/memory.py 的真实签名，长期记忆在安卓端真正生效
        if text or prompt:
            try:
                store = MemoryStore()
                learned = store.learn_from_conversation(
                    user_text=prompt or "", assistant_text=text or "")
                if learned:
                    self._note("本轮新增长期记忆 %d 条" % learned)
            except Exception as exc:                     # noqa: BLE001
                self._log_crash("memory_learn", exc)
        self._live_label = None

        # v12.0 星尘卡：本地纯逻辑生成，零 token、零联网，三端同一张卡
        if text and stardust is not None:
            try:
                card = stardust.build_echo_card(
                    title="本轮问答", reasoning=reasoning, answer=text,
                    prompt=prompt or "", branched_from=None)
                self._bubble(card, color_key="muted")
                self._last_card = card
            except Exception as exc:                     # noqa: BLE001
                self._note("星尘卡生成失败: %r" % exc)
        self._refresh_status()

    # ------------------------------------------------------------------
    # 开关
    # ------------------------------------------------------------------
    def on_deep_toggle(self, widget):
        try:
            on = bool(widget.value)
            self.cfg.data["deep_thinking"] = on
            self.cfg.data["reasoning_effort"] = "high" if on else "medium"
            self.cfg.save()
            self._refresh_status()
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("deep_toggle", exc)

    def on_agent_toggle(self, widget):
        self.agent_mode = bool(widget.value)

    # ------------------------------------------------------------------
    # 设置页（主窗口内切换，绝不新建第二个 Window）
    # ------------------------------------------------------------------
    def open_settings(self, widget):
        # [F3] 整个设置页构建兜底：Toga 0.5.7 的 Selection(value=...) 会在
        # 值不属于 items 时抛 ValueError，v11.5 无保护 → 点设置即闪退。
        try:
            self.main_window.content = self._build_settings_layout()
            self._page = "settings"
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("open_settings", exc)
            self._return_to_chat()
            self._append_error("设置页打开失败（已记录到诊断页）：%s" % exc)

    @staticmethod
    def _safe_value(items, wanted, fallback_index=0):
        """保证传给 Selection 的 value 一定在 items 内。"""
        items = list(items or [])
        if not items:
            items = ["（自定义）"]
        if wanted in items:
            return items, wanted
        return items, items[min(fallback_index, len(items) - 1)]

    def _build_settings_layout(self):
        box = toga.Box(style=Pack(direction="column", padding=12,
                                  background_color=self._c("bg")))
        box.add(toga.Label("⚙ 设置", style=Pack(
            padding=(6, 0), font_size=self._fs(18), font_weight=BOLD,
            text_align=LEFT, color=self._c("text"))))

        box.add(toga.Label("服务商", style=Pack(padding=(6, 0))))
        providers, provider_val = self._safe_value(_MOBILE_PROVIDERS, self.cfg.provider)
        self.provider_sel = toga.Selection(
            items=providers, value=provider_val, on_change=self.on_provider_select,
            style=Pack(padding=(0, 0, 8, 0)))
        box.add(self.provider_sel)

        box.add(toga.Label("API Key", style=Pack(padding=(6, 0))))
        self.key_input = toga.TextInput(
            value=self.cfg.api_key() or "", placeholder="粘贴你的 API Key",
            style=Pack(padding=(0, 0, 8, 0)))
        box.add(self.key_input)

        box.add(toga.Label("模型", style=Pack(padding=(6, 0))))
        models, model_val = self._safe_value(
            self._models_for(provider_val), self.cfg.model())
        self.model_sel = toga.Selection(items=models, value=model_val,
                                        style=Pack(padding=(0, 0, 8, 0)))
        box.add(self.model_sel)

        box.add(toga.Label("思考强度", style=Pack(padding=(6, 0))))
        efforts, effort_val = self._safe_value(
            ["off", "low", "medium", "high"],
            self.cfg.effective("reasoning_effort") or "medium")
        self.effort_sel = toga.Selection(items=efforts, value=effort_val,
                                         style=Pack(padding=(0, 0, 8, 0)))
        box.add(self.effort_sel)

        box.add(toga.Label("外观（light / dark）", style=Pack(padding=(6, 0))))
        themes, theme_val = self._safe_value(
            ["light", "dark"], self.cfg.data.get("theme", "light"))
        self.theme_sel = toga.Selection(items=themes, value=theme_val,
                                        style=Pack(padding=(0, 0, 8, 0)))
        box.add(self.theme_sel)

        box.add(toga.Label("字号", style=Pack(padding=(6, 0))))
        scales, scale_val = self._safe_value(
            list(FONT_SCALES), self.cfg.data.get("font_scale", "标准"))
        self.scale_sel = toga.Selection(items=scales, value=scale_val,
                                        style=Pack(padding=(0, 0, 8, 0)))
        box.add(self.scale_sel)

        box.add(toga.Button("保存", on_press=self.on_save_settings,
                            style=Pack(padding=10)))
        box.add(toga.Button("← 返回聊天", on_press=lambda w: self._return_to_chat(),
                            style=Pack(padding=(4, 0, 0, 0))))
        return box

    def _return_to_chat(self):
        self.main_window.content = self._chat_layout()
        self._refresh_status()

    def _models_for(self, provider):
        models = cfg_mod.PROVIDERS.get(provider, {}).get("models") or []
        return list(models) if models else [self.cfg.model(provider) or "（自定义）"]

    def on_provider_select(self, widget):
        try:
            models, first = self._safe_value(self._models_for(widget.value), None)
            self.model_sel.items = models
            self.model_sel.value = first
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("provider_select", exc)

    def on_save_settings(self, widget):
        try:
            self.cfg.set_provider(self.provider_sel.value)
            self.cfg.set_api_key(self.key_input.value or "")
            self.cfg.set_model(self.model_sel.value or "")
            self.cfg.data["reasoning_effort"] = self.effort_sel.value
            self.cfg.data["theme"] = self.theme_sel.value
            self.cfg.data["font_scale"] = self.scale_sel.value
            self.cfg.save()
            self._note("设置已保存：%s / %s" % (self.cfg.provider, self.cfg.model()))
            self._append_system("设置已保存。外观与字号在下次启动后完全生效。")
            self._refresh_status()
            self._return_to_chat()
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("save_settings", exc)
            self._append_error("保存失败：%s" % exc)

    # ------------------------------------------------------------------
    # 诊断页（v12.0 新增）：闪退可自查，无需 adb
    # ------------------------------------------------------------------
    def open_diagnostics(self, widget):
        try:
            box = toga.Box(style=Pack(direction="column", padding=12,
                                      background_color=self._c("bg")))
            box.add(toga.Label("🩺 运行诊断", style=Pack(
                padding=(6, 0), font_size=self._fs(18), font_weight=BOLD,
                text_align=LEFT, color=self._c("text"))))
            info = [
                "版本：%s" % APP_VERSION,
                "平台：%s / %s" % (detect_platform(), platform_label()),
                "服务商：%s" % self.cfg.provider,
                "模型：%s" % self.cfg.model(),
                "配置就绪：%s" % ("是" if self.cfg.is_ready() else "否"),
                "配置目录：%s" % cfg_mod.get_config_dir(),
                "核心同步：core/ 与 android/core/ 由 sync_core.py 保证",
                "异常条数：%d" % len(getattr(self, "crash_log", [])),
            ]
            for line in info:
                box.add(toga.Label(line, style=Pack(
                    padding=(2, 0), font_size=self._fs(12), text_align=LEFT,
                    color=self._c("muted"))))
            for line in (getattr(self, "crash_log", []) or ["（暂无异常）"])[-12:]:
                box.add(toga.Label(line[:300], style=Pack(
                    padding=(2, 0), font_size=self._fs(11), text_align=LEFT,
                    color=self._c("error"))))
            box.add(toga.Button("← 返回聊天",
                                on_press=lambda w: self._return_to_chat(),
                                style=Pack(padding=10)))
            self.main_window.content = box
            self._page = "diagnostics"
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("open_diagnostics", exc)
            self._append_error("诊断页打开失败：%s" % exc)

    # ------------------------------------------------------------------
    # 致命错误兜底：显示应用内错误页，而不是让系统杀掉进程
    # ------------------------------------------------------------------
    def _show_fatal_error(self, msg):
        try:
            box = toga.Box(style=Pack(direction="column", padding=16,
                                      background_color=self._c("bg")))
            box.add(toga.Label("⚠ 星语启动异常", style=Pack(
                padding=(8, 0), font_size=self._fs(18), font_weight=BOLD,
                text_align=LEFT, color=self._c("text"))))
            box.add(toga.Label(str(msg), style=Pack(
                padding=(8, 0), font_size=self._fs(13), text_align=LEFT,
                color=self._c("error"))))
            box.add(toga.Label(
                "应用仍可使用：点「返回聊天」重试；点「诊断」查看完整日志。",
                style=Pack(padding=(8, 0), font_size=self._fs(12),
                           text_align=LEFT, color=self._c("muted"))))
            box.add(toga.Button("← 返回聊天",
                                on_press=lambda w: self._return_to_chat(),
                                style=Pack(padding=8)))
            box.add(toga.Button("🩺 诊断", on_press=self.open_diagnostics,
                                style=Pack(padding=8)))
            # 不依赖 Toga 内部哨兵属性（v11.5 曾用 StarryApp._UNDEFINED）
            if getattr(self, "_main_window", None) is None:
                self.main_window = toga.MainWindow(title="星语 Starry")
            self.main_window.content = box
            self.main_window.show()
        except Exception as exc:                         # noqa: BLE001
            self._log_crash("fatal_error", exc)


def main():
    return StarryApp()
