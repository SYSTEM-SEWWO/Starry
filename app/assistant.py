# -*- coding: utf-8 -*-
"""应用主控制器：装配各子系统并编排交互。

结构（v4 分层）：
- main.py                  入口：开屏 → 装配 → 运行
- app/assistant.py         本文件：装配编排 + 对话流程 + 对话框管理
- app/model_controller.py  模型管理（列表刷新 / 本地探测 / 视觉·推理切换）
- app/screenshot_controller.py  截图提问流程
- core/                   纯逻辑层（配置 / API / 模型 / 会话 / 导出 / 智能体）
- ui/                     Qt 视图层（悬浮球 / 聊天窗 / 对话框 / 动画）
"""
import os
import sys
import time

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QFileDialog

from core.attachment import Attachment
from core.config import AppConfig, PROVIDERS
from core.gateway import GatewayStats, KeyPool, route_pick
from core.web_sites import (create_site_client, get_site, is_web_site,
                            site_login_hint)
from core.agent.skills import SkillManager
from core.agent.market import PluginMarket
from core.sessions import SessionStore, message_text, trim_history
from core.context import trim_to_context, messages_tokens
from core.prompts import PromptLibrary
from core.hotkey import (HotkeyManager, DEFAULT_HOTKEY,
                         DEFAULT_QUICK_HOTKEY)
from core.stats import UsageStats
from core.tts import Speaker
from core.workers import ChatWorker, AgentWorker
from core.exporter import (conversation_to_markdown, conversation_to_json,
                           conversation_to_text, conversation_to_html,
                           conversation_to_pdf, available_formats,
                           export_all_sessions)
from core.sessions import build_summary_prompt, build_quoted_prompt
from core.insights import (session_stats, overview_stats, diff_sessions,
                           format_stats_markdown, format_diff_markdown)
from core.library import KnowledgeBase
from core.automation import AutomationManager
from core.mcp import McpManager
from core.screen import build_question, default_question, SCREEN_PRESETS
from core.memory import MemoryStore
from core.reasoning import StreamingThinkSplitter
from app.model_controller import ModelController
from app.screenshot_controller import ScreenshotController
from ui.floating_ball import FloatingBall, BallState
from ui.chat_window import ChatWindow
from ui.settings_dialog import SettingsDialog


# 支持思考强度（reasoning effort）下发的服务商（其余服务商自动忽略该参数）
EFFORT_SUPPORTED_PROVIDERS = {"openrouter", "deepseek", "zhipu",
                              "dashscope", "groq", "siliconflow",
                              "minimax", "together"}


def extract_html_artifact(content):
    """从一段文本中提取最后一个 ```html 代码块（产物预览用，纯函数可单测）。"""
    import re
    matches = re.findall(r"```html\s*(.*?)```", content, re.S | re.I)
    return matches[-1].strip() if matches else None


def make_tray_icon(theme=None):
    """绘制托盘图标（品牌色随主题切换：翠绿 / 天蓝）"""
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    from ui.theme import brand
    p.setBrush(QColor(brand(theme)["main"]))
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor(255, 255, 255))
    f = p.font()
    f.setPixelSize(26)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignCenter, "✦")
    p.end()
    return QIcon(pix)


class AssistantApp(QObject):
    """应用控制器：串联悬浮球、聊天窗口、托盘、设置与后台请求。

    模型管理与截图流程已拆分为独立控制器（self.models / self.shots），
    本类聚焦：装配编排、对话流、多会话与对话框管理。
    """

    _hotkey_triggered = pyqtSignal()     # 热键线程 → UI 线程的安全桥
    _quick_hotkey_triggered = pyqtSignal()  # v7.2 划词提问热键

    def __init__(self):
        super().__init__()
        self.qt = QApplication.instance() or QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.cfg = AppConfig.load()

        # 智能体：技能（专家人设）+ 插件市场（工具/技能/代码插件）
        self.skills = SkillManager(self.cfg)
        self.market = PluginMarket(self.cfg)
        # 资料库：本地文档导入 + TF-IDF 检索（复刻 WorkBuddy 资料库）
        self.library = KnowledgeBase()
        from core.agent.builtin import library as library_tools
        library_tools.set_store(self.library)
        # 自动化任务：定时 / 间隔执行提示词（复刻 WorkBuddy 自动化工作流）
        self.automation = AutomationManager()
        self._automation_running = set()
        # 多会话 / 提示词库 / 全局热键 / 用量统计
        self.sessions = SessionStore()
        self.prompts = PromptLibrary(self.cfg)
        self.hotkey = HotkeyManager(
            self.cfg.data.get("hotkey") or DEFAULT_HOTKEY,
            self._emit_hotkey)
        # v7.2：划词提问热键（第二条全局热键，可从设置关闭）
        self.quick_hotkey = HotkeyManager(
            self.cfg.data.get("quick_hotkey") or DEFAULT_QUICK_HOTKEY,
            self._emit_quick_hotkey)
        self._quick_win = None
        self.stats = UsageStats()
        if not os.path.exists(self.sessions.path):
            # 首次使用：自动创建的第一个会话计入统计
            self.stats.record_session()
            self.stats.save()
        self._about_dialog = None
        self._load_current_session()
        self.worker = None
        self._assistant_text = ""
        self._current_bubble = None
        self._settings = None
        self._market_dialog = None
        self._session_dialog = None
        self._prompt_dialog = None
        self._library_dialog = None
        self._automation_dialog = None
        self._panel_dialog = None
        self._mail_dialog = None
        self._models_dialog = None
        self._onboarding = None
        # v5 创新：语音朗读 / 命令面板 / 对话分支
        self.speaker = Speaker()
        self._palette = None
        self._pending_variants = []
        self._regenerating = False
        # v6 创新：网关统计 / 密钥池 / 网页版接入 / 网关仪表盘
        self.gateway_stats = GatewayStats.instance()
        self.keys = KeyPool(self.cfg)
        self._req_t0 = 0.0
        self._req_provider = ""
        self._req_model = ""
        self._gateway_dialog = None
        self._starred_dialog = None
        # v13.3：跨数据源全局搜索 + 本轮资料库来源引用
        self._global_search_dialog = None
        self._last_citations = []
        # v13.4：应用内 API Key 申请引导 / 缓存清理 / 模型能力
        self._apikey_guide = None
        self._cache_dialog = None
        # v13.5：开发者调试面板 / 自动缩放快照
        self._devtools_dialog = None
        self._applied_snapshot = {}
        # V11.4：消息引用 / 分支对话的消息选择器对话框
        self._message_picker = None
        # v7.3 补齐：MCP 工具生态（外部 MCP 服务器的工具接入智能体）
        # v7.5 安全护栏：危险（写/执行）工具来自非信任服务器时默认拒绝，
        # 需用户去设置标记为「信任」或会话内批准。
        self._mcp_approved = set()
        self.mcp = McpManager(self.cfg.data.get("mcp_servers") or [],
                              confirm_cb=self._mcp_confirm)
        # v8.0：长期记忆系统（跨会话持久化用户画像 / 偏好 / 项目背景）
        self.memory = MemoryStore()
        self._think_splitter = StreamingThinkSplitter()

        ap = self.cfg.appearance
        self.ball = FloatingBall(size=int(ap.get("ball_size", 56)))
        self.ball.set_theme(ap.get("theme"))
        self.window = ChatWindow(self.cfg)
        # 独立控制器：模型管理 / 截图流程
        self.models = ModelController(self.cfg, self.window,
                                      settings_provider=lambda: self._settings)
        self.shots = ScreenshotController(
            self.window, self.ball,
            theme_provider=lambda: self.cfg.appearance.get("theme"))
        self._wire_ball()
        self._wire_window()
        self._init_tray()
        self._restore_ball_position()
        # v13.2 启动优化：把「非首屏必需」的初始化（本地 GGUF 扫描 / 模型探测 /
        # 自动化定时器 / 全局热键）推迟到首屏亮相之后，缩短同步装配耗时。
        QTimer.singleShot(300, self._defer_background_init)
        self._pending_first_run_settings = not self.cfg.is_ready()
        self._pending_onboarding = not bool(self.cfg.data.get("onboarded"))
        # v7.3：后台接入 MCP 工具（默认无配置则不触发，零启动开销）
        self._mcp_state = {"done": False, "report": {}, "tools": 0}
        if self.mcp.entries:
            QTimer.singleShot(1200, self._connect_mcp_async)

    def _mcp_confirm(self, tool_id):
        """危险工具放行判定：会话内已批准 → 放行；否则拒绝（提示去信任）"""
        return tool_id in self._mcp_approved

    def _defer_background_init(self):
        """v13.2 启动优化：首屏亮相后异步执行的非关键初始化。

        把本地 GGUF 扫描 / 模型探测 / 自动化定时器 / 全局热键这些不阻塞首屏的
        工作从同步装配中剥离，app 更快进入可交互状态；任何一项失败都静默降级，
        不影响主流程。
        """
        for fn in (self._inject_local_gguf, self.models.init,
                   self._init_automation_timer, self._init_hotkey,
                   self._auto_scale_on_startup):
            try:
                fn()
            except Exception:                              # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # 会话加载
    # ------------------------------------------------------------------
    def _load_current_session(self):
        """把当前会话的消息灌入 history，并刷新标题"""
        session = self.sessions.current() or {}
        messages = list(session.get("messages") or [])
        if not messages or messages[0].get("role") != "system":
            prompt = self.skills.system_prompt_for()
            messages = ([{"role": "system", "content": prompt}]
                        + [m for m in messages if m.get("role") != "system"])
        self.history = messages
        self._session_title = session.get("title") or "新会话"

    # ------------------------------------------------------------------
    # 开屏结束后的首次亮相
    # ------------------------------------------------------------------
    def reveal(self):
        """开屏动画结束后调用：展示悬浮球，并按需弹出设置 / 新手引导"""
        self.ball.fade_in()
        self.window.set_memory_count(self.memory.count())
        # 有历史消息的会话：渲染到消息区
        real_msgs = [m for m in self.history
                     if m.get("role") in ("user", "assistant")]
        if real_msgs:
            self._render_history()
        if self._pending_first_run_settings:
            QTimer.singleShot(600, self.open_settings)
        elif self._pending_onboarding:
            QTimer.singleShot(900, self.start_onboarding)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------
    def _wire_ball(self):
        self.ball.clicked.connect(self.toggle_window)
        self.ball.settings_requested.connect(self.open_settings)
        self.ball.quit_requested.connect(self.quit)
        self.ball.position_changed.connect(self._on_ball_moved)

    def _wire_window(self):
        self.window.send_requested.connect(self.on_send)
        self.window.stop_requested.connect(self.on_stop)
        self.window.regenerate_requested.connect(self.on_regenerate)
        self.window.model_change_requested.connect(self.on_model_changed)
        self.window.settings_requested.connect(self.open_settings)
        self.window.minimize_requested.connect(self.minimize)
        self.window.closed.connect(self.minimize)
        self.window.screenshot_requested.connect(self.start_screenshot)
        self.window.deep_thinking_requested.connect(self.on_deep_thinking)
        self.window.skill_changed.connect(self.on_skill_changed)
        self.window.tools_changed.connect(self._on_tools_changed)
        self.window.market_requested.connect(self.open_market)
        self.window.automation_requested.connect(self.open_automation)
        self.window.speak_requested.connect(self.on_speak)
        self.window.variant_selected.connect(self._on_variant_selected)
        self.window.command_palette_requested.connect(self.open_command_palette)
        self.window.panel_requested.connect(self.open_panel)
        self.window.sessions_requested.connect(self.open_sessions)
        self.window.prompts_requested.connect(self.open_prompts)
        self.window.library_requested.connect(self.open_library)
        self.window.memory_requested.connect(self.open_memory)
        self.window.artifacts_requested.connect(self.open_artifacts)
        self.window.models_requested.connect(self.open_models)
        self.window.about_requested.connect(self.open_about)
        self.window.example_requested.connect(self._on_example_requested)
        self.window.set_agent_enabled(
            bool(self.cfg.data.get("agent_enabled", True)))
        self.window.set_session_title(self._session_title)

    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            # 无托盘环境（如部分 Linux 最小安装）下降级运行
            self.tray = None
            return
        self.tray = QSystemTrayIcon(make_tray_icon(self.cfg.appearance.get("theme")))
        self.tray.setToolTip("星语 · Starry — 液态玻璃桌面 AI 伙伴")
        menu = QMenu()
        menu.addAction("显示 / 隐藏", self.toggle_window)
        menu.addAction("截图提问", self.start_screenshot)
        menu.addAction("会话管理", self.open_sessions)
        menu.addAction("🔎 全局搜索", self.open_global_search)
        menu.addAction("🔑 申请 API Key 指引", self.open_apikey_guide)
        menu.addAction("🧹 清理应用缓存", self.open_cache_clean)
        menu.addAction("🛠 开发者调试面板", self.open_devtools)
        menu.addAction("资料库", self.open_library)
        menu.addAction("模型库（魔塔 GGUF）", self.open_models)
        menu.addAction("自动化任务", self.open_automation)
        menu.addAction("专家会诊", self.open_panel)
        menu.addAction("Agent 邮件", self.open_mail)
        menu.addAction("导出对话 (Markdown)", self.export_conversation)
        menu.addAction("提示词库", self.open_prompts)
        menu.addAction("🔊 朗读最后一条回复", self._speak_latest)
        menu.addAction("✨ 命令面板 (Ctrl+K)", self.open_command_palette)
        menu.addAction("🎨 切换主题", self._cycle_theme)
        menu.addAction("🛰 网关仪表盘", self.open_gateway)
        menu.addAction("关于 星语", self.open_about)
        menu.addAction("设置", self.open_settings)
        menu.addSeparator()
        menu.addAction("🗑 删除最后一条消息", self.delete_last_message)
        menu.addSeparator()
        menu.addAction("退出", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    # ------------------------------------------------------------------
    # 窗口显隐
    # ------------------------------------------------------------------
    def toggle_window(self):
        if self.window.isVisible():
            self.window._play_minimize()
        else:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
            self.window.play_open_animation()
            self.ball.hide()

    def minimize(self):
        self.window.save_geometry()
        self.window.hide()
        self.ball.show()
        self.ball.raise_()
        self.ball.fade_in()

    def _on_ball_moved(self, x, y):
        self.cfg.appearance["ball_position"] = [int(x), int(y)]
        self.cfg.save()

    def _restore_ball_position(self):
        screen = self.qt.desktop().availableGeometry(self.ball)
        pos = self.cfg.appearance.get("ball_position")
        if pos:
            x = min(max(int(pos[0]), screen.left()), screen.right() - self.ball.width())
            y = min(max(int(pos[1]), screen.top()), screen.bottom() - self.ball.height())
            self.ball.move(x, y)
        else:
            self.ball.move(screen.right() - self.ball.width() - 48,
                           screen.bottom() - self.ball.height() - 48)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.toggle_window()

    # ------------------------------------------------------------------
    # 对话流程
    # ------------------------------------------------------------------
    def on_send(self, text, attachments=None):
        attachments = attachments or []
        if self.worker is not None and self.worker.isRunning():
            return

        has_image = any(a.kind == Attachment.IMAGE for a in attachments)

        # v13.6.2：发送前能力守卫 —— 杜绝把图片发往「不支持视觉」的模型而触发
        # 服务端 HTTP 400（"does not support image inputs"）。
        # ensure_vision_model() 会尽量把当前模型切换为可用的视觉模型，并返回
        # 「当前模型能否看图」；若携带了图片但最终仍无视觉模型可用，则本地下掉
        # 图片、仅发送文字（并明确告知用户），而不是让请求 400 崩溃。
        allow_images = True
        images_dropped = False
        if has_image:
            allow_images = self.models.ensure_vision_model()
            images_dropped = not allow_images

        parts = []
        if text.strip():
            parts.append({"type": "text", "text": text.strip()})
        if allow_images:
            for att in attachments:
                if att.kind == Attachment.IMAGE:
                    parts.append({"type": "image_url",
                                  "image_url": {"url": att.data_url()}})
        file_blocks = [att.as_text_block() for att in attachments
                       if att.kind == Attachment.FILE]
        if file_blocks:
            parts.append({"type": "text", "text": "\n\n".join(file_blocks)})
        if not parts:
            return

        # 单条纯文本时退化为字符串，兼容性更好
        if len(parts) == 1 and parts[0]["type"] == "text":
            content = parts[0]["text"]
        else:
            content = parts

        self.history.append({"role": "user", "content": content})
        self.sessions.append({"role": "user", "content": content})
        self.window.add_user_message(text.strip(), attachments)
        self.stats.record_message(text)
        self.stats.save()

        if images_dropped:
            n = sum(1 for a in attachments if a.kind == Attachment.IMAGE)
            model = self.cfg.model()
            self.window.show_hint(
                "⚠️ 当前模型「%s」不支持图片理解，已忽略 %d 张图片、仅发送文字。"
                "如需让助手看图，请在 ⚙ 设置切换到视觉模型（如智谱 glm-4v-flash 免费），"
                "或在 LM Studio 加载视觉模型（如 llama-3.2-vision / MiniCPM-V）后本助手会自动切换。"
                % (model, n), 9000)

        if not self.cfg.is_ready():
            self.window.fail_message(
                "尚未完成 API 配置：请点击右上角 ⚙ 打开设置，选择服务商并填写 API Key"
                "（本地模型 Ollama / LM Studio 无需 Key）。")
            QTimer.singleShot(150, self.open_settings)
            return
        self._start_worker()

    def on_regenerate(self):
        if self.worker is not None and self.worker.isRunning():
            return
        if not self.history or self.history[-1].get("role") not in \
                ("user", "assistant"):
            return
        # 对话分支：旧回答收进变体列表，新回答并排为 ①②③…
        old = None
        if self.history[-1].get("role") == "assistant":
            old = self.history.pop()
        if old is None:
            self._pending_variants = []
        else:
            self._pending_variants = list(
                old.get("variants") or [old.get("content") or ""])
        self._regenerating = True
        self.window.remove_last_assistant()
        self._start_worker()

    def on_stop(self):
        if self.worker is not None:
            self.worker.stop()
        self.speaker.stop()

    def on_model_changed(self, name):
        name = (name or "").strip()
        if not name:
            return
        self.cfg.set_model(name)
        self.cfg.save()
        self.window._update_status()

    # ------------------------------------------------------------------
    # 语音朗读（v5 创新）
    # ------------------------------------------------------------------
    def on_speak(self, text):
        """朗读一条回复；朗读中再次触发 = 停止"""
        if not text or not text.strip():
            self.window.show_hint("这条消息还没有可朗读的内容")
            return
        if self.speaker.is_speaking():
            self.speaker.stop()
            self.window.show_hint("已停止朗读")
            return
        if not self.speaker.available():
            self.window.show_hint(
                "语音朗读需要可选依赖：pip install pyttsx3"
                "（并确保系统已安装 espeak 语音引擎）", 6000)
            return
        if self.speaker.speak(text):
            self.window.show_hint("🔊 正在朗读，再次点击「🔊 朗读」可停止", 6000)
        else:
            self.window.show_hint("朗读启动失败，请检查语音引擎")

    def _speak_latest(self):
        """朗读 history 中最后一条助手回复"""
        last = next((m for m in reversed(self.history)
                     if m.get("role") == "assistant" and m.get("content")), None)
        self.on_speak(last.get("content") if last else "")

    # ------------------------------------------------------------------
    # 命令面板（v5 创新：Ctrl+K 全局快捷入口）
    # ------------------------------------------------------------------
    def open_command_palette(self):
        from ui.command_palette import CommandPalette
        from ui.theme import get_theme
        theme = get_theme(self.cfg.appearance.get("theme", "light"))
        if self._palette is None:
            self._palette = CommandPalette(
                self._palette_commands(), self.window, theme)
            self._palette.command_triggered.connect(self._on_palette_command)
            self._palette.finished.connect(self._on_palette_closed)
        self._palette._reload("")
        self._palette.show()
        self._palette.raise_()

    def _on_palette_closed(self):
        self._palette = None

    def _palette_commands(self):
        """注册命令：(id, 图标, 标题, 说明, 分组)"""
        speaking = self.speaker.is_speaking()
        return [
            ("new_session", "🗨", "新建会话", "开始一段全新的对话", "会话"),
            ("sessions", "🗂", "会话管理", "搜索 / 切换 / 重命名 / 删除", "会话"),
            ("clear", "🗑", "清空当前会话", "删除本会话全部消息（不可恢复）", "会话"),
            ("settings", "⚙", "打开设置", "服务商 / 生成参数 / 外观", "设置"),
            ("apikey_guide", "🔑", "申请 API Key 指引",
             "分服务商的完整申请步骤，应用内说明不联网（v13.4）", "设置"),
            ("cache_clean", "🧹", "清理应用缓存",
             "扫描 → 勾选 → 二次确认 → 先备份可撤销（v13.4）", "其他"),
            ("devtools", "🛠", "开发者调试面板",
             "分级日志实时输出 / 环境信息 / 导出（v13.5）", "其他"),
            ("auto_scale", "🔎", "按屏幕自动适配缩放",
             "按 DPI / 分辨率自动设置缩放档与窗口尺寸（v13.5）", "外观"),
            ("models", "📦", "模型库（魔塔 GGUF）", "搜索并下载本地模型", "模型"),
            ("switch_model", "🔀", "切换到下一个模型", "在模型列表中循环切换", "模型"),
            ("model_route", "🧠", "智能选模型",
             "按本轮请求特征推荐模型并确认切换（v13.4）", "模型"),
            ("model_caps", "📊", "模型能力矩阵",
             "查看工具 / 视觉 / 推理 / 上下文能力（v13.4）", "模型"),
            ("auto_route_toggle", "🧭", "开关智能模型路由",
             "每轮自动按请求特征选模型（默认关，v13.4）", "模型"),
            ("deep_on", "🧠", "开启深度思考", "切换到推理模型", "模型"),
            ("deep_off", "💤", "关闭深度思考", "切回普通对话模型", "模型"),
            ("theme", "🎨", "切换主题", "翠绿 / 天蓝 / 墨夜 / 深蓝 循环", "外观"),
            ("gateway", "🛰", "网关仪表盘", "密钥轮询 · 失败退避 · 实时用量", "外观"),
            ("web_login", "🌐", "登录 DeepSeek 网页版", "打开浏览器完成登录（一次即可）", "模型"),
            ("web_login_zhipu", "🌐", "登录智谱清言网页版", "社区维护站点，打开浏览器登录", "模型"),
            ("web_login_doubao", "🌐", "登录豆包网页版", "社区维护站点，打开浏览器登录", "模型"),
            ("screenshot", "✂", "截图提问", "框选屏幕区域进行提问", "对话"),
            ("screen_qa", "👁", "看屏幕问答", "一键抓全屏并就屏幕内容提问", "对话"),
            ("quick_ask", "✂️", "划词提问", "对选中/复制的文字一键解释翻译总结", "对话"),
            ("roam", "🚶", ("关闭悬浮球漫游" if self.ball.roam() else "开启悬浮球漫游"),
             "闲置时伙伴会慢慢溜达并冒提示气泡", "外观"),
            ("speak", "🔊", ("停止朗读" if speaking else "朗读最后一条回复"),
             "TTS 语音播放 / 停止", "对话"),
            ("library", "📚", "打开资料库", "导入文档 / 检索引用", "知识"),
            ("global_search", "🔎", "全局搜索",
             "一次搜完会话 / 资料库 / 提示词 / 记忆 / 收藏（v13.3）", "知识"),
            ("citations", "📎", "本轮引用来源",
             "查看本轮回答引用了哪些资料（v13.3）", "知识"),
            ("prompts", "📖", "提示词库", "插入常用提示词", "知识"),
            ("market", "🧩", "插件市场", "工具 / 技能 / 代码插件", "智能体"),
            ("rea", "🔍", "REA 逆向工程", "一键接入 REA（GitHub 爆火 MCP 逆向工具）", "智能体"),
            ("panel", "🎭", "专家会诊", "多专家视角会诊当前问题", "智能体"),
            ("mail", "✉️", "Agent 邮件", "本地优先读取 / 摘要 / 草拟回复", "智能体"),
            ("automation", "⏰", "自动化任务", "定时 / 间隔执行提示词", "智能体"),
            ("export", "📝", "导出当前对话", "保存为 Markdown / PDF 等格式", "文件"),
            ("export_all", "📦", "批量导出全部会话", "合并全部会话导出为 md/zip 等", "文件"),
            ("star_last", "⭐", "收藏最后回复", "收藏 / 取消收藏最后一条 AI 回复", "对话"),
            ("starred", "📌", "收藏夹", "查看全部已收藏的消息并跳转", "对话"),
            ("summary", "📋", "AI 总结当前会话", "让模型提炼本会话要点并缓存", "对话"),
            ("quote_pick", "💬", "引用消息追问", "选一条历史消息作为引用，针对它提问", "对话"),
            ("quote_last", "↩️", "引用最后回复", "引用最后一条 AI 回复并追问", "对话"),
            ("branch", "🌿", "分支对话", "从某条消息处复制出一个新会话继续", "对话"),
            ("branches", "🌱", "分支列表", "查看由当前会话派生的分支并跳转", "对话"),
            ("insight", "📊", "对话统计洞察", "当前会话 + 全局消息 / token / 收藏统计", "对话"),
            ("diff", "🔀", "分支对比", "对比当前会话与另一会话的消息差异", "对话"),
            ("merge", "🧬", "会话合并", "把另一会话的消息合并进当前会话（自动去重）", "对话"),
            ("delete_last", "🗑", "删除最后一条消息", "撤回刚发出 / 收到的最后一条", "对话"),
            ("artifacts", "🧪", "产物预览", "在浏览器预览最近回复里的 HTML 产物", "文件"),
            # ---- v12.0 电脑端新功能（与 CLI / 安卓共用 core.stardust）----
            ("echo_card", "✦", "生成本轮星尘卡", "本地生成可复制的问答小卡，零 token", "对话"),
            ("budget_plan", "📐", "上下文预算裁剪", "离线给出保留/裁剪消息的确定性计划", "对话"),
            ("archive_export", "📤", "导出 .starry 存档", "会话 + 长期记忆打包，带校验和", "文件"),
            ("archive_import", "📥", "导入 .starry 存档", "先验签再导入，自动备份原数据", "文件"),
            ("doctor", "🩺", "运行环境自检", "版本 / 依赖 / 三端同源一键核查", "其他"),
            # ---- v13.0 大版本：整体项目 → 多线并行 → 自动更新（电脑端工作台）----
            ("workbench", "🗂", "打开整体项目工作台",
             "目标 → 任务树 → 分波并行 → 报告，一站式（v13.0）", "项目"),
            ("project_plan", "🧭", "从当前对话规划项目",
             "用最近一次提问生成整体项目（v13.0）", "项目"),
            ("project_run", "⚡", "规划并多线并行执行",
             "一键跑完整体项目的分波并行（v13.0）", "项目"),
            ("project_save", "💾", "保存整体项目",
             "导出 .starryproj，带 SHA-256 校验（v13.0）", "项目"),
            ("project_load", "📂", "载入整体项目",
             "从 .starryproj 恢复，校验失败拒绝（v13.0）", "项目"),
            ("update_check", "🔄", "检查版本更新",
             "校验 update.json，列出平台资产（v13.0）", "项目"),
            # ---- v13.1 Skills Hub（兼容主流 Skills 生态 + 技能更新）----
            ("hub", "🧩", "打开 Skills Hub",
             "浏览 Claude Code / GitHub / WorkBuddy 技能（v13.1）", "项目"),
            ("hub_update", "🔄", "检查技能更新",
             "选 hub.json 校验并比对技能版本（v13.1）", "项目"),
            # ---- v13.2 企业级错误治理 ----
            ("api_diag", "🩺", "API 诊断",
             "查看最近 API 失败的脱敏分类与可操作建议（v13.2）", "其他"),
            ("about", "✦", "关于本程序", "版本与功能清单", "其他"),
            # 「看屏幕」预设问题（core.screen.SCREEN_PRESETS）
            *[("screen_qa::%s" % name, "👁", name, q[:26], "对话")
              for name, q in SCREEN_PRESETS],
        ]

    def _on_palette_command(self, cid):
        if cid == "new_session":
            self._save_current_session()
            self.sessions.create()
            self._load_current_session()
            self._render_history()
            self.window.show_hint("已开始新会话")
        elif cid == "sessions":
            self.open_sessions()
        elif cid == "clear":
            self._clear_current_session()
        elif cid == "settings":
            self.open_settings()
        elif cid == "apikey_guide":
            self.open_apikey_guide()
        elif cid == "cache_clean":
            self.open_cache_clean()
        elif cid == "devtools":
            self.open_devtools()
        elif cid == "auto_scale":
            self.apply_auto_scale()
        elif cid == "models":
            self.open_models()
        elif cid == "switch_model":
            self._cycle_model()
        elif cid == "model_route":
            self.open_model_route()
        elif cid == "model_caps":
            self.open_model_capabilities()
        elif cid == "auto_route_toggle":
            self.toggle_auto_route()
        elif cid == "deep_on":
            self.window.deep_btn.setChecked(True)
            self.on_deep_thinking(True)
        elif cid == "deep_off":
            self.window.deep_btn.setChecked(False)
            self.on_deep_thinking(False)
        elif cid == "theme":
            self._cycle_theme()
        elif cid == "gateway":
            self.open_gateway()
        elif cid == "web_login":
            self._switch_to_web()
            self.open_web_login()
        elif cid == "web_login_zhipu":
            self._switch_to_web("web_zhipu")
            self.open_web_login("web_zhipu")
        elif cid == "web_login_doubao":
            self._switch_to_web("web_doubao")
            self.open_web_login("web_doubao")
        elif cid == "screenshot":
            self.start_screenshot()
        elif cid.startswith("screen_qa"):
            label = cid.split("::", 1)[1] if "::" in cid else None
            self.start_screen_qa(label)
        elif cid == "quick_ask":
            self.open_quick_ask()
        elif cid == "roam":
            self.toggle_roam()
        elif cid == "speak":
            if self.speaker.is_speaking():
                self.speaker.stop()
                self.window.show_hint("已停止朗读")
            else:
                self._speak_latest()
        elif cid == "library":
            self.open_library()
        elif cid == "global_search":
            self.open_global_search()
        elif cid == "citations":
            self.open_citations()
        elif cid == "prompts":
            self.open_prompts()
        elif cid == "market":
            self.open_market()
        elif cid == "rea":
            self.open_rea()
        elif cid == "panel":
            self.open_panel()
        elif cid == "automation":
            self.open_automation()
        elif cid == "export":
            self.export_conversation()
        elif cid == "export_all":
            self.export_all_sessions()
        elif cid == "star_last":
            self.toggle_star_last()
        elif cid == "starred":
            self.open_starred()
        elif cid == "summary":
            self.summarize_current_session()
        elif cid == "quote_pick":
            self.open_quote_picker()
        elif cid == "quote_last":
            self.quote_last_reply()
        elif cid == "branch":
            self.open_branch_picker()
        elif cid == "branches":
            self.open_branches()
        elif cid == "insight":
            self.open_insight()
        elif cid == "diff":
            self.open_diff_picker()
        elif cid == "merge":
            self.open_merge_picker()
        elif cid == "delete_last":
            self.delete_last_message()
        elif cid == "artifacts":
            self.open_artifacts()
        # ---- v12.0 新增命令 ----
        elif cid == "echo_card":
            self.open_echo_card()
        elif cid == "budget_plan":
            self.open_budget_plan()
        elif cid == "archive_export":
            self.open_archive_export()
        elif cid == "archive_import":
            self.open_archive_import()
        elif cid == "doctor":
            self.open_doctor()
        # ---- v13.0 整体项目工作台（命令面板是工作台的快捷入口）----
        elif cid == "workbench":
            self.open_workbench()
        elif cid == "project_plan":
            self.open_workbench(goal=self._suggest_goal())
        elif cid == "project_run":
            self.open_workbench(action="run", goal=self._suggest_goal())
        elif cid == "project_save":
            self.open_workbench(action="save", goal=self._suggest_goal())
        elif cid == "project_load":
            self.open_workbench(action="load")
        elif cid == "update_check":
            self.open_workbench(action="update")
        # ---- v13.1 Skills Hub ----
        elif cid == "hub":
            self.open_hub()
        elif cid == "hub_update":
            self.open_hub(action="update")
        # ---- v13.2 企业级错误治理 ----
        elif cid == "api_diag":
            self.open_api_diag()
        elif cid == "about":
            self.open_about()

    # ------------------------------------------------------------------
    # v12.0 电脑端新功能：星尘卡 / 上下文预算 / .starry 存档 / 环境自检
    # 全部复用 core.stardust 与 core.cli，与 CLI 版、安卓版同一份逻辑。
    # ------------------------------------------------------------------
    def _current_messages(self):
        """取当前会话消息（只读，返回新列表）。"""
        from core.insights import message_content
        self._save_current_session()
        sid = self.sessions.current_id()
        cur = self.sessions.get(sid) or {}
        out = []
        for m in (cur.get("messages") or []):
            if not isinstance(m, dict):
                continue
            out.append({
                "role": m.get("role", ""),
                "content": message_content(m),
                "reasoning": m.get("reasoning", "") or "",
            })
        return cur, out

    def open_echo_card(self):
        """✦ 用本地纯逻辑把本轮问答收成一张星尘卡（零 token、零联网）。"""
        import time
        from core import stardust
        from ui.insight_dialog import InsightDialog
        cur, msgs = self._current_messages()
        prompt = answer = reasoning = ""
        for m in reversed(msgs):
            if m["role"] == "assistant" and not answer:
                answer = m["content"]
                reasoning = m.get("reasoning", "")
            elif m["role"] == "user" and not prompt:
                prompt = m["content"]
            if prompt and answer:
                break
        if not answer:
            self.window.show_hint("当前会话还没有可生成卡片的回答")
            return
        card = stardust.build_echo_card(
            title=cur.get("title") or "本轮问答", reasoning=reasoning,
            answer=answer, prompt=prompt,
            branched_from=cur.get("branched_from"),
            ts=time.strftime("%Y-%m-%d %H:%M"))
        InsightDialog(card, "✦ 星尘卡", self.window).exec_()

    def open_budget_plan(self):
        """📐 离线给出当前会话的上下文裁剪计划，不修改任何数据。"""
        from core import stardust
        from ui.insight_dialog import InsightDialog
        cur, msgs = self._current_messages()
        budget = int(self.cfg.data.get("max_tokens", 4096) or 4096)
        plan = stardust.plan_trim(msgs, budget, policy="keep_recent")
        md = [
            "# 📐 上下文预算裁剪计划", "",
            "- 会话：**%s**" % (cur.get("title") or "未命名"),
            "- 预算上限：**%d tokens**" % plan["max_tokens"],
            "- 消息总数：**%d**，估算总量 **%d tokens**" % (len(msgs), plan["total_tokens"]),
            "- 建议保留 **%d** 条（约 %d tokens），裁剪 **%d** 条"
            % (len(plan["keep_indices"]), plan["kept_tokens"],
               len(plan["drop_indices"])),
            "", "保留下标：`%s`" % plan["keep_indices"],
            "", "裁剪下标：`%s`" % plan["drop_indices"], "",
            "> 离线相对估算，不代表任何模型的精确计费；此面板只读，不修改会话。",
        ]
        InsightDialog("\n".join(md), "📐 上下文预算", self.window).exec_()

    def open_archive_export(self):
        """📤 导出 .starry 存档（复用 core.cli._run_archive，保证三端口径一致）。"""
        import io
        from PyQt5.QtWidgets import QFileDialog
        from core import cli as cli_mod
        path, _ = QFileDialog.getSaveFileName(
            self.window, "导出 .starry 存档", "星语备份.starry",
            "星语存档 (*.starry);;所有文件 (*)")
        if not path:
            return
        buf = io.StringIO()
        rc = cli_mod._run_archive(path, buf)
        self.window.show_hint(
            ("已导出 %s" % path) if rc == 0 else buf.getvalue().strip()[:120])

    def open_archive_import(self):
        """📥 导入 .starry 存档（先验签，再备份，最后落盘）。"""
        import io
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        from core import cli as cli_mod
        path, _ = QFileDialog.getOpenFileName(
            self.window, "导入 .starry 存档", "",
            "星语存档 (*.starry);;所有文件 (*)")
        if not path:
            return
        confirm = QMessageBox.question(
            self.window, "📥 确认导入",
            "将从存档恢复会话与长期记忆；现有数据会自动备份为 *.bak。\n继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        buf = io.StringIO()
        rc = cli_mod._run_restore(path, buf)
        if rc == 0:
            self._load_current_session()
            self._render_history()
        self.window.show_hint(buf.getvalue().strip()[:140])

    def open_doctor(self):
        """🩺 运行环境自检（版本 / 依赖 / 三端同源）。"""
        import io
        from core import cli as cli_mod
        from ui.insight_dialog import InsightDialog
        buf = io.StringIO()
        cli_mod._run_doctor(buf)
        InsightDialog("```\n" + buf.getvalue() + "\n```",
                      "🩺 运行环境自检", self.window).exec_()

    # ------------------------------------------------------------------
    # v13.0 整体项目工作台（WorkBuddy 式）
    # 逻辑全部在 core.project / core.parallel / core.updatecheck，
    # 这里只负责「从哪拿目标、打开哪个动作」，避免与 UI 层重复实现。
    # ------------------------------------------------------------------
    def _suggest_goal(self):
        """从内存中的当前会话取最近一次提问作为项目目标（不写磁盘）。"""
        from core.insights import message_content
        for m in reversed(getattr(self, "history", []) or []):
            if isinstance(m, dict) and m.get("role") == "user":
                text = (message_content(m) or "").strip()
                if text:
                    return text[:80]
        return "梳理当前目标：盘点资料、提炼要点、草拟方案并复核汇总"

    def open_workbench(self, action=None, goal=None):
        """打开整体项目工作台；action 可预设 save / load / update / run。"""
        from ui.workbench_dialog import WorkbenchDialog
        dlg = WorkbenchDialog(self.window, initial_goal=goal or "")
        if action == "run":
            if dlg.project is None:
                dlg.goal_edit.setText(goal or self._suggest_goal())
                dlg._on_plan()
            dlg._on_run()
        elif action == "save":
            if dlg.project is None:
                dlg.goal_edit.setText(goal or self._suggest_goal())
                dlg._on_plan()
            dlg._on_save()
        elif action == "load":
            dlg._on_load()
        elif action == "update":
            dlg._on_update_check()
        dlg.exec_()

    def open_hub(self, action=None):
        """打开 Skills Hub；action=update 时直接调起技能更新检查。"""
        from ui.hub_dialog import HubDialog
        dlg = HubDialog(self.window,
                        cfg=getattr(self.window, "cfg", None))
        if action == "update":
            dlg._on_check_update()
        dlg.exec_()

    def open_api_diag(self):
        """v13.2：打开 API 诊断面板（脱敏、可复制、可清空）。"""
        from ui.api_diag_dialog import ApiDiagDialog
        ApiDiagDialog(self.window).exec_()

    def _cycle_model(self):
        """在窗口模型下拉中循环切换到下一个模型"""
        combo = getattr(self.window, "model_combo", None)
        if combo is None or combo.count() < 2:
            self.window.show_hint("模型列表为空，请先在设置中选择服务商")
            return
        combo.setCurrentIndex((combo.currentIndex() + 1) % combo.count())

    def _cycle_theme(self):
        """四主题循环切换（翠绿 / 天蓝 / 墨夜 / 深蓝）"""
        from ui.theme import THEME_LABELS
        order = ["light", "sky", "dark", "sky_dark"]
        cur = self.cfg.appearance.get("theme", "light")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "light"
        self.cfg.appearance["theme"] = nxt
        self._apply_settings()
        self.window.show_hint("已切换主题：%s" % THEME_LABELS.get(nxt, nxt))

    def _clear_current_session(self):
        """清空当前会话（保留系统提示）"""
        if self.worker is not None and self.worker.isRunning():
            self.window.show_hint("正在生成回复，稍后再清空")
            return
        system = [self.history[0]] if (self.history and
                                       self.history[0].get("role") == "system") else []
        prompt = self.skills.system_prompt_for()
        if not system:
            system = [{"role": "system", "content": prompt}]
        self.history = system
        self.sessions.set_messages(list(self.history))
        self.window.clear_messages()
        self.window.show_welcome()
        self.window.show_hint("已清空当前会话")

    # ------------------------------------------------------------------
    # 网关仪表盘（v6 旗舰界面）
    # ------------------------------------------------------------------
    def open_gateway(self):
        from ui.gateway_dialog import GatewayDialog
        if self._gateway_dialog is None:
            self._gateway_dialog = GatewayDialog(self.cfg, self.window)
            self._gateway_dialog.finished.connect(
                lambda: setattr(self, "_gateway_dialog", None))
        from ui.theme import get_theme
        self._gateway_dialog.apply_theme(
            get_theme(self.cfg.appearance.get("theme", "light")))
        self._gateway_dialog.show()
        self._gateway_dialog.raise_()

    # ------------------------------------------------------------------
    # 网页版接入（v6：DeepSeek 网页版浏览器 harness）
    # ------------------------------------------------------------------
    def open_web_login(self, site_key=None):
        """弹出浏览器引导登录网页版（登录态持久化）。

        v7：登录指定网页站点（DeepSeek / 智谱清言 / 豆包）；
        未指定时用当前 provider（是网页站点则登它，否则默认 DeepSeek）。
        """
        from core.browser_llm import browser_guidance
        if not site_key:
            site_key = self.cfg.provider if is_web_site(self.cfg.provider) \
                else "web_deepseek"
        if "未安装" in browser_guidance():
            self.window.show_hint(
                "网页版模式需要 Playwright：pip install playwright\n"
                "然后执行 playwright install chromium", 8000)
            return
        self.window.show_hint(site_login_hint(site_key), 6000)
        client = create_site_client(site_key, self.cfg)
        ok, detail = client.login_status()
        if ok:
            self.window.show_hint("✓ %s 已登录，可直接使用"
                                  % get_site(site_key)["name"], 5000)
        else:
            self.window.show_hint("网页版登录未完成：%s" % detail[:80], 8000)

    def _switch_to_web(self, site_key="web_deepseek"):
        """切换到网页版 provider（设置/命令面板共用，默认 DeepSeek）"""
        from core.browser_llm import playwright_available
        if not is_web_site(site_key):
            site_key = "web_deepseek"
        if not playwright_available():
            # 前置条件尽早暴露：切换时就告知，而不是等第一次提问才报错
            self.window.show_hint(
                "⚠ 网页版模式需要 Playwright：pip install playwright\n"
                "然后执行 playwright install chromium\n"
                "（或在设置 → 网页接入页点「一键安装浏览器内核」）", 9000)
        self.cfg.set_provider(site_key)
        self.cfg.save()
        self.models.reload_combo()
        self.window._update_status()
        self.window.show_hint(
            "已切换到%s。首次提问会弹出浏览器，请登录一次"
            % get_site(site_key)["name"], 6000)

    def on_deep_thinking(self, on):
        """🧠 深度思考：委托模型控制器在普通 / 推理模型间切换"""
        self.models.set_deep_thinking(on)

    def _effective_client(self):
        """按当前模型构造客户端（模型级覆盖 > 全局默认）

        分支：
        - web_deepseek  → 浏览器 harness 客户端（DeepSeek 网页版）
        - 其余          → OpenAI 兼容 ChatClient
        路由策略（网关）：fastest / manual 时按统计临时切换服务商。
        """
        from core.api import ChatClient  # 懒加载：把 requests/urllib3 推到首次请求时
        provider = self.cfg.provider
        gw = self.cfg.data.get("gateway") or {}
        policy = gw.get("route_policy", "auto")
        if policy in ("fastest", "manual"):
            picked = route_pick(policy, GatewayStats.instance().summary(),
                                gw.get("manual_provider"), provider)
            if picked and picked in PROVIDERS and picked != provider:
                provider = picked
                self.window.show_hint(
                    "🛰 网关路由：本次请求已切换至「%s」"
                    % PROVIDERS[picked].get("name", picked), 4000)
        if is_web_site(provider):
            # v7：任意网页站点（DeepSeek / 智谱清言 / 豆包）统一走 harness
            return create_site_client(provider, self.cfg)
        effort = self.cfg.effective("reasoning_effort")
        # 思考强度仅对已知支持的服务商下发，其余自动忽略
        if provider not in EFFORT_SUPPORTED_PROVIDERS:
            effort = None
        top_p = float(self.cfg.effective("top_p") or 1.0)
        if abs(top_p - 1.0) < 1e-6:
            top_p = None
        return ChatClient(
            base_url=self.cfg.base_url(provider),
            api_key=self.cfg.api_key(provider),
            model=self.cfg.model(provider),
            temperature=float(self.cfg.effective("temperature") or 0.7),
            max_tokens=int(self.cfg.effective("max_tokens") or 4096),
            top_p=top_p,
            reasoning_effort=effort,
        )

    def _start_worker(self):
        # v13.4 智能模型路由：在构造 ChatClient 之前按本轮特征切换模型
        if self.cfg.data.get("auto_route_model", False):
            try:
                self._apply_auto_route(silent=True)
            except Exception:                           # noqa: BLE001
                pass                                    # 路由失败不影响正常请求
        from core import devlog
        devlog.info("request", "发起请求", provider=self.cfg.provider,
                    model=self.cfg.model(), history=len(self.history))
        client = self._effective_client()
        self._assistant_text = ""
        self._req_t0 = time.time()
        self._req_provider = self.cfg.provider
        self._req_model = self.cfg.model()
        # 资料库自动注入：把本轮问题的相关片段作为系统消息送给模型
        # （不写入 history，避免污染后续上下文）
        messages = list(self.history)
        last_user = next((m for m in reversed(messages)
                          if m.get("role") == "user"), None)
        if last_user is not None:
            ctx = self._library_context(message_text(last_user))
            if ctx:
                sys_idx = 1 if (messages and messages[0].get("role") == "system") else 0
                messages.insert(sys_idx, {"role": "system", "content": ctx})
            # 资料库引用角标：命中检索时点亮最后一条用户消息（v13.3 显示来源数）
            n_cite = len(self._last_citations or [])
            self.window.set_last_user_badge(
                ("📎 已引用 %d 份资料 · 命令面板可查看来源" % n_cite)
                if n_cite else
                ("📚 已引用资料库片段作为回答依据" if ctx else ""))
        # 上下文裁剪：按「上下文大小」保留系统消息与最近对话
        limit = int(self.cfg.effective("context_window") or 32768)
        messages, used, dropped = trim_to_context(messages, limit)
        if dropped:
            self.window.show_hint(
                "上下文已达上限，已自动省略最早的 %d 条消息" % dropped, 4000)
        self.window.set_context_usage(used, limit)
        tools = set()
        if bool(self.cfg.data.get("agent_enabled", True)):
            tools = self.market.enabled_tools()
        if is_web_site(self._req_provider):
            # 网页版没有函数调用能力：禁用工具，走普通对话
            tools = set()
        if tools:
            # 智能体模式：模型可调用工具，多轮循环
            self.worker = AgentWorker(
                client, messages, tools,
                max_iterations=int(self.cfg.data.get("agent_max_iterations", 6)))
            self.worker.tool_call.connect(self._on_tool_call)
            self.worker.notice.connect(self._on_agent_notice)
        else:
            self.worker = ChatWorker(client, messages)
        self.worker.reasoning.connect(self._on_reasoning)
        self.worker.content.connect(self._on_content)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self._think_splitter = StreamingThinkSplitter()   # v8.0：本轮重新计数
        self.ball.set_state(BallState.THINKING)
        self.window.set_busy(True)
        bubble = self.window.start_assistant_message()
        bubble.thinking.start()
        self._current_bubble = bubble
        self.worker.start()

    def _on_tool_call(self, info):
        """工具调用生命周期 → 气泡中的 chip"""
        bubble = self._current_bubble
        if bubble is None:
            return
        if info.get("running"):
            bubble.add_tool_call(info.get("name", "工具"), info.get("args"))
            self.ball.set_state(BallState.THINKING)
        else:
            bubble.complete_tool_call(info.get("name", "工具"),
                                      info.get("result", ""))
            self.stats.record_tool_call()
            self.stats.save()

    def _on_agent_notice(self, text):
        self.window.show_hint(text, 6000)

    def _on_tools_changed(self):
        """工具开关变化：更新状态栏提示"""
        n = len(self.market.enabled_tools())
        self.window.show_hint("当前生效工具 %d 个" % n if n
                              else "已关闭全部工具（普通对话模式）")

    def _on_reasoning(self, text):
        self.window.append_reasoning(text)
        # v9.0：同步把流式思考推到悬浮球（液态玻璃字幕 + 微光）
        self.ball.show_thinking_text(text)

    def _on_content(self, text):
        # v8.0：部分模型把思考包进 <think> 随正文返回，剥离后单独走思考块
        think, ans = self._think_splitter.feed(text)
        if think:
            self._on_reasoning(think)
        if ans:
            self._append_answer(ans)

    def _append_answer(self, text):
        if not self._assistant_text:
            self.ball.set_state(BallState.SPEAKING)   # 首个正文 → 输出动画
        self._assistant_text += text
        self.window.append_content(text)

    def _on_finished(self):
        from core import devlog
        devlog.info("request", "请求完成",
                    ms=round((time.time() - self._req_t0) * 1000, 1),
                    chars=len(self._assistant_text))
        # v8.0：收尾思考分片（极少数未 flushed 的尾部字符）
        think, ans = self._think_splitter.flush()
        if think:
            self._on_reasoning(think)
        if ans:
            self._append_answer(ans)
        if self._assistant_text.strip():
            msg = {"role": "assistant", "content": self._assistant_text}
            if self._regenerating and self._pending_variants:
                # 分支：旧回答 + 新回答组成变体组，默认激活最新一个
                variants = self._pending_variants + [self._assistant_text]
                msg["variants"] = variants
                msg["active"] = len(variants) - 1
                bubble = self._current_bubble
                if bubble is not None and hasattr(bubble, "set_variants"):
                    bubble.set_variants(variants, msg["active"])
            self.history.append(msg)
            self.sessions.append(msg)
            self.history = trim_history(
                self.history, int(self.cfg.data.get("history_limit", 20)))
            self.sessions.set_messages(list(self.history))
            # v8.0：从本轮对话启发式学习长期记忆，并让其即时生效（下一轮）
            last_user = next((message_text(m)
                              for m in reversed(self.history)
                              if m.get("role") == "user"), "")
            if self.memory.learn_from_conversation(last_user):
                self._rebuild_system_prompt()
            self.window.set_memory_count(self.memory.count())
        # 网关统计：成功请求（旁路记录，失败静默降级）
        self._record_gateway(True)
        self._regenerating = False
        self._pending_variants = []
        self.window.finish_message()
        self._stop_ui()

    def _record_gateway(self, ok, error=""):
        """把一次请求写入网关统计（tokens 按 CJK 感知估算）"""
        try:
            latency = int((time.time() - getattr(self, "_req_t0", 0) or 0) * 1000)
            tokens = messages_tokens(
                [{"role": "user", "content": self._assistant_text or ""}])
            GatewayStats.instance().record(
                self._req_provider, self._req_model, ok,
                latency, tokens, error)
        except Exception:                          # noqa: BLE001 - 旁路不打扰主链路
            pass

    def _on_variant_selected(self, idx):
        """切换回答变体：同步 history / 会话存储中的激活项"""
        if self.worker is not None and self.worker.isRunning():
            return
        for m in reversed(self.history):
            if m.get("role") != "assistant":
                continue
            variants = m.get("variants")
            if not variants:
                continue
            if 0 <= idx < len(variants) and m.get("active") != idx:
                m["active"] = idx
                m["content"] = variants[idx]
                self.sessions.set_messages(list(self.history))
            return

    def _on_failed(self, err):
        import html as _html
        from core import devlog
        devlog.error("request", "请求失败", error=str(err)[:200])
        self._record_gateway(False, str(err))
        self.window.fail_message(
            "%s<br><br>💡 可点击消息下方的「重新生成」重试；"
            "若持续失败，请点右上角 ⚙ 检查服务商 / API Key / 网络。"
            % _html.escape(str(err)))
        self._stop_ui()

    def _stop_ui(self):
        self.ball.set_state(BallState.IDLE)
        self.window.set_busy(False)
        self.worker = None
        self._current_bubble = None
        self._assistant_text = ""

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------
    def start_screenshot(self):
        if self.worker is not None and self.worker.isRunning():
            self.window.show_hint("正在生成回复，稍后再截图")
            return
        self.shots.start()

    # ------------------------------------------------------------------
    # MCP 工具接入（v7.3 补齐）：后台线程连接，主线程轮询收尾
    # ------------------------------------------------------------------
    def _connect_mcp_async(self):
        """在后台线程连接 MCP 服务器（子进程握手可能较慢，不能拖慢启动）"""
        import threading

        def work():
            report, n = {}, 0
            try:
                report = self.mcp.connect_all()
                n = self.mcp.register_tools()
            except Exception:                           # noqa: BLE001
                report, n = {}, 0
            self._mcp_state = {"done": True, "report": report, "tools": n}

        threading.Thread(target=work, daemon=True).start()
        self._mcp_poll = QTimer()
        self._mcp_poll.timeout.connect(self._poll_mcp)
        self._mcp_poll.start(400)

    def _poll_mcp(self):
        """主线程轮询：后台连接完成后给出提示并停止轮询"""
        st = getattr(self, "_mcp_state", None) or {}
        if not st.get("done"):
            return
        poll = getattr(self, "_mcp_poll", None)
        if poll is not None:
            poll.stop()
        n = int(st.get("tools") or 0)
        if n:
            self.window.show_hint("已接入 %d 个 MCP 工具" % n)
            print("[MCP] 已注册 %d 个工具" % n)
        for name, (ok, msg) in (st.get("report") or {}).items():
            if not ok:
                print("[MCP] 服务器「%s」连接失败：%s" % (name, msg))

    # ------------------------------------------------------------------
    # 「看屏幕」问答：一键抓全屏 + 预设问题（对标 Moonwalker / Jini）
    # ------------------------------------------------------------------
    def start_screen_qa(self, label=None):
        if self.worker is not None and self.worker.isRunning():
            self.window.show_hint("正在生成回复，稍后再看屏幕")
            return
        question = build_question(label) if label else default_question()
        self.shots.capture_screen(question)

    # ------------------------------------------------------------------
    # 智能体：技能 / 工具 / 插件市场
    # ------------------------------------------------------------------
    def _rebuild_system_prompt(self):
        """系统提示 = 基础人设 + 当前技能提示 + V8.0 长期记忆块"""
        prompt = self.skills.system_prompt_for()
        if self.memory.enabled:
            mem = self.memory.build_memory_block()
            if mem:
                prompt = prompt + "\n\n" + mem
        if self.history and self.history[0].get("role") == "system":
            self.history[0]["content"] = prompt
        else:
            self.history.insert(0, {"role": "system", "content": prompt})

    def on_skill_changed(self, skill_id):
        self.skills.set_current(skill_id)
        self._rebuild_system_prompt()
        s = self.skills.get(skill_id) or {}
        self.window.show_hint("已切换技能：%s %s"
                              % (s.get("icon", ""), s.get("name", "")))

    def open_market(self):
        from ui.market_dialog import MarketDialog
        if self._market_dialog is None:
            self._market_dialog = MarketDialog(self.market, self.cfg,
                                               self.window)
            self._market_dialog.changed.connect(self._on_market_changed)
            self._market_dialog.finished.connect(self._on_market_closed)
        self._market_dialog._load_cards()
        self._market_dialog.show()
        self._market_dialog.raise_()

    def _on_market_closed(self):
        self._market_dialog = None

    def _on_market_changed(self):
        """市场安装/开关后：刷新技能下拉、工具按钮与系统提示"""
        self.window.refresh_skills()
        self.window._refresh_tools_button()
        self._rebuild_system_prompt()

    # ------------------------------------------------------------------
    # 多会话
    # ------------------------------------------------------------------
    def _render_history(self):
        """把 history 渲染到消息区（启动恢复 / 切换会话）"""
        self.window.clear_messages()
        for m in self.history:
            role = m.get("role")
            if role == "user":
                self.window.add_user_message(message_text(m) or "（空）")
            elif role == "assistant" and m.get("content"):
                bubble = self.window.start_assistant_message()
                bubble.thinking.skip()
                bubble.append_content(m["content"])
                bubble.flush()
                variants = m.get("variants")
                if variants:
                    # 分支回答：渲染激活变体并显示 ①② 切换器
                    bubble.set_variants(variants, int(m.get("active") or 0))
                else:
                    bubble.actions.hide()
        self.window.set_session_title(self._session_title)

    def _save_current_session(self):
        self.sessions.set_messages(list(self.history))
        self._session_title = (self.sessions.current() or {}).get(
            "title") or self._session_title

    def open_sessions(self):
        from ui.session_dialog import SessionDialog
        if self._session_dialog is None:
            self._session_dialog = SessionDialog(self.sessions, self.cfg,
                                                 self.window)
            self._session_dialog.session_selected.connect(
                self._on_session_selected)
            self._session_dialog.export_requested.connect(
                self.export_conversation)
            self._session_dialog.finished.connect(
                self._on_session_dialog_closed)
        self._session_dialog._reload()
        self._session_dialog.show()
        self._session_dialog.raise_()

    def _on_session_dialog_closed(self):
        self._session_dialog = None

    def _on_session_selected(self, session_id):
        if session_id == self.sessions.current_id():
            return
        if self.worker is not None and self.worker.isRunning():
            self.window.show_hint("正在生成回复，稍后再切换会话")
            return
        self._save_current_session()
        if not self.sessions.set_current(session_id):
            return
        self._load_current_session()
        self._render_history()
        self.window.show_hint("已切换会话：%s" % self._session_title)

    # ------------------------------------------------------------------
    # 提示词库
    # ------------------------------------------------------------------
    def open_prompts(self):
        from ui.prompt_dialog import PromptDialog
        if self._prompt_dialog is None:
            self._prompt_dialog = PromptDialog(self.cfg, self.window)
            self._prompt_dialog.prompt_inserted.connect(
                self._on_prompt_inserted)
            self._prompt_dialog.finished.connect(
                self._on_prompt_dialog_closed)
        self._prompt_dialog.set_current_text(
            self.window.input.toPlainText())
        self._prompt_dialog._reload()
        self._prompt_dialog.show()
        self._prompt_dialog.raise_()

    def _on_prompt_dialog_closed(self):
        self._prompt_dialog = None

    def _on_prompt_inserted(self, content):
        self.window.insert_text(content)

    # ------------------------------------------------------------------
    # 资料库
    # ------------------------------------------------------------------
    def open_library(self):
        from ui.library_dialog import LibraryDialog
        if self._library_dialog is None:
            self._library_dialog = LibraryDialog(self.library, self.cfg,
                                                 self.window)
            self._library_dialog.finished.connect(
                self._on_library_closed)
        self._library_dialog._reload()
        self._library_dialog.show()
        self._library_dialog.raise_()

    def open_memory(self):
        """打开长期记忆管理对话框（查看 / 删除 / 开关）。"""
        from ui.memory_dialog import MemoryDialog
        dlg = MemoryDialog(self.memory, self.window)
        dlg.changed.connect(
            lambda: self.window.set_memory_count(self.memory.count()))
        dlg.exec_()

    def open_models(self):
        """打开模型库（阿里魔塔 GGUF 下载 / llama.cpp 本地服务）"""
        from ui.models_dialog import ModelsDialog
        if self._models_dialog is None:
            self._models_dialog = ModelsDialog(self.cfg, self.window)
            self._models_dialog.models_changed.connect(
                self._on_local_models_changed)
            self._models_dialog.finished.connect(
                self._on_models_dialog_closed)
        self._models_dialog.show()
        self._models_dialog.raise_()

    def open_rea(self):
        """V9.0：一键接入 REA 逆向工程（GitHub 爆火 MCP 逆向工具）。

        把 REA 的 MCP 预设并入设置，并打开设置页的 MCP 工具区供用户启用 / 连接。
        """
        from core.rea import ensure_rea_preset
        servers, existed = ensure_rea_preset(self.cfg.data.get("mcp_servers")
                                            or [])
        self.cfg.data["mcp_servers"] = servers
        self.cfg.save()
        self.open_settings()
        self.window.show_hint(
            "已%s REA 逆向工程预设，请在「MCP 工具」页启用并连接"
            % ("定位到" if existed else "添加"))

    def open_artifacts(self):
        """V9.0：产物预览（学习 Open WebUI / LobeChat 的 Artifacts 创新）。

        扫描最近一条 assistant 回复中的 ```html 代码块，落地临时文件后在浏览器打开。
        """
        import os
        import re
        import tempfile
        import webbrowser
        html = None
        for m in reversed(self.history):
            if m.get("role") != "assistant":
                continue
            html = extract_html_artifact(message_text(m))
            if html:
                break
        if not html:
            self.window.show_hint(
                "最近还没有可预览的 HTML 产物（回复里用 ```html 包裹即可）")
            return
        fd, path = tempfile.mkstemp(suffix=".html", prefix="starry_artifact_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)
        webbrowser.open("file://" + path)
        self.window.show_hint("已在浏览器打开产物预览（临时文件：%s）" % path)

    def _on_models_dialog_closed(self):
        # 关闭后刷新设置页的本地状态（若设置对话框仍打开）
        if self._settings is not None:
            self._settings._refresh_local_status()
        self._models_dialog = None

    def _on_local_models_changed(self):
        """模型库下载/删除后刷新「魔塔本地模型」下拉与缓存"""
        self._inject_local_gguf()
        self.models.reload_combo()

    def _inject_local_gguf(self):
        """把本地已下载 GGUF 写入 modelscope_local 的模型缓存"""
        from core import local_llm, models as model_reg
        ggufs = local_llm.list_local_gguf()
        names = [g["name"] for g in ggufs]
        if names:
            model_reg.cache_put(self.cfg, "modelscope_local", names)
        self._local_gguf_count = len(names)

    def _on_library_closed(self):
        self._library_dialog = None

    def _library_context(self, query):
        """资料库自动注入：按本轮问题检索相关片段（无资料 / 未开启返回空）。

        v13.3：同时记录来源引用清单，供「本轮引用来源」面板回显用户
        （借鉴 AnythingLLM 的 source citations，让回答可溯源）。
        """
        self._last_citations = []
        if not self.cfg.data.get("library_auto", True):
            return ""
        if not self.library.data.get("docs"):
            return ""
        try:
            ctx = self.library.context_for(query)
            if ctx:
                self._last_citations = self.library.citations_for(query)
            return ctx
        except Exception:  # noqa: BLE001  检索失败不阻塞对话
            return ""

    # ------------------------------------------------------------------
    # v13.3 · 全局搜索 / 来源引用（借鉴 Cherry Studio / AnythingLLM）
    # ------------------------------------------------------------------
    def open_global_search(self, query=""):
        """打开跨数据源全局搜索窗口。"""
        from ui.globalsearch_dialog import GlobalSearchDialog
        if self._global_search_dialog is None:
            self._global_search_dialog = GlobalSearchDialog(
                sessions=self.sessions, library=self.library,
                prompts=self.prompts, memory=self.memory,
                parent=self.window)
            self._global_search_dialog.open_requested.connect(
                self._on_global_search_open)
            self._global_search_dialog.finished.connect(
                lambda: setattr(self, "_global_search_dialog", None))
        if query:
            self._global_search_dialog.apply_query(query)
        else:
            self._global_search_dialog._reload()
        self._global_search_dialog.show()
        self._global_search_dialog.raise_()

    def _on_global_search_open(self, ref):
        """全局搜索结果跳转：会话 / 收藏切过去，其余打开对应功能页。"""
        ref = ref or {}
        kind = ref.get("type")
        if kind in ("session", "starred"):
            sid = ref.get("id") or ref.get("session_id")
            if not sid:
                return
            if sid == self.sessions.current_id():
                self.window.show_hint("已在目标会话")
                return
            self._save_current_session()
            if not self.sessions.set_current(sid):
                return
            self._load_current_session()
            self._render_history()
            self.window.show_hint("已跳转到：%s" % (ref.get("title") or "目标会话"))
        elif kind == "library":
            self.open_library()
            self.window.show_hint("来源资料：%s" % ref.get("doc", ""))
        elif kind == "prompt":
            self.open_prompts()
        elif kind == "memory":
            self.open_memory()

    def open_citations(self):
        """查看本轮回答引用了哪些资料（AnythingLLM 式可溯源来源清单）。"""
        from PyQt5.QtWidgets import QMessageBox
        from core.library import format_citations
        text = format_citations(self._last_citations, with_excerpt=True)
        QMessageBox.information(self.window, "📎 本轮引用来源", text)

    # ------------------------------------------------------------------
    # v13.4 · 应用内 API Key 申请引导
    # ------------------------------------------------------------------
    def open_apikey_guide(self, provider=None):
        """打开「申请 API Key」过程说明（分服务商，纯本地内容不联网）。"""
        from ui.apikey_guide_dialog import ApiKeyGuideDialog
        if self._apikey_guide is None:
            self._apikey_guide = ApiKeyGuideDialog(
                self.cfg, self.window, provider=provider)
            self._apikey_guide.open_settings_requested.connect(
                self._focus_settings_key)
            self._apikey_guide.finished.connect(
                lambda: setattr(self, "_apikey_guide", None))
        self._apikey_guide.show()
        self._apikey_guide.raise_()

    def _focus_settings_key(self):
        """引导里点「去设置填写」：把已打开的设置窗口提到前台。"""
        if self._settings is not None:
            self._settings.raise_()
            self._settings.activateWindow()
        else:
            self.window.show_hint("请在「设置 → 服务商」中填写 API Key")

    # ------------------------------------------------------------------
    # v13.4 · 应用缓存清理
    # ------------------------------------------------------------------
    def open_cache_clean(self):
        """打开缓存清理窗口（扫描只读，清理需二次确认且先备份）。"""
        from ui.cache_dialog import CacheDialog
        if self._cache_dialog is None:
            self._cache_dialog = CacheDialog(self.cfg, self.window)
            self._cache_dialog.finished.connect(
                lambda: setattr(self, "_cache_dialog", None))
        self._cache_dialog.show()
        self._cache_dialog.raise_()

    # ------------------------------------------------------------------
    # v13.5 · 开发者调试模式 / 自动缩放 / 退出自动清理
    # ------------------------------------------------------------------
    def open_devtools(self):
        """打开开发者调试面板（分级日志实时输出）。"""
        from ui.devtools_dialog import DevToolsDialog
        if self._devtools_dialog is None:
            self._devtools_dialog = DevToolsDialog(self.cfg, self.window)
            self._devtools_dialog.finished.connect(
                lambda: setattr(self, "_devtools_dialog", None))
        self._devtools_dialog.show()
        self._devtools_dialog.raise_()

    def _screen_recommendation(self):
        from PyQt5.QtWidgets import QApplication
        from core import uiscale
        desk = QApplication.desktop()
        area = desk.availableGeometry()
        return uiscale.recommend(
            area.width(), area.height(), desk.logicalDpiX() or 96,
            int(self.cfg.appearance.get("font_size", 14)))

    def apply_auto_scale(self, silent=False):
        """按屏幕自动适配缩放档 + 窗口尺寸（设置页「立即按屏幕适配」）。"""
        from core import uiscale, devlog
        try:
            rec = self._screen_recommendation()
        except Exception as e:                          # noqa: BLE001
            devlog.warn("uiscale", "自动缩放失败", error=str(e)[:120])
            if not silent:
                self.window.show_hint("自动缩放失败：%s" % str(e)[:60])
            return None
        uiscale.apply_to_config(self.cfg, rec, save=False)
        try:
            self.window.resize(*rec["window_size"])
        except Exception:                               # noqa: BLE001
            pass
        self._apply_settings()        # 复用条件化分发：主题 / 字号 / 持久化
        if self._settings is not None:
            try:
                idx = self._settings.scale_combo.findText(rec["scale_label"])
                if idx >= 0:
                    self._settings.scale_combo.setCurrentIndex(idx)
                self._settings._refresh_banner()
                self._settings._refresh_auto_scale_hint()
            except Exception:                           # noqa: BLE001
                pass
        devlog.info("uiscale", "自动缩放已应用",
                    scale=rec["scale_label"], window="%sx%s" % tuple(rec["window_size"]),
                    reason=rec["reason"])
        if not silent:
            self.window.show_hint("🔎 已按屏幕适配：%s（窗口 %s×%s）" % (
                rec["scale_label"], rec["window_size"][0], rec["window_size"][1]))
        return rec

    def _auto_scale_on_startup(self):
        """启动时自动缩放（放进首屏后的延迟初始化，不拖慢启动）。"""
        if not bool(self.cfg.data.get("auto_ui_scale", False)):
            return
        from core import uiscale, devlog
        try:
            rec = self._screen_recommendation()
            uiscale.apply_to_config(self.cfg, rec, save=True)
            self.window.resize(*rec["window_size"])
            self.window.apply_theme()
            devlog.info("uiscale", "启动自动缩放",
                        scale=rec["scale_label"], reason=rec["reason"])
        except Exception as e:                          # noqa: BLE001
            devlog.warn("uiscale", "启动自动缩放失败", error=str(e)[:120])

    def _auto_clean_tmp_on_exit(self):
        """退出时自动清理临时残留（可选开关，仍走备份/小批量安全链路）。"""
        if not bool(self.cfg.data.get("auto_clean_tmp", False)):
            return
        from core import cacheclean as cc
        from core import devlog
        try:
            items = [i for i in cc.scan(cfg=self.cfg)
                     if i["id"] in ("tmp", "logs")]
            for i in items:
                i["selected"] = True
            rep = cc.clean(items, cfg=self.cfg, backup=True)
            devlog.info("cache", "退出自动清理临时残留",
                        cleaned=len(rep["cleaned"]), freed=rep["freed_bytes"])
        except Exception as e:                          # noqa: BLE001
            devlog.warn("cache", "退出自动清理失败", error=str(e)[:120])

    # ------------------------------------------------------------------
    # v13.4 · 大模型能力：能力矩阵 / 自动路由 / 失败回退
    # ------------------------------------------------------------------
    def _model_names_for_route(self):
        combo = getattr(self.window, "model_combo", None)
        names = []
        if combo is not None:
            names = [combo.itemText(i).split("（")[0].strip()
                     for i in range(combo.count())]
        if not names:
            from core.config import PROVIDERS
            names = list((PROVIDERS.get(self.cfg.provider) or {}).get("models") or [])
        return [n for n in names if n]

    def _route_request(self):
        from core import modelcap
        last_user = next((m for m in reversed(self.history or [])
                          if m.get("role") == "user"), None)
        query = message_text(last_user) if last_user else ""
        try:
            need_tools = self.mcp.tool_count() > 0
        except Exception:                               # noqa: BLE001
            need_tools = False
        req = modelcap.describe_request(
            query=query, messages=self.history,
            has_images=bool(getattr(self, "_pending_images", None)),
            need_tools=need_tools,
            deep_thinking=bool(self.cfg.data.get("deep_thinking")),
        )
        return modelcap.route_model(
            self._model_names_for_route(), req,
            provider=self.cfg.provider, current=self.cfg.model())

    def _apply_auto_route(self, silent=False):
        route = self._route_request()
        cur = self.cfg.model()
        if not route.get("ok") or not route.get("model") or route["model"] == cur:
            return route
        self.cfg.set_model(route["model"])
        self.window.show_hint("🧠 智能路由：%s" % route["model"])
        return route

    def open_model_route(self):
        """手动「智能选模型」：展示推荐与理由，确认后切换。"""
        from PyQt5.QtWidgets import QMessageBox
        from core import modelcap
        route = self._route_request()
        text = modelcap.format_route(route)
        if not route.get("ok") or route["model"] == self.cfg.model():
            QMessageBox.information(self.window, "🧠 智能选模型", text)
            return
        box = QMessageBox(self.window)
        box.setWindowTitle("🧠 智能选模型")
        box.setIcon(QMessageBox.Information)
        box.setText(text)
        box.setInformativeText("是否把当前模型切换为推荐模型？")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec_() == QMessageBox.Yes:
            self.cfg.set_model(route["model"])
            try:
                self.models.reload_combo()
            except Exception:                           # noqa: BLE001
                pass
            self.window.show_hint("🧠 已切换到：%s" % route["model"])

    def toggle_auto_route(self):
        """开关「每轮自动按请求特征选模型」（默认关闭）。"""
        on = not bool(self.cfg.data.get("auto_route_model", False))
        self.cfg.data["auto_route_model"] = on
        self.cfg.save()
        self.window.show_hint("🧠 智能模型路由已%s" % ("开启" if on else "关闭"))

    def open_model_capabilities(self):
        """查看当前服务商的模型能力矩阵。"""
        from PyQt5.QtWidgets import QMessageBox
        from core.modelcap import capability_table, format_capabilities
        caps = capability_table(self._model_names_for_route(), self.cfg.provider)
        QMessageBox.information(self.window, "🧠 模型能力矩阵",
                                format_capabilities(caps))

    # ------------------------------------------------------------------
    # 自动化任务
    # ------------------------------------------------------------------
    AUTOMATION_SESSION = "⚙ 自动化"

    def _init_automation_timer(self):
        """周期检查到点任务（30 秒粒度）"""
        self._automation_timer = QTimer(self)
        self._automation_timer.timeout.connect(self._check_automation)
        self._automation_timer.start(30000)
        # 启动后尽快检查一次（补行关闭期间错过的任务）
        QTimer.singleShot(2500, self._check_automation)

    def open_automation(self):
        from ui.automation_dialog import AutomationDialog
        if self._automation_dialog is None:
            self._automation_dialog = AutomationDialog(
                self.automation, self.skills, self.cfg, self.window)
            self._automation_dialog.run_now_requested.connect(
                self._on_automation_run_now)
            self._automation_dialog.finished.connect(
                self._on_automation_closed)
        self._automation_dialog._reload()
        self._automation_dialog.show()
        self._automation_dialog.raise_()

    def _on_automation_closed(self):
        self._automation_dialog = None

    def _on_automation_run_now(self, task_id):
        task = self.automation.get(task_id)
        if task is not None:
            self._run_automation_task(task, manual=True)

    def _check_automation(self):
        for task in self.automation.due():
            self._run_automation_task(task)

    def _run_automation_task(self, task, manual=False):
        """在后台执行一次自动化任务（结果写入专用会话）"""
        task_id = task.get("id")
        if task_id in self._automation_running:
            return
        if not self.cfg.is_ready():
            if manual:
                self.window.show_hint("尚未配置 API，无法运行自动化任务")
            return
        self._automation_running.add(task_id)
        if not manual:
            self.automation.mark_run(task_id)

        prompt = task.get("prompt", "")
        skill = task.get("skill") or ""
        system = self.skills.system_prompt_for(skill or None)
        client = self._effective_client()
        history = [{"role": "system", "content": system},
                   {"role": "user", "content": prompt}]
        worker = ChatWorker(client, history)
        buffer = {"text": ""}

        def _content(text):
            buffer["text"] += text

        def _done():
            self._automation_running.discard(task_id)
            self._on_automation_done(task, buffer["text"])

        def _failed(err):
            self._automation_running.discard(task_id)
            self._on_automation_done(task, "", error=str(err))

        worker.content.connect(_content)
        worker.finished.connect(_done)
        worker.failed.connect(_failed)
        worker.start()
        self.window.show_hint("⏰ 自动化任务「%s」开始执行" % task.get("name"),
                              4000)

    def _automation_session_id(self):
        """找到 / 创建「⚙ 自动化」专用会话（不抢占用户当前会话）"""
        for info in self.sessions.list():
            if info.get("title") == self.AUTOMATION_SESSION:
                return info["id"]
        prev = self.sessions.current_id()
        session = self.sessions.create(self.AUTOMATION_SESSION)
        if prev:
            self.sessions.set_current(prev)
        return session["id"]

    def _on_automation_done(self, task, text, error=""):
        name = task.get("name", "自动化任务")
        if error:
            msg = "⏰ 自动化任务「%s」失败：%s" % (name, error)
            self.window.show_hint(msg, 6000)
            if self.tray is not None:
                self.tray.showMessage("星语 · 自动化", msg)
            return
        if text.strip():
            sid = self._automation_session_id()
            self.sessions.append({"role": "user",
                                  "content": "【自动化】%s" % task.get("prompt", "")},
                                 session_id=sid)
            self.sessions.append({"role": "assistant", "content": text},
                                 session_id=sid)
        msg = "⏰ 自动化任务「%s」已完成，结果已写入「%s」会话" % (
            name, self.AUTOMATION_SESSION)
        self.window.show_hint(msg, 6000)
        if self.tray is not None:
            self.tray.showMessage("星语 · 自动化", msg)
        if self._automation_dialog is not None:
            self._automation_dialog._reload()

    # ------------------------------------------------------------------
    # 专家会诊（多智能体协作）
    # ------------------------------------------------------------------
    def open_panel(self):
        from ui.panel_dialog import ExpertPanelDialog
        if self._panel_dialog is None:
            self._panel_dialog = ExpertPanelDialog(
                self.skills, self._make_client, self.cfg, self.window)
            self._panel_dialog.finished.connect(self._on_panel_closed)
        self._panel_dialog.show()
        self._panel_dialog.raise_()

    def _on_panel_closed(self):
        self._panel_dialog = None

    # ------------------------------------------------------------------
    # Agent Mail（邮件智能体）
    # ------------------------------------------------------------------
    def open_mail(self):
        from ui.mail_dialog import MailDialog
        if self._mail_dialog is None:
            self._mail_dialog = MailDialog(
                self.cfg, self._make_client, self.window)
            self._mail_dialog.finished.connect(self._on_mail_closed)
        self._mail_dialog.show()
        self._mail_dialog.raise_()

    def _on_mail_closed(self):
        self._mail_dialog = None

    def _make_client(self):
        """为会诊专家创建独立客户端（每次调用一个新实例）"""
        return self._effective_client()

    # ------------------------------------------------------------------
    # 关于 / 欢迎页示例
    # ------------------------------------------------------------------
    def open_about(self):
        from ui.about_dialog import AboutDialog
        if self._about_dialog is None:
            self._about_dialog = AboutDialog(self.cfg, self.stats,
                                             self.hotkey, self.window)
            self._about_dialog.finished.connect(
                self._on_about_closed)
        if self._settings is not None and self._settings.isVisible():
            # 设置对话框是模态的：关于以模态方式叠在其上，避免被阻断输入
            self._about_dialog.setModal(True)
            self._about_dialog.exec_()
        else:
            self._about_dialog.setModal(False)
            self._about_dialog.show()
            self._about_dialog.raise_()

    def _on_about_closed(self):
        self._about_dialog = None

    def _on_example_requested(self, text):
        """欢迎页示例问题：填入输入框并直接发送"""
        if self.worker is not None and self.worker.isRunning():
            self.window.show_hint("正在生成回复，稍后再试")
            return
        self.window.insert_text(text)
        self.on_send(text)

    # ------------------------------------------------------------------
    # 导出对话
    # ------------------------------------------------------------------
    def export_conversation(self):
        import datetime
        base = "AI对话_%s" % datetime.datetime.now().strftime("%Y%m%d_%H%M")
        filters = ("Markdown 文件 (*.md);;JSON 文件 (*.json);;"
                   "纯文本 (*.txt);;HTML 网页 (*.html)")
        if "pdf" in available_formats():      # V11.2：环境支持时追加 PDF
            filters += ";;PDF 文件 (*.pdf)"
        path, selected = QFileDialog.getSaveFileName(
            self.window, "导出对话", base, filters)
        if not path:
            return
        # 依据所选过滤器决定格式，并补全扩展名（V11.1 多格式导出）
        if "json" in selected:
            fmt, ext = "json", ".json"
        elif "txt" in selected:
            fmt, ext = "text", ".txt"
        elif "html" in selected:
            fmt, ext = "html", ".html"
        elif "pdf" in selected:
            fmt, ext = "pdf", ".pdf"
        else:
            fmt, ext = "markdown", ".md"
        if not path.lower().endswith(ext):
            path += ext
        title = self._session_title or "AI 对话记录"
        model = self.cfg.model()
        provider_name = self.cfg.provider_info().get("name", self.cfg.provider)
        try:
            if fmt == "pdf":
                data = conversation_to_pdf(
                    self.history, title=title, model=model,
                    provider_name=provider_name)
                with open(path, "wb") as f:
                    f.write(data)
            elif fmt == "json":
                content = conversation_to_json(
                    self.history, title=title, model=model,
                    provider_name=provider_name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            elif fmt == "text":
                content = conversation_to_text(
                    self.history, title=title, model=model,
                    provider_name=provider_name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            elif fmt == "html":
                content = conversation_to_html(
                    self.history, title=title, model=model,
                    provider_name=provider_name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            else:
                content = conversation_to_markdown(
                    self.history, title=title, model=model,
                    provider_name=provider_name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            self.window.show_hint("对话已导出：%s" % path, 6000)
        except Exception as e:  # noqa: BLE001
            self.window.show_hint("导出失败：%s" % e, 6000)

    def delete_last_message(self):
        """V11.2：删除当前会话最后一条消息（撤回刚发出/收到的内容）。

        同步会话存储并重新渲染消息区；保留系统提示不被删。
        """
        if self.worker is not None and self.worker.isRunning():
            self.window.show_hint("正在生成回复，稍后再删除")
            return
        if not self.history or len(self.history) <= 1:
            self.window.show_hint("没有可删除的消息")
            return
        removed = self.history.pop()
        sid = self.sessions.current_id()
        msgs = self.sessions.messages(sid)
        if msgs:
            self.sessions.delete_message(sid, len(msgs) - 1)
        self._session_title = (self.sessions.current() or {}).get(
            "title") or self._session_title
        self._render_history()
        self.window.show_hint(
            "已删除最后一条消息（%s）" % removed.get("role", "未知"))

    # ------------------------------------------------------------------
    # V11.3：消息收藏 / AI 总结 / 批量导出
    # ------------------------------------------------------------------
    def toggle_star_last(self):
        """收藏 / 取消收藏当前会话最后一条 AI 回复。"""
        if not self.history:
            self.window.show_hint("没有可收藏的消息")
            return
        idx = None
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i].get("role") == "assistant":
                idx = i
                break
        if idx is None:
            self.window.show_hint("当前还没有 AI 回复可收藏")
            return
        self._save_current_session()      # 确保 history 已落库、索引一致
        sid = self.sessions.current_id()
        now = self.sessions.toggle_star(sid, idx)
        self.window.show_hint("已收藏最后一条回复 ⭐"
                               if now else "已取消收藏该回复")

    def open_starred(self):
        """打开收藏夹：列出全部已收藏消息，点击可跳转到对应会话。"""
        from ui.starred_dialog import StarredDialog
        if self._starred_dialog is None:
            self._starred_dialog = StarredDialog(
                self.sessions, self.window)
            self._starred_dialog.jump_requested.connect(
                self._on_starred_jump)
            self._starred_dialog.finished.connect(
                lambda: setattr(self, "_starred_dialog", None))
        self._starred_dialog._reload()
        self._starred_dialog.show()
        self._starred_dialog.raise_()

    def _on_starred_jump(self, session_id):
        self._starred_dialog = None
        if session_id == self.sessions.current_id():
            self.window.show_hint("已在目标会话")
            return
        self._save_current_session()
        if not self.sessions.set_current(session_id):
            return
        self._load_current_session()
        self._render_history()
        self.window.show_hint(
            "已跳转到收藏所在的会话：%s" % self._session_title)

    def export_all_sessions(self):
        """V11.3：把全部会话合并导出为 Markdown/JSON/文本/HTML/ZIP。"""
        import datetime
        base = "星语Starry_全部会话_%s" % \
            datetime.datetime.now().strftime("%Y%m%d_%H%M")
        filters = ("Markdown 文件 (*.md);;JSON 文件 (*.json);;"
                   "纯文本 (*.txt);;HTML 网页 (*.html);;ZIP 压缩包 (*.zip)")
        path, selected = QFileDialog.getSaveFileName(
            self.window, "批量导出全部会话", base, filters)
        if not path:
            return
        if "zip" in selected:
            fmt, ext = "zip", ".zip"
        elif "json" in selected:
            fmt, ext = "json", ".json"
        elif "txt" in selected:
            fmt, ext = "text", ".txt"
        elif "html" in selected:
            fmt, ext = "html", ".html"
        else:
            fmt, ext = "markdown", ".md"
        if not path.lower().endswith(ext):
            path += ext
        try:
            content, _ext = export_all_sessions(
                self.sessions, fmt=fmt, title="星语 Starry · 全部会话")
            if fmt == "zip":
                with open(path, "wb") as f:
                    f.write(content)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            self.window.show_hint("全部会话已导出：%s" % path, 6000)
        except Exception as e:  # noqa: BLE001
            self.window.show_hint("导出失败：%s" % e, 6000)

    def summarize_current_session(self):
        """V11.3：调用模型总结当前会话，要点缓存到会话元数据。"""
        if self.worker is not None and self.worker.isRunning():
            self.window.show_hint("正在生成回复，稍后再总结")
            return
        msgs = list(self.history)
        if not any(m.get("role") == "assistant" for m in msgs):
            self.window.show_hint("当前会话内容太少，无法总结")
            return
        system, user = build_summary_prompt(msgs)
        try:
            from core.cli import build_client  # 懒加载：把 core.cli 推到摘要时才导入
            client = build_client(self.cfg)
        except Exception as e:  # noqa: BLE001
            self.window.show_hint("配置错误：%s" % e, 6000)
            return
        self.window.show_hint("正在生成会话摘要…（可能需要十几秒）")
        self._summary_thread(client, system, user)

    def _summary_thread(self, client, system, user):
        """在后台线程流式生成摘要，完成后弹窗展示并缓存。"""
        from PyQt5.QtCore import QThread, pyqtSignal

        class _SumWorker(QThread):
            done = pyqtSignal(str)
            failed = pyqtSignal(str)

            def __init__(self, client, system, user):
                super().__init__()
                self._client = client
                self._system = system
                self._user = user

            def run(self):
                buf = []
                try:
                    for kind, text in self._client.chat_stream(
                            [{"role": "system", "content": self._system},
                             {"role": "user", "content": self._user}]):
                        if kind == "content":
                            buf.append(text)
                except Exception as e:  # noqa: BLE001
                    self.failed.emit("生成摘要失败：%s" % e)
                    return
                self.done.emit("".join(buf).strip())

        w = _SumWorker(client, system, user)
        w.done.connect(self._on_summary_done)
        w.failed.connect(lambda m: self.window.show_hint(m, 6000))
        w.start()

    def _on_summary_done(self, text):
        sid = self.sessions.current_id()
        self.sessions.set_summary(sid, text)
        from PyQt5.QtWidgets import QMessageBox
        box = QMessageBox(self.window)
        box.setWindowTitle("会话摘要 · 已缓存")
        box.setText(text or "（摘要为空）")
        box.setStandardButtons(QMessageBox.Ok)
        box.setMinimumWidth(420)
        box.exec_()

    # ------------------------------------------------------------------
    # V11.4：消息引用（Quote）/ 分支对话（Branch）
    #   纯逻辑在 core.sessions，UI 仅做选择 + 调用，桌面/安卓同源
    # ------------------------------------------------------------------
    def _can_send_now(self):
        if self.worker is not None and self.worker.isRunning():
            self.window.show_hint("正在生成回复，稍后再操作")
            return False
        return True

    def open_quote_picker(self):
        """弹出消息选择器（引用模式），选中后发送带引用的追问。"""
        if not self._can_send_now():
            return
        from ui.message_picker_dialog import MessagePickerDialog
        # 先落库，确保 self.history 与 sessions.messages 索引一致
        # （启动时可能补了 system 提示但未写回，会造成下标偏移）
        self._save_current_session()
        dlg = MessagePickerDialog(self.sessions, mode="quote",
                                  parent=self.window)
        self._message_picker = dlg
        dlg.picked.connect(self._on_quote_picked)
        dlg.finished.connect(
            lambda: setattr(self, "_message_picker", None))
        dlg._reload()
        dlg.show()
        dlg.raise_()

    def _on_quote_picked(self, index, question):
        if not self._can_send_now():
            return
        sid = self.sessions.current_id()
        quote = self.sessions.quote_block(sid, index)
        if not quote:
            self.window.show_hint("该消息不可引用（系统提示或空内容）")
            return
        # 复用既有发送链路：引用块 + 问题作为一条 user 消息
        self.on_send(build_quoted_prompt(quote, question))
        self.window.show_hint("已引用 #%d 发送消息" % index)

    def quote_last_reply(self):
        """快速引用最后一条 AI 回复并追问。"""
        if not self._can_send_now():
            return
        from PyQt5.QtWidgets import QInputDialog
        idx = None
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i].get("role") == "assistant":
                idx = i
                break
        if idx is None:
            self.window.show_hint("当前还没有 AI 回复可引用")
            return
        question, ok = QInputDialog.getText(
            self.window, "↩️ 引用最后回复", "针对这条回复，你想追问什么？")
        if not ok:
            return
        self._save_current_session()
        sid = self.sessions.current_id()
        quote = self.sessions.quote_block(sid, idx)
        if not quote:
            self.window.show_hint("该消息不可引用")
            return
        self.on_send(build_quoted_prompt(quote, question))
        self.window.show_hint("已引用最后一条回复并发送 ↩️")

    def open_branch_picker(self):
        """弹出消息选择器（分支模式），选定点创建新分支会话。"""
        if not self._can_send_now():
            return
        from ui.message_picker_dialog import MessagePickerDialog
        self._save_current_session()          # 建立一致的索引基线
        dlg = MessagePickerDialog(self.sessions, mode="branch",
                                  parent=self.window)
        self._message_picker = dlg
        dlg.picked.connect(self._on_branch_picked)
        dlg.finished.connect(
            lambda: setattr(self, "_message_picker", None))
        dlg._reload()
        dlg.show()
        dlg.raise_()

    def _on_branch_picked(self, index, _extra):
        sid = self.sessions.current_id()
        new = self.sessions.branch_from(sid, index)
        if new is None:
            self.window.show_hint("分支创建失败（消息索引无效）")
            return
        # branch_from 已把新会话置为 current，直接重载渲染
        self._load_current_session()
        self._render_history()
        self.window.show_hint("已从 #%d 处创建分支会话：%s"
                              % (index, new["title"]))

    def open_branches(self):
        """列出当前会话派生的分支并跳转。"""
        from PyQt5.QtWidgets import QInputDialog, QMessageBox
        sid = self.sessions.current_id()
        items = self.sessions.list_branches(sid)
        if not items:
            QMessageBox.information(
                self.window, "🌱 分支列表",
                "当前会话还没有派生分支。\n"
                "在命令面板执行「🌿 分支对话」，可从某条消息处复制出新会话。")
            return
        titles = ["%s（#%d）" % (it["title"], it["index"]) for it in items]
        choice, ok = QInputDialog.getItem(
            self.window, "🌱 分支列表", "选择一个分支跳转：",
            titles, 0, False)
        if not ok or not choice or choice not in titles:
            return
        target = items[titles.index(choice)]
        if target["id"] == sid:
            return
        self._save_current_session()
        if self.sessions.set_current(target["id"]):
            self._load_current_session()
            self._render_history()
            self.window.show_hint("已跳转分支：%s" % target["title"])

    # ------------------------------------------------------------------
    # V11.5：对话洞察（统计 / 分支对比 / 会话合并）
    #   纯逻辑在 core.insights，UI 仅做选择 + 展示，桌面/安卓同源
    # ------------------------------------------------------------------
    def _pick_other_session(self, title, prompt):
        """从会话列表里选一个「非当前」会话，返回 (session_id, title)。"""
        from PyQt5.QtWidgets import QInputDialog, QMessageBox
        sid = self.sessions.current_id()
        items = [it for it in self.sessions.list() if it["id"] != sid]
        if not items:
            QMessageBox.information(
                self.window, title,
                "当前只有一个会话。\n先新建或切换会话后，再进行对比 / 合并。")
            return None
        titles = ["%s（%d 条）" % (it["title"], it["count"]) for it in items]
        choice, ok = QInputDialog.getItem(
            self.window, title, prompt, titles, 0, False)
        if not ok or choice not in titles:
            return None
        target = items[titles.index(choice)]
        return target["id"], target["title"]

    def open_insight(self):
        """📊 当前会话 + 全局统计面板。"""
        from ui.insight_dialog import InsightDialog
        self._save_current_session()
        sid = self.sessions.current_id()
        cur = self.sessions.get(sid) or {}
        stats = session_stats(cur)
        overview = overview_stats(self.sessions.data.get("sessions") or [])
        InsightDialog(format_stats_markdown(stats, overview),
                      "📊 对话统计洞察", self.window).exec_()

    def open_diff_picker(self):
        """🔀 选一个会话与当前会话做分支对比。"""
        from ui.insight_dialog import InsightDialog
        self._save_current_session()
        picked = self._pick_other_session(
            "🔀 分支对比", "选择与当前会话对比的另一个会话：")
        if picked is None:
            return
        other_id, _ = picked
        sid = self.sessions.current_id()
        diff = diff_sessions(self.sessions.get(sid) or {},
                             self.sessions.get(other_id) or {})
        InsightDialog(format_diff_markdown(diff),
                      "🔀 会话对比结果", self.window).exec_()

    def open_merge_picker(self):
        """🧬 把另一个会话的消息合并进当前会话。"""
        from PyQt5.QtWidgets import QMessageBox
        if not self._can_send_now():
            return
        self._save_current_session()
        picked = self._pick_other_session(
            "🧬 会话合并", "选择要合并进当前会话的来源会话：")
        if picked is None:
            return
        other_id, other_title = picked
        sid = self.sessions.current_id()
        confirm = QMessageBox.question(
            self.window, "🧬 确认合并",
            "将「%s」的消息合并进当前会话？\n"
            "共同前缀会自动去重，来源会话本身不会被删除。" % other_title,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        ok, report = self.sessions.merge_into(sid, other_id)
        if not ok:
            self.window.show_hint("合并失败（会话无效）")
            return
        self._load_current_session()
        self._render_history()
        self.window.show_hint(
            "已合并 %d 条消息（跳过重复 %d 条，共同前缀 %d 条）"
            % (report.get("added", 0), report.get("skipped", 0),
               report.get("common_prefix", 0)))

    # ------------------------------------------------------------------
    # 全局热键
    # ------------------------------------------------------------------
    def _init_hotkey(self):
        self._hotkey_triggered.connect(self._on_hotkey)
        ok, msg = self.hotkey.start()
        self._hotkey_msg = msg
        if not ok:
            # 优雅降级：仅记录，不打扰用户
            self._hotkey_msg = msg
        # v7.2 划词提问热键：失败同样静默降级（命令面板/托盘仍可召唤）
        self._quick_hotkey_triggered.connect(self._on_quick_hotkey)
        self.quick_hotkey.start()
        # 待机漫游：读取上一次的选择
        if self.cfg.data.get("roam"):
            self.ball.set_roam(True)

    def _emit_hotkey(self):
        """pynput 监听线程回调：发信号切回 UI 线程"""
        self._hotkey_triggered.emit()

    def _emit_quick_hotkey(self):
        self._quick_hotkey_triggered.emit()

    def _on_quick_hotkey(self):
        """划词热键：召唤迷你提问窗（读剪贴板/选区）"""
        self.open_quick_ask()

    def open_quick_ask(self):
        """v7.2 划词提问：选中/复制的文字 + 一个动作 → 一句好提示词"""
        if self._quick_win is None:
            from ui.quick_ask import QuickAskWindow
            self._quick_win = QuickAskWindow(self.cfg, None)
            self._quick_win.submitted.connect(self._on_quick_submit)
        self._quick_win.set_snippet(self._read_selection())
        self._quick_win.popup()

    @staticmethod
    def _read_selection():
        """读取当前选区（X11/Linux 支持鼠标选区；其余平台读剪贴板）"""
        try:
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtGui import QGuiApplication
            cb = QApplication.clipboard() or QGuiApplication.clipboard()
            text = ""
            try:
                from PyQt5.QtCore import QClipboard
                # X11 的「鼠标选中」优先（不破坏用户自己的剪贴板内容）
                text = cb.text(QClipboard.Selection)
            except Exception:                          # noqa: BLE001
                text = ""
            if not text:
                text = cb.text()
            return text or ""
        except Exception:                              # noqa: BLE001
            return ""

    def _on_quick_submit(self, prompt):
        """迷你窗提交 → 主窗发送（并把主窗拉到前台）"""
        if self._quick_win is not None:
            self._quick_win.close()
        try:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
        except Exception:                              # noqa: BLE001
            pass
        self.on_send(prompt)

    def toggle_roam(self):
        """v7.2 悬浮球待机漫游开关（含持久化）"""
        on = not self.ball.roam()
        self.ball.set_roam(on)
        self.cfg.data["roam"] = bool(on)
        try:
            self.cfg.save()
        except Exception:                              # noqa: BLE001
            pass
        self.window.show_hint(
            "🚶 待机漫游已开启：闲置时伙伴会慢慢溜达" if on
            else "🛑 待机漫游已关闭", 3000)
        return on

    def _on_hotkey(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.toggle_window()

    def _restart_hotkey(self):
        hotkey = self.cfg.data.get("hotkey") or DEFAULT_HOTKEY
        ok, msg = self.hotkey.set_hotkey(hotkey)
        if ok and not self.hotkey.active:
            self.hotkey.start()
        self.window.show_hint(msg, 5000)
        return ok, msg

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------
    def open_settings(self):
        if self._settings is None:
            self._settings = SettingsDialog(self.cfg, hotkey=self.hotkey)
            self._settings.onboarding_requested.connect(
                self._on_onboarding_requested)
            self._settings.about_requested.connect(self.open_about)
            self._settings.models_library_requested.connect(self.open_models)
            self._settings.web_login_requested.connect(self.open_web_login)
            self._settings.web_switch_requested.connect(self._switch_to_web)
            self._settings.gateway_requested.connect(self.open_gateway)
            self._settings.apikey_guide_requested.connect(
                self.open_apikey_guide)
            self._settings.cache_clean_requested.connect(self.open_cache_clean)
            self._settings.devtools_requested.connect(self.open_devtools)
            self._settings.auto_scale_requested.connect(self.apply_auto_scale)
        if self._settings.exec_() == SettingsDialog.Accepted:
            self._apply_settings()

    def _refresh_open_dialogs_theme(self, theme, eff_fs):
        """v13.5 控制逻辑优化：统一把主题/字号同步到所有已打开窗口。

        原先每段设置保存都要写十几行 ``if self._xxx_dialog is not None``，
        新增窗口还容易漏。这里集中登记 + 逐个 try/except 降级：
        支持 ``apply_theme(name, fs)`` 与 ``apply_theme(theme_dict)`` 两种签名，
        没有该方法的窗口静默跳过，绝不让一次外观刷新拖垮设置保存。
        """
        from ui.theme import get_theme
        td = get_theme(theme)
        two_arg = (self._settings, self._market_dialog, self._library_dialog,
                   self._automation_dialog, self._panel_dialog,
                   self._mail_dialog, self._about_dialog,
                   self._models_dialog, self._session_dialog,
                   self._prompt_dialog, self._starred_dialog)
        for dlg in two_arg:
            if dlg is None:
                continue
            try:
                dlg.apply_theme(theme, eff_fs)
            except TypeError:
                try:
                    dlg.apply_theme(td)
                except Exception:                       # noqa: BLE001
                    pass
            except Exception:                           # noqa: BLE001
                pass
        for dlg in (self._palette, self._gateway_dialog,
                    self._global_search_dialog, self._cache_dialog,
                    self._apikey_guide, self._devtools_dialog):
            if dlg is None:
                continue
            try:
                dlg.apply_theme(td)
            except Exception:                           # noqa: BLE001
                pass

    def _apply_settings(self):
        """应用设置变更（v13.5 优化：按变更项条件化分发）。

        首次调用等价于旧版全量应用；之后只在对应字段真的变化时才刷新对应
        子系统，避免「改一个热键却重建所有窗口 / 重拉模型」的无谓开销。
        所有变更写入分级日志，便于在开发者调试面板里核对。
        """
        from core import devlog
        from ui.theme import effective_font_size
        self.cfg.save()
        self._rebuild_system_prompt()          # 系统提示变化后重置上下文

        theme = self.cfg.appearance.get("theme")
        base_fs = int(self.cfg.appearance.get("font_size", 14))
        scale = self.cfg.data.get("font_scale", "标准")
        eff_fs = effective_font_size(base_fs, scale)
        top = bool(self.cfg.appearance.get("always_on_top", True))
        new_size = int(self.cfg.appearance.get("ball_size", 56))
        hotkey = self.cfg.data.get("hotkey") or DEFAULT_HOTKEY

        snap = {
            "theme": theme, "font_size": base_fs, "font_scale": scale,
            "hotkey": hotkey, "ball_size": new_size, "always_on_top": top,
            "provider": self.cfg.provider,
            "agent_enabled": bool(self.cfg.data.get("agent_enabled", True)),
            "deep_thinking": bool(self.cfg.data.get("deep_thinking", False)),
            "debug_mode": bool(self.cfg.data.get("debug_mode", False)),
            "log_level": self.cfg.data.get("log_level", "INFO"),
            "mcp_count": len(self.cfg.data.get("mcp_servers") or []),
        }
        prev = getattr(self, "_applied_snapshot", {})
        changed = {k for k, v in snap.items() if prev.get(k) != v}
        self._applied_snapshot = snap
        if changed:
            devlog.info("settings", "设置已保存，变更项：%s"
                        % "、".join(sorted(changed)))

        # 1) 主题 / 字号：只在相关项变化时刷新全部窗口
        if not prev or (changed & {"theme", "font_size", "font_scale"}):
            self.window.apply_theme()
            self.ball.set_theme(theme)
            if self.tray is not None:
                self.tray.setIcon(make_tray_icon(theme))
            self._refresh_open_dialogs_theme(theme, eff_fs)

        # 2) 调试日志开关与级别
        if not prev or (changed & {"debug_mode", "log_level"}):
            devlog.configure(enabled=snap["debug_mode"],
                             level=snap["log_level"], cfg=self.cfg)

        # 3) 智能体 / 技能 / 工具按钮
        if not prev or (changed & {"agent_enabled", "provider", "mcp_count"}):
            self.window.set_agent_enabled(snap["agent_enabled"])
            self.window.refresh_skills()
            self.window._refresh_tools_button()

        # 4) 全局热键：仅变更时重启
        if hotkey != self.hotkey.hotkey:
            self._restart_hotkey()

        # 5) 重新播放新手引导（用户在设置中请求）
        if self._pending_onboarding:
            self._pending_onboarding = False
            QTimer.singleShot(500, self.start_onboarding)

        # 6) 模型列表：仅服务商变化或首次
        if not prev or "provider" in changed:
            self.models.reload_combo()
        self.window.set_deep_thinking(snap["deep_thinking"])

        # 7) 置顶：仅变更时
        if not prev or "always_on_top" in changed:
            self.window.setWindowFlag(Qt.WindowStaysOnTopHint, top)
            self.ball.set_always_on_top(top)
            if self.window.isVisible():
                self.window.show()

        # 8) 悬浮球：仅尺寸变化时重建
        if new_size != self.ball._size:
            pos = self.ball.pos()
            state = self.ball._state
            self.ball.close()
            self.ball.deleteLater()
            self.ball = FloatingBall(size=new_size)
            self.ball.set_theme(theme)
            self.ball.move(pos)
            self.ball.set_state(state)
            self._wire_ball()
            if not self.window.isVisible():
                self.ball.fade_in()
        self.window._update_status()
        # 9) 模型刷新 / 本地探测保持原有节奏（异步、不阻塞保存）
        if self.cfg.data.get("auto_refresh_models", True):
            QTimer.singleShot(300, self.models.refresh_models)
        QTimer.singleShot(300, self.models.probe_local)

    # ------------------------------------------------------------------
    # 新手引导
    # ------------------------------------------------------------------
    def start_onboarding(self):
        from ui.onboarding import OnboardingOverlay
        if getattr(self, "_onboarding", None) is not None:
            self._onboarding.close()
            self._onboarding.deleteLater()
        self._onboarding = OnboardingOverlay(self)
        self._onboarding.start()

    def _on_onboarding_requested(self):
        self._pending_onboarding = True

    # ------------------------------------------------------------------
    def run(self):
        return self.qt.exec_()

    def quit(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        self.speaker.stop()
        # v7.3：断开 MCP 服务器子进程并卸载其工具
        try:
            self.mcp.stop_all()
        except Exception:                          # noqa: BLE001
            pass
        # 关闭浏览器 harness（若正在使用网页版模式）
        try:
            from core.browser_llm import BrowserSession
            BrowserSession.instance().stop()
        except Exception:                          # noqa: BLE001
            pass
        self.window.save_geometry()
        self._save_current_session()
        self.hotkey.stop()
        # v7.2：划词热键与待机气泡同样要收干净，避免线程残留
        self.quick_hotkey.stop()
        try:
            if self._quick_win is not None:
                self._quick_win.close()
            self.ball.close_bubble()
        except Exception:                          # noqa: BLE001
            pass
        self.cfg.appearance["ball_position"] = [self.ball.x(), self.ball.y()]
        self.cfg.save()
        self._auto_clean_tmp_on_exit()   # v13.5：可选，仍带备份/小批量保护
        if self.tray is not None:
            self.tray.hide()
        self.qt.quit()
