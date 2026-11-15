# -*- coding: utf-8 -*-
"""主聊天窗口：无边框圆角窗口，标题栏（含模型切换）、消息流、输入区（附件）、状态栏。"""
from PyQt5.QtCore import (Qt, QEvent, QPoint, QRect, QTimer, pyqtSignal,
                          QPropertyAnimation, QEasingCurve)
from PyQt5.QtGui import QColor, QKeySequence
from PyQt5.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QComboBox, QMenu,
                             QApplication, QGraphicsDropShadowEffect, QTextEdit,
                             QShortcut, QFileDialog, QSizePolicy, QCheckBox,
                             QLineEdit, QSlider, QScrollBar, QTextBrowser,
                             QSpinBox, QListWidget)

from core import uilayout
from core.config import APP_VERSION
from core.attachment import load_file_attachment, image_attachment
from core.agent.skills import SkillManager
from core.agent.market import PluginMarket
from core.context import context_usage_str
from ui.attachment_bar import AttachmentBar
from ui.theme import build_qss, get_theme, RADIUS_L, effective_font_size
from ui.frost import FrostGlass
from ui.widgets import AssistantBubble, UserBubble, fade_in_widget


class InputEdit(QTextEdit):
    """输入框：Enter 发送，Shift+Enter 换行，Ctrl+V 粘贴图片"""
    send = pyqtSignal()
    image_pasted = pyqtSignal(object)      # QImage

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min_h = 112
        self._max_h = 210
        self._pad = 26
        self.document().documentLayout().documentSizeChanged.connect(self._auto_height)

    def set_bounds(self, min_h, max_h, pad):
        """v13.6.5：按栏目密度调整输入框高度区间（即时生效）"""
        self._min_h, self._max_h, self._pad = int(min_h), int(max_h), int(pad)
        self.setFixedHeight(max(self._min_h, min(self._max_h, self.height())))

    def _auto_height(self, size):
        h = max(self._min_h, min(self._max_h, int(size.height()) + self._pad))
        self.setFixedHeight(h)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.send.emit()
            return
        if e.matches(QKeySequence.Paste):
            mime = QApplication.clipboard().mimeData()
            if mime.hasImage():
                img = QApplication.clipboard().image()
                if not img.isNull():
                    self.image_pasted.emit(img)
                    return
        super().keyPressEvent(e)


class ChatWindow(QWidget):
    send_requested = pyqtSignal(str, list)      # (文本, [Attachment])
    stop_requested = pyqtSignal()
    regenerate_requested = pyqtSignal()
    model_change_requested = pyqtSignal(str)    # 真实模型名
    settings_requested = pyqtSignal()
    minimize_requested = pyqtSignal()
    screenshot_requested = pyqtSignal()
    deep_thinking_requested = pyqtSignal(bool)
    skill_changed = pyqtSignal(str)             # 技能 id
    tools_changed = pyqtSignal()                # 工具开关变化
    market_requested = pyqtSignal()             # 打开插件市场
    automation_requested = pyqtSignal()         # 打开自动化任务
    panel_requested = pyqtSignal()              # 打开专家会诊
    sessions_requested = pyqtSignal()           # 打开会话管理
    prompts_requested = pyqtSignal()            # 打开提示词库
    library_requested = pyqtSignal()            # 打开资料库
    memory_requested = pyqtSignal()             # 打开长期记忆（V8.0）
    artifacts_requested = pyqtSignal()         # 产物预览（V9.0 Artifacts）
    models_requested = pyqtSignal()             # 打开模型库（魔塔 GGUF）
    about_requested = pyqtSignal()              # 关于对话框
    example_requested = pyqtSignal(str)         # 欢迎页示例问题（点击即发）
    speak_requested = pyqtSignal(str)           # 朗读某条回复（正文文本）
    variant_selected = pyqtSignal(int)          # 切换回答变体（索引）
    command_palette_requested = pyqtSignal()    # 打开命令面板（Ctrl+K）
    density_cycle_requested = pyqtSignal()      # v13.6.5：Ctrl+Alt+D 切换栏目密度
    selection_mode_changed = pyqtSignal(bool)  # v13.7：消息勾选模式
    delete_selected_requested = pyqtSignal(list)  # v13.7：删除所选历史索引
    background_changed = pyqtSignal()          # v13.7：主窗口背景立即应用
    delete_one_requested = pyqtSignal(int)    # v13.8：删除单条（气泡序号）
    edit_one_requested = pyqtSignal(int)      # v13.8：编辑单条
    copy_one_requested = pyqtSignal(int)      # v13.8：复制单条
    star_one_requested = pyqtSignal(int)      # v13.8：收藏单条
    find_requested = pyqtSignal()             # v13.8：会话内查找
    slash_command = pyqtSignal(str)           # v13.8：斜杠命令
    closed = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.cfg = config
        # v13.6.5：一次性升级旧窗口尺寸（config.json 里的 430×640 会覆盖
        # 代码默认值，导致「改了布局却看不到变化」），并打迁移标记。
        self._layout_migration = uilayout.migrate(config)
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self._current_bubble = None
        self._drag_pos = None
        self._resize_pos = None
        self._start_geo = None
        self._hint_timer = None
        self._stick_bottom = True
        self._selection_mode = False
        self._msg_checks = []            # [(check, history_index, bubble)]
        self._open_children = []         # 非模态子窗口引用（防 GC）
        self._drag_active = False        # v13.8：按下时锁定，移动中不再重复判定
        self.skills = SkillManager(config)
        self.market = PluginMarket(config)
        self._build_ui()
        self.apply_theme()
        self._restore_geometry()
        # 欢迎页作为初始态；有历史会话时 AssistantApp.reveal() 会调用
        # _render_history() → clear_messages() 将其清掉，不会混入消息流。
        self.show_welcome()
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlag(Qt.WindowStaysOnTopHint,
                           bool(self.cfg.appearance.get("always_on_top", True)))
        size = self.cfg.appearance.get("window_size") or uilayout.metrics(
            self.cfg.data.get("ui_density"))["window"]
        self.resize(int(size[0]), int(size[1]))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 16)   # 给阴影留空间
        outer.setSpacing(0)
        self._outer = outer
        # v7.3：内容面板改为真·毛玻璃（FrostGlass），背后桌面经抓屏模糊后透出
        self.container = FrostGlass(self, radius=RADIUS_L)
        self.container.setObjectName("FrostHost")
        self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self.container)

        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(26)
        shadow.setColor(QColor(0, 0, 0, 110))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)

        # 复用 FrostGlass 自带布局（避免重复 setLayout 冲突）
        root = self.container.layout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 标题栏 ----
        self.title_bar = QFrame()
        self.title_bar.setObjectName("TitleBar")
        self.title_bar.setFixedHeight(56)
        self.title_bar.installEventFilter(self)
        tl = QHBoxLayout(self.title_bar)
        tl.setContentsMargins(16, 0, 10, 0)
        tl.setSpacing(10)
        self._tl = tl
        self.logo = QPushButton("✦")
        self.logo.setObjectName("LogoLabel")
        self.logo.setFlat(True)
        self.logo.setCursor(Qt.PointingHandCursor)
        self.logo.setToolTip("关于 星语 · Starry")
        self.logo.setFixedSize(28, 28)
        self.logo.clicked.connect(self.about_requested)
        self.title_label = QLabel("星语 · Starry")
        self.title_label.setObjectName("TitleLabel")
        tl.addWidget(self.logo)
        tl.addWidget(self.title_label)
        tl.addStretch(1)
        self.model_combo = QComboBox()
        self.model_combo.setToolTip("切换模型（更多模型见设置）")
        self.model_combo.setMinimumWidth(130)
        self.model_combo.currentIndexChanged.connect(self._on_model_index_changed)
        tl.addWidget(self.model_combo)
        self.sessions_btn = QPushButton("💬")
        self.sessions_btn.setObjectName("FlatButton")
        self.sessions_btn.setToolTip("会话管理（新建 / 切换 / 搜索 / 导出）")
        self.sessions_btn.setFixedSize(30, 30)
        self.sessions_btn.setCursor(Qt.PointingHandCursor)
        self.sessions_btn.clicked.connect(self.sessions_requested)
        self.library_btn = QPushButton("📚")
        self.library_btn.setObjectName("FlatButton")
        self.library_btn.setToolTip("资料库：导入文档，让 AI 基于你的资料回答")
        self.library_btn.setFixedSize(30, 30)
        self.library_btn.setCursor(Qt.PointingHandCursor)
        self.library_btn.clicked.connect(self.library_requested)
        self.memory_btn = QPushButton("🧠")
        self.memory_btn.setObjectName("FlatButton")
        self.memory_btn.setToolTip("长期记忆：星语记住的关于你与项目的信息")
        self.memory_btn.setFixedSize(30, 30)
        self.memory_btn.setCursor(Qt.PointingHandCursor)
        self.memory_btn.clicked.connect(self.memory_requested)
        self.models_btn = QPushButton("📦")
        self.models_btn.setObjectName("FlatButton")
        self.models_btn.setToolTip("模型库：从阿里魔塔下载 GGUF 本地模型（llama.cpp）")
        self.models_btn.setFixedSize(30, 30)
        self.models_btn.setCursor(Qt.PointingHandCursor)
        self.models_btn.clicked.connect(self.models_requested)
        self.artifacts_btn = QPushButton("🧪")
        self.artifacts_btn.setObjectName("FlatButton")
        self.artifacts_btn.setToolTip("产物预览：在浏览器预览最近回复里的 HTML 产物")
        self.artifacts_btn.setFixedSize(30, 30)
        self.artifacts_btn.setCursor(Qt.PointingHandCursor)
        self.artifacts_btn.clicked.connect(self.artifacts_requested)
        self.palette_btn = QPushButton("✨")
        self.palette_btn.setObjectName("FlatButton")
        self.palette_btn.setToolTip("命令面板（Ctrl+K）：所有功能一键可达")
        self.palette_btn.setFixedSize(30, 30)
        self.palette_btn.setCursor(Qt.PointingHandCursor)
        self.palette_btn.clicked.connect(self.command_palette_requested)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("FlatButton")
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setFixedSize(30, 30)
        self.settings_btn.clicked.connect(self.settings_requested)
        tl.addWidget(self.settings_btn)
        self.min_btn = QPushButton("—")
        self.min_btn.setObjectName("FlatButton")
        self.min_btn.setToolTip("收起为悬浮小球")
        self.min_btn.setFixedSize(30, 30)
        self.min_btn.clicked.connect(self._play_minimize)
        tl.addWidget(self.min_btn)

        # v13.6.5：次要功能收进「⋯ 更多」，标题栏不再横向挤成一团。
        # 原按钮对象/信号全部保留，仅从布局移入菜单（兼容性不变）。
        self._more_btn = QPushButton("⋯")
        self._more_btn.setObjectName("FlatButton")
        self._more_btn.setToolTip("更多功能（会话 / 资料库 / 记忆 / 模型库 / 产物 / 命令面板）")
        self._more_btn.setCursor(Qt.PointingHandCursor)
        self._more_menu = QMenu(self)
        for _btn, _text in (
                (self.sessions_btn, "💬 会话管理"),
                (self.library_btn, "📚 资料库"),
                (self.memory_btn, "🧠 长期记忆"),
                (self.models_btn, "📦 本地模型库"),
                (self.artifacts_btn, "🧪 产物预览"),
                (self.palette_btn, "✨ 命令面板")):
            _btn.hide()
            _a = self._more_menu.addAction(_text)
            _a.triggered.connect(lambda _c=False, _b=_btn: _b.click())
        self._menu_select_action = self._more_menu.addAction("☑ 选择 / 删除消息")
        self._menu_select_action.triggered.connect(self._toggle_selection_mode)
        self._more_btn.setMenu(self._more_menu)
        tl.insertWidget(tl.indexOf(self.settings_btn), self._more_btn)
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("FlatButton")
        self.close_btn.setToolTip("关闭（退到托盘）")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.clicked.connect(self._play_minimize)
        tl.addWidget(self.close_btn)
        root.addWidget(self.title_bar)

        # ---- 消息滚动区 ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.messages_widget = QWidget()
        self.messages_widget.installEventFilter(self)
        self.msg_layout = QVBoxLayout(self.messages_widget)
        self.msg_layout.setContentsMargins(14, 14, 14, 12)
        self.msg_layout.setSpacing(14)
        self.msg_layout.addStretch(1)
        self._msg_layout = self.msg_layout
        self.scroll.setWidget(self.messages_widget)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value)
        root.addWidget(self.scroll, 1)

        # ---- 输入区 ----
        input_frame = QFrame()
        il = QVBoxLayout(input_frame)
        il.setContentsMargins(14, 10, 14, 14)
        il.setSpacing(10)
        self._il, self._input_frame = il, input_frame

        # 附件栏
        self.attach_bar = AttachmentBar()
        self.attach_bar.remove_requested.connect(self._remove_attachment)
        il.addWidget(self.attach_bar)

        # v13.7：消息勾选工具条（默认隐藏）
        self._selection_bar = QFrame()
        sb = QHBoxLayout(self._selection_bar)
        sb.setContentsMargins(6, 2, 6, 2)
        sb.setSpacing(8)
        self._selection_info = QLabel("勾选要删除的消息")
        self._selection_info.setObjectName("MutedLabel")
        sb.addWidget(self._selection_info)
        sb.addStretch(1)
        self._sel_all_btn = QPushButton("全选")
        self._sel_all_btn.setObjectName("FlatButton")
        self._sel_all_btn.clicked.connect(self._select_all_messages)
        sb.addWidget(self._sel_all_btn)
        self._del_selected_btn = QPushButton("🗑 删除选中")
        self._del_selected_btn.setObjectName("FlatButton")
        self._del_selected_btn.setEnabled(False)
        self._del_selected_btn.clicked.connect(self._emit_delete_selected)
        sb.addWidget(self._del_selected_btn)
        self._sel_done_btn = QPushButton("完成")
        self._sel_done_btn.setObjectName("FlatButton")
        self._sel_done_btn.clicked.connect(lambda: self.set_selection_mode(False))
        sb.addWidget(self._sel_done_btn)
        self._selection_bar.hide()
        il.addWidget(self._selection_bar)

        # ---- 智能体行：技能 / 工具 / 插件市场 ----
        agent_row = QHBoxLayout()
        agent_row.setSpacing(8)
        self._agent_row = agent_row
        self.skill_combo = QComboBox()
        self.skill_combo.setToolTip("切换技能：为 AI 切换专家人设（提示词）")
        self.skill_combo.setMinimumWidth(112)
        self._reload_skills()
        self.skill_combo.currentIndexChanged.connect(self._on_skill_changed)
        agent_row.addWidget(self.skill_combo)

        self.tools_btn = QPushButton("🧰 工具 · %d" % self._tool_count())
        self.tools_btn.setObjectName("FlatButton")
        self.tools_btn.setCursor(Qt.PointingHandCursor)
        self.tools_btn.setFixedHeight(34)
        self.tools_btn.setToolTip("管理 AI 可调用的工具（点击开关工具包）")
        self.tools_btn.clicked.connect(self._show_tools_menu)
        agent_row.addWidget(self.tools_btn)

        self.market_btn = QPushButton("🧩 插件市场")
        self.market_btn.setObjectName("FlatButton")
        self.market_btn.setCursor(Qt.PointingHandCursor)
        self.market_btn.setFixedHeight(34)
        self.market_btn.setToolTip("浏览 / 安装智能体插件（工具包 · 技能包 · 代码插件）")
        self.market_btn.clicked.connect(self.market_requested)
        agent_row.addWidget(self.market_btn)

        self.automation_btn = QPushButton("⏰ 自动化")
        self.automation_btn.setObjectName("FlatButton")
        self.automation_btn.setCursor(Qt.PointingHandCursor)
        self.automation_btn.setFixedHeight(34)
        self.automation_btn.setToolTip("自动化任务：定时 / 间隔自动执行提示词")
        self.automation_btn.clicked.connect(self.automation_requested)
        agent_row.addWidget(self.automation_btn)

        self.panel_btn = QPushButton("🎭")
        self.panel_btn.setObjectName("FlatButton")
        self.panel_btn.setCursor(Qt.PointingHandCursor)
        self.panel_btn.setFixedHeight(34)
        self.panel_btn.setToolTip("专家会诊：多位专家并行回答，主持人汇总")
        self.panel_btn.clicked.connect(self.panel_requested)
        agent_row.addWidget(self.panel_btn)
        agent_row.addStretch(1)
        il.addLayout(agent_row)

        self.input = InputEdit()
        self.input.setObjectName("InputEdit")
        self.input.setFixedHeight(88)
        self.input.setPlaceholderText(
            "输入消息，Enter 发送，Shift+Enter 换行\n可拖入 / 粘贴图片文件，或点 ✂ 截图")
        self.input.send.connect(self._on_send_clicked)
        self.input.image_pasted.connect(self._on_image_pasted)
        il.addWidget(self.input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._btn_row = btn_row
        self.hint_label = QLabel("Enter 发送 · Shift+Enter 换行")
        self.hint_label.setObjectName("MutedLabel")
        btn_row.addWidget(self.hint_label)
        btn_row.addStretch(1)

        # 深度思考开关
        self.deep_btn = QPushButton("🧠 深度思考")
        self.deep_btn.setObjectName("FlatButton")
        self.deep_btn.setCheckable(True)
        self.deep_btn.setChecked(bool(self.cfg.data.get("deep_thinking", False)))
        self.deep_btn.setCursor(Qt.PointingHandCursor)
        self.deep_btn.setFixedHeight(36)
        self.deep_btn.setToolTip("开启后优先选用推理模型（展示思考过程）")
        self.select_msg_btn = QPushButton("☑")
        self.select_msg_btn.setObjectName("FlatButton")
        self.select_msg_btn.setToolTip("选择消息：勾选后批量删除，或右键单条消息")
        self.select_msg_btn.setCursor(Qt.PointingHandCursor)
        self.select_msg_btn.clicked.connect(self._toggle_selection_mode)
        btn_row.addWidget(self.select_msg_btn)
        self.find_btn = QPushButton("🔍")
        self.find_btn.setObjectName("FlatButton")
        self.find_btn.setToolTip("在当前对话中查找（Ctrl+F）")
        self.find_btn.setCursor(Qt.PointingHandCursor)
        self.find_btn.clicked.connect(self.find_requested.emit)
        btn_row.addWidget(self.find_btn)
        self.deep_btn.toggled.connect(self.deep_thinking_requested)
        btn_row.addWidget(self.deep_btn)

        # 附件按钮
        self.file_btn = QPushButton("📎")
        self.file_btn.setObjectName("FlatButton")
        self.file_btn.setToolTip("发送文件（文本/代码/PDF/图片）")
        self.file_btn.setFixedSize(30, 30)
        self.file_btn.setCursor(Qt.PointingHandCursor)
        self.file_btn.clicked.connect(self._pick_file)
        btn_row.addWidget(self.file_btn)

        self.img_btn = QPushButton("🖼")
        self.img_btn.setObjectName("FlatButton")
        self.img_btn.setToolTip("发送图片")
        self.img_btn.setFixedSize(30, 30)
        self.img_btn.setCursor(Qt.PointingHandCursor)
        self.img_btn.clicked.connect(self._pick_image)
        btn_row.addWidget(self.img_btn)

        self.shot_btn = QPushButton("✂")
        self.shot_btn.setObjectName("FlatButton")
        self.shot_btn.setToolTip("截图并发送（Ctrl+Shift+S）")
        self.shot_btn.setFixedSize(30, 30)
        self.shot_btn.setCursor(Qt.PointingHandCursor)
        self.shot_btn.clicked.connect(self.screenshot_requested)
        btn_row.addWidget(self.shot_btn)

        # 提示词库
        self.prompt_btn = QPushButton("📖")
        self.prompt_btn.setObjectName("FlatButton")
        self.prompt_btn.setToolTip("提示词库：一键插入常用提示词")
        self.prompt_btn.setFixedSize(34, 34)
        self.prompt_btn.setCursor(Qt.PointingHandCursor)
        self.prompt_btn.clicked.connect(self.prompts_requested)
        btn_row.addWidget(self.prompt_btn)

        # 停止 / 发送
        self.stop_btn = QPushButton("■ 停止")
        self.stop_btn.setObjectName("FlatButton")
        self.stop_btn.hide()
        self.stop_btn.clicked.connect(self.stop_requested)
        btn_row.addWidget(self.stop_btn)

        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("AccentButton")
        self.send_btn.setFixedHeight(38)
        self.send_btn.clicked.connect(self._on_send_clicked)
        btn_row.addWidget(self.send_btn)
        il.addLayout(btn_row)
        root.addWidget(input_frame)

        # ---- 状态栏 ----
        self.status = QLabel("")
        self.status.setObjectName("MutedLabel")
        self.status.setFixedHeight(30)
        self.status.setContentsMargins(16, 0, 16, 0)
        root.addWidget(self.status)
        # 上下文用量（由控制器在每次请求前回填）
        self._ctx_used = 0
        self._ctx_limit = 0

        # ---- 缩放手柄 ----
        self.grip = QWidget(self.container)
        self.grip.setFixedSize(16, 16)
        self.grip.setCursor(Qt.SizeFDiagCursor)
        self.grip.installEventFilter(self)
        self.grip.move(self.container.width() - 24, self.container.height() - 24)

        # 截图快捷键
        sc = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        sc.activated.connect(self.screenshot_requested)
        sc2 = QShortcut(QKeySequence("Ctrl+Alt+D"), self)
        sc2.activated.connect(self.density_cycle_requested)
        sc3 = QShortcut(QKeySequence("Ctrl+F"), self)
        sc3.activated.connect(self.find_requested)
        sc4 = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
        sc4.activated.connect(self._toggle_selection_mode)
        sc5 = QShortcut(QKeySequence("Ctrl+Shift+X"), self)
        sc5.activated.connect(lambda: self.set_selection_mode(False))

        # 统一按当前密度档位应用到全部栏目（也是即时切换的入口）
        self._apply_layout()
        # v13.7：给整个窗口子树装拖拽过滤器（含动态新增的气泡），
        # 交互控件在 eventFilter 里显式放行，保证按钮/输入框照常工作。
        self._drag_installed = False
        self._install_drag_filter()
        self.apply_background()

        # 命令面板快捷键（Ctrl+K，Raycast / VSCode 式全局入口）
        ck = QShortcut(QKeySequence("Ctrl+K"), self)
        ck.activated.connect(self.command_palette_requested)

        self._update_status()

    # ------------------------------------------------------------------
    # 消息流
    # ------------------------------------------------------------------
    def show_welcome(self):
        from urllib.parse import quote
        examples = [
            ("🕐 现在几点了？顺便算笔账",
             "现在几点了？帮我顺便算一下 (128+47)*3"),
            ("🔍 搜一下 AI 桌面助手的新趋势",
             "联网搜索一下 2026 年桌面 AI 助手的发展趋势"),
            ("🧮 让智能体算笔账",
             "帮我计算：一个项目预算 12500 元，分 8 期，每期多少？"),
        ]
        links = "\n".join(
            "- [%s](send:%s)" % (title, quote(text, safe=""))
            for title, text in examples)
        bubble = AssistantBubble(self._theme, self._fs)
        bubble.thinking.skip()
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bubble)
        fade_in_widget(bubble)
        bubble.content.setOpenExternalLinks(False)
        bubble.content.anchorClicked.connect(self._on_welcome_link)
        bubble.append_content(
            "你好！我是**星语**，你的桌面 AI 助手 ✦\n\n"
            "试试这些（点击即问）：\n\n"
            + links + "\n\n"
            "也可以直接输入问题 —— **Enter** 发送，**Shift+Enter** 换行。\n\n"
            "- 🧠 深度思考可查看推理过程\n"
            "- 📎🖼✂ 支持文件 / 图片 / 截图\n"
            "- 📚 资料库：导入文档，让 AI 基于你的资料回答\n"
            "- ⏰ 自动化：定时 / 间隔自动执行任务\n"
            "- 🎭 会诊：多位专家并行分析，主持人汇总\n"
            "- 🧩 输入区上方可切换技能、管理工具与插件\n"
            "- 💬 标题栏可管理多个会话，📖 可一键插入提示词")
        bubble.flush()

    def _on_welcome_link(self, url):
        """欢迎页示例问题：点击即发送"""
        if url.scheme() == "send":
            from PyQt5.QtCore import QUrl
            text = QUrl.fromPercentEncoding(
                url.toString().replace("send:", "", 1).encode("utf-8"))
            self.example_requested.emit(text)

    def clear_messages(self):
        """v13.7：彻底清空消息流（切换会话 / 清空对话用）。

        旧实现只删除 widget，stretch 与 deleteLater 残留项可能让界面看起来
        「没清空」；这里把全部 item（含 spacer）移除并重建 stretch，
        同时清理勾选状态与缓存气泡引用。
        """
        while self.msg_layout.count():
            item = self.msg_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.msg_layout.addStretch(1)
        self._current_bubble = None
        self._msg_checks = []
        self._selection_mode = False
        self._update_selection_bar()

    def set_empty_hint(self, text="已清空对话，输入消息开始新的一轮"):
        """清空后的空态提示（不是消息气泡，不会被当成对话记录）"""
        lb = QLabel(text)
        lb.setObjectName("MutedLabel")
        lb.setAlignment(Qt.AlignCenter)
        lb.setWordWrap(True)
        lb.setProperty("empty_hint", True)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, lb)
        return lb

    # ------------------------------------------------------------------
    # v13.7 消息勾选 / 批量删除
    # ------------------------------------------------------------------
    def _update_selection_bar(self):
        bar = getattr(self, "_selection_bar", None)
        if bar is not None:
            bar.setVisible(self._selection_mode)
            n = sum(1 for c, _i, _b in self._msg_checks if c.isChecked())
            self._del_selected_btn.setEnabled(n > 0)
            self._selection_info.setText("已选 %d 条" % n if n else "勾选要删除的消息")

    def _bubble_ordinals(self):
        """按布局顺序返回所有消息气泡及其序号（含流式回复气泡）。"""
        out = []
        for i in range(self.msg_layout.count()):
            item = self.msg_layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, (UserBubble, AssistantBubble)):
                out.append((len(out), w))
        return out

    def _ensure_checks(self):
        """v13.8：给**每一条**消息气泡挂复选框 + 单条操作按钮。

        旧实现只给 _render_history/on_send 创建的气泡挂过复选框，流式回复
        气泡没有 → 用户看不到勾选框。这里按布局顺序统一补齐并校准序号。
        """
        for ordinal, bubble in self._bubble_ordinals():
            entry = next((e for e in self._msg_checks if e[2] is bubble), None)
            if entry is None:
                cb = QCheckBox("选择")
                cb.setObjectName("MsgCheck")
                cb.setFixedHeight(24)
                cb.setToolTip("勾选后点「删除选中」；也可右键单条消息单独删除")
                cb.setStyleSheet(
                    "QCheckBox{spacing:4px;color:#5b7086;font-size:12px;}"
                    "QCheckBox::indicator{width:18px;height:18px;}"
                    "QCheckBox::indicator:checked{background:#3d8bfd;"
                    "border:1px solid #2f6fd0;border-radius:4px;}")
                cb.stateChanged.connect(self._update_selection_bar)
                lay = bubble.layout()
                if lay is not None:
                    lay.insertWidget(0, cb)
                else:
                    cb.setParent(bubble)
                    cb.move(4, 4)
                entry = [cb, ordinal, bubble]
                self._msg_checks.append(entry)
            entry[1] = ordinal
            if self._selection_mode:
                entry[0].show()
            else:
                entry[0].hide()
        # 清理已销毁气泡的残留项
        alive = {w for _o, w in self._bubble_ordinals()}
        self._msg_checks = [e for e in self._msg_checks if e[2] in alive]

    def set_selection_mode(self, on):
        """进入/退出消息勾选模式；on=True 时确保每条消息都有复选框。"""
        self._selection_mode = bool(on)
        self._ensure_checks()
        for cb, _i, _b in self._msg_checks:
            if self._selection_mode:
                cb.show()
            else:
                cb.setChecked(False)
                cb.hide()
        self._update_selection_bar()
        self.selection_mode_changed.emit(self._selection_mode)

    def _attach_check(self, bubble, index):
        """兼容旧调用：统一走 _ensure_checks 的同一套复选框。"""
        entry = next((e for e in self._msg_checks if e[2] is bubble), None)
        if entry is None:
            self._ensure_checks()
        else:
            entry[1] = int(index)

    def tag_last_message(self, index):
        """把刚插入的气泡与序号绑定（兼容旧调用；实际由 _ensure_checks 校准）。"""
        ords = self._bubble_ordinals()
        if not ords:
            return False
        o, bubble = ords[-1]
        self._attach_check(bubble, o if index is None else index)
        return True

    def _bubble_context_menu(self, bubble, global_pos):
        """v13.8：消息右键菜单 —— 复制 / 编辑 / 删除本条 / 收藏。"""
        for ordinal, w in self._bubble_ordinals():
            if w is bubble:
                menu = QMenu(self)
                a_copy = menu.addAction("📋 复制这条")
                a_edit = menu.addAction("✏️ 编辑这条")
                a_star = menu.addAction("⭐ 收藏/取消收藏")
                menu.addSeparator()
                a_del = menu.addAction("🗑 删除这条")
                act = menu.exec_(global_pos)
                if act is a_copy:
                    self.copy_one_requested.emit(ordinal)
                elif act is a_edit:
                    self.edit_one_requested.emit(ordinal)
                elif act is a_star:
                    self.star_one_requested.emit(ordinal)
                elif act is a_del:
                    self.delete_one_requested.emit(ordinal)
                return
        return None

    def _toggle_selection_mode(self):
        self.set_selection_mode(not self._selection_mode)
        self.show_hint("已开启消息勾选：勾选后点「删除选中」，或右键单条消息" if self._selection_mode
                       else "已退出消息勾选")

    def _select_all_messages(self):
        self._ensure_checks()
        any_unchecked = any(not c.isChecked() for c, _i, _b in self._msg_checks)
        for c, _i, _b in self._msg_checks:
            c.setChecked(any_unchecked)
        self._update_selection_bar()

    def _emit_delete_selected(self):
        self._ensure_checks()
        idx = self.selected_history_indices()
        if idx:
            self.delete_selected_requested.emit(idx)
        else:
            self.show_hint("请先勾选要删除的消息")

    def selected_history_indices(self):
        return sorted({i for c, i, _b in self._msg_checks if c.isChecked()},
                      reverse=True)

    # ------------------------------------------------------------------
    # v13.7 主窗口背景自定义（立即生效）
    # ------------------------------------------------------------------
    def apply_background(self):
        ap = self.cfg.appearance
        self.container.set_custom_background(
            ap.get("background_mode", "theme"),
            ap.get("background_color", ""),
            ap.get("background_image", ""),
            int(ap.get("background_opacity", 35)))

    def _install_drag_filter(self):
        if self._drag_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._drag_installed = True

    def add_user_message(self, text, attachments=None):
        bubble = UserBubble(text or "", self._theme, self._fs, attachments)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bubble)
        fade_in_widget(bubble)
        self._scroll_bottom()
        return bubble

    def set_last_user_badge(self, text):
        """给最后一条用户气泡设置角标（如「📚 已引用资料库」）"""
        for i in range(self.msg_layout.count() - 1, -1, -1):
            item = self.msg_layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, UserBubble):
                w.set_badge(text)
                return True
        return False

    def start_assistant_message(self):
        bubble = AssistantBubble(self._theme, self._fs)
        bubble.regenerate_requested.connect(self.regenerate_requested)
        bubble.speak_requested.connect(self.speak_requested)
        bubble.variant_selected.connect(self.variant_selected)
        self._current_bubble = bubble
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bubble)
        fade_in_widget(bubble)
        self._scroll_bottom()
        return bubble

    def append_reasoning(self, text):
        if self._current_bubble:
            self._current_bubble.thinking.append(text)
            self._maybe_scroll()

    def append_content(self, text):
        if self._current_bubble:
            self._current_bubble.append_content(text)
            self._maybe_scroll()

    def finish_message(self):
        if self._current_bubble:
            self._current_bubble.flush()
            self._current_bubble.thinking.finish()
            self._current_bubble = None
            self._scroll_bottom()

    def fail_message(self, error):
        if self._current_bubble:
            self._current_bubble.flush()
            self._current_bubble.set_error(error)
            self._current_bubble = None
            self._scroll_bottom()

    def remove_last_assistant(self):
        """移除最后一条 AI 气泡（重新生成用）"""
        layout = self.msg_layout
        for i in range(layout.count() - 1, -1, -1):
            item = layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, AssistantBubble):
                layout.removeWidget(w)
                w.deleteLater()
                return True
        return False

    def set_busy(self, busy):
        self.send_btn.setEnabled(not busy)
        self.input.setEnabled(not busy)
        self.file_btn.setEnabled(not busy)
        self.img_btn.setEnabled(not busy)
        self.shot_btn.setEnabled(not busy)
        self.deep_btn.setEnabled(not busy)
        self.stop_btn.setVisible(bool(busy))
        self._update_status("正在思考…" if busy else None)

    # ------------------------------------------------------------------
    # 附件
    # ------------------------------------------------------------------
    def add_attachment(self, attachment):
        self.attach_bar.add_attachment(attachment)
        self.input.setFocus()

    def attach_buttons_rect(self):
        """📎 🖼 ✂ 📖 附件与提示词按钮的全局矩形（新手引导聚光灯用）"""
        a = self.file_btn.mapToGlobal(QPoint(0, 0))
        b = (self.prompt_btn.mapToGlobal(QPoint(0, 0))
             + QPoint(self.prompt_btn.width(), self.prompt_btn.height()))
        return QRect(a, b)

    def set_session_title(self, title):
        """标题栏显示当前会话名（带省略）"""
        text = (title or "新会话").strip() or "新会话"
        if len(text) > 9:
            text = text[:9] + "…"
        self.title_label.setText(text)
        self.title_label.setToolTip(title or "新会话")

    def insert_text(self, text):
        """把提示词插入输入框（保留已有内容，光标移至末尾）"""
        if not text:
            return
        cursor = self.input.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.input.setFocus()

    def attachments(self):
        return [chip.attachment for chip in self.attach_bar._chips]

    def _remove_attachment(self, idx):
        chips = self.attach_bar._chips
        if not (0 <= idx < len(chips)):
            return
        chip = chips[idx]
        self.attach_bar.layout().removeWidget(chip)
        chip.deleteLater()
        chips.remove(chip)
        if not chips:
            self.attach_bar.hide()
        # 重建剩余芯片的移除信号索引
        for i, c in enumerate(chips):
            try:
                c.remove_clicked.disconnect()
            except TypeError:
                pass
            c.remove_clicked.connect(lambda i=i: self._remove_attachment(i))

    def clear_attachments(self):
        self.attach_bar.clear()

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "所有文件 (*.*)")
        if path:
            self._load_path(path)

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.gif *.bmp)")
        if path:
            self._load_path(path)

    def _load_path(self, path):
        try:
            att = load_file_attachment(path)
        except ValueError as e:
            self.show_hint(str(e))
            return
        self.add_attachment(att)
        self.show_hint("已添加附件：%s" % att.name)

    def _on_image_pasted(self, image):
        self.add_attachment(image_attachment(image, "粘贴的图片"))
        self.show_hint("已从剪贴板添加图片")

    # ---- 拖拽 ----
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() or md.hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasImage():
            img = md.imageData()
            if img is not None:
                self.add_attachment(image_attachment(img, "拖入的图片"))
        for url in md.urls():
            path = url.toLocalFile()
            if path:
                self._load_path(path)

    # ------------------------------------------------------------------
    # 模型下拉框（展示名 ↔ 真实名）
    # ------------------------------------------------------------------
    def set_models(self, models, current=""):
        """models: [str] 或 [(展示名, 真实名)]"""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models or []:
            if isinstance(m, (tuple, list)):
                self.model_combo.addItem(m[0], m[1])
            else:
                self.model_combo.addItem(m, m)
        if current:
            idx = self.model_combo.findData(current)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.addItem(current, current)
                self.model_combo.setCurrentIndex(self.model_combo.count() - 1)
        self.model_combo.blockSignals(False)
        self._update_status()

    def _on_model_index_changed(self, _idx):
        real = self.model_combo.currentData()
        if real:
            self.model_change_requested.emit(real)

    def current_model(self):
        return self.model_combo.currentData() or ""

    def set_deep_thinking(self, on):
        self.deep_btn.setChecked(bool(on))

    def set_memory_count(self, n):
        """更新标题栏记忆按钮上的计数角标（V8.0）。"""
        btn = getattr(self, "memory_btn", None)
        if btn is None:
            return
        n = int(n or 0)
        btn.setText("🧠%d" % n)
        btn.setToolTip("长期记忆：已记住 %d 条（点击查看 / 管理）" % n)

    # ------------------------------------------------------------------
    # 智能体：技能 / 工具 / 插件市场
    # ------------------------------------------------------------------
    def _reload_skills(self):
        """重填技能下拉框（市场安装技能包后由外部调用 refresh_skills）"""
        self.skill_combo.blockSignals(True)
        current = self.skills.current_id()
        self.skill_combo.clear()
        for s in self.skills.all_skills():
            self.skill_combo.addItem(
                "%s %s" % (s.get("icon", "🧩"), s.get("name", s["id"])), s["id"])
        idx = self.skill_combo.findData(current)
        self.skill_combo.setCurrentIndex(max(idx, 0))
        self.skill_combo.blockSignals(False)

    def refresh_skills(self):
        self._reload_skills()

    def _on_skill_changed(self, _idx):
        sid = self.skill_combo.currentData()
        if sid:
            self.skill_changed.emit(sid)

    def current_skill(self):
        return self.skill_combo.currentData() or "general"

    def _tool_count(self):
        return len(self.market.enabled_tools())

    def _refresh_tools_button(self):
        n = self._tool_count()
        self.tools_btn.setText("🧰 工具 · %d" % n)
        if n:
            self.tools_btn.setToolTip("AI 可调用 %d 个工具（点击管理工具包）" % n)
        else:
            self.tools_btn.setToolTip("所有工具已关闭，AI 将只进行普通对话")

    def _show_tools_menu(self):
        menu = QMenu(self)
        for plugin in self.market.all_plugins():
            if plugin.get("type") != "tool":
                continue
            act = menu.addAction("🔧 %s" % plugin.get("name", plugin["id"]))
            act.setCheckable(True)
            act.setChecked(self.market.pack_enabled(plugin["id"]))
            act.setToolTip(plugin.get("description", ""))
            act.toggled.connect(
                lambda on, pid=plugin["id"]: self._on_tool_toggled(pid, on))
        menu.addSeparator()
        open_act = menu.addAction("🧩 打开插件市场 ...")
        open_act.triggered.connect(self.market_requested)
        menu.exec_(self.tools_btn.mapToGlobal(
            QPoint(0, self.tools_btn.height())))

    def _on_tool_toggled(self, plugin_id, on):
        ok, msg = self.market.set_pack_enabled(plugin_id, on)
        self._refresh_tools_button()
        if not ok:
            self.show_hint(msg)
            return
        self.tools_changed.emit()
        names = self.market.get(plugin_id) or {}
        self.show_hint("%s%s：%s" % ("已开启" if on else "已关闭",
                                     names.get("name", ""),
                                     "、".join((names.get("tools") or [])[:3])))

    def set_agent_enabled(self, on):
        """智能体总开关（设置中可关闭，退回普通对话模式）"""
        on = bool(on)
        self.skill_combo.setVisible(on)
        self.tools_btn.setVisible(on)
        self.market_btn.setVisible(on)

    # ------------------------------------------------------------------
    # 主题 / 状态
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # v13.6.5 栏目密度：一处定义、全窗口应用、即时切换
    # ------------------------------------------------------------------
    def _apply_layout(self, name=None):
        name = uilayout.normalize(name or self.cfg.data.get("ui_density"))
        m = uilayout.metrics(name)
        self._outer.setContentsMargins(*m["outer"])
        self.title_bar.setFixedHeight(m["title_h"])
        self._tl.setContentsMargins(*m["title_m"])
        self._tl.setSpacing(m["title_gap"])
        self.logo.setFixedSize(m["logo"], m["logo"])
        self.model_combo.setMinimumWidth(m["model_w"])
        for b in (self.sessions_btn, self.library_btn, self.memory_btn,
                  self.models_btn, self.artifacts_btn, self.palette_btn,
                  self.settings_btn, self.min_btn, self.close_btn,
                  self._more_btn):
            b.setFixedSize(m["icon"], m["icon"])
        self._msg_layout.setContentsMargins(*m["msg_m"])
        self._msg_layout.setSpacing(m["msg_gap"])
        self._il.setContentsMargins(*m["input_m"])
        self._il.setSpacing(m["input_gap"])
        self._agent_row.setSpacing(m["agent_gap"])
        self.skill_combo.setMinimumWidth(m["skill_w"])
        for b in (self.tools_btn, self.market_btn, self.automation_btn,
                  self.panel_btn):
            b.setFixedHeight(m["agent_h"])
        self.input.set_bounds(m["input_min"], m["input_max"], m["input_pad"])
        self._btn_row.setSpacing(m["btn_gap"])
        self.deep_btn.setFixedHeight(m["deep_h"])
        for b in (self.file_btn, self.img_btn, self.shot_btn):
            b.setFixedSize(m["small_icon"], m["small_icon"])
        self.prompt_btn.setFixedSize(m["prompt_icon"], m["prompt_icon"])
        self.send_btn.setFixedHeight(m["send_h"])
        self.stop_btn.setFixedHeight(m["send_h"])
        self.status.setFixedHeight(m["status_h"])
        self.status.setContentsMargins(*m["status_m"])
        self.grip.setFixedSize(m["grip"], m["grip"])
        self.setMinimumSize(*m["min_window"])
        self._layout_metrics = m
        return m

    def set_density(self, name, resize=True):
        """即时切换栏目密度（无需重启）；返回该档位尺寸。"""
        name = uilayout.normalize(name)
        m = self._apply_layout(name)
        self.cfg.data["ui_density"] = name
        if resize:
            self.resize(*m["window"])
            self.cfg.appearance["window_size"] = list(m["window"])
            self.cfg.appearance["window_position"] = None
        self.cfg.save()
        self._update_status()
        self.show_hint("栏目布局已切换为「%s」（%d × %d）"
                       % (name, m["window"][0], m["window"][1]))
        return m

    def reset_layout(self, name=None):
        """一键恢复推荐布局（重置窗口尺寸 / 位置 / 密度）。"""
        m = uilayout.reset(self.cfg, name)
        self._apply_layout(uilayout.normalize(self.cfg.data.get("ui_density")))
        self.resize(*m["window"])
        self._update_status()
        self.show_hint("已恢复推荐布局（%d × %d）" % tuple(m["window"]))
        return m

    def apply_theme(self):
        self._theme = get_theme(self.cfg.appearance.get("theme", "light"))
        base_fs = int(self.cfg.appearance.get("font_size", 14))
        scale = self.cfg.data.get("font_scale", "标准")
        self._fs = effective_font_size(base_fs, scale)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_qss(self._theme, self._fs))
        if getattr(self, "container", None) is not None \
                and hasattr(self.container, "apply_theme"):
            self.container.apply_theme(self._theme)     # 毛玻璃主题同步
        for i in range(self.msg_layout.count()):
            item = self.msg_layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and hasattr(w, "apply_theme"):
                w.apply_theme(self._theme, self._fs)
        self._update_status()

    def _update_status(self, busy_text=None):
        if busy_text:
            self.status.setText(busy_text)
            return
        info = self.cfg.provider_info()
        model = self.cfg.model() or "未选择"
        ready = "就绪" if self.cfg.is_ready() else "未配置 Key"
        extra = " · 本地" if self.cfg.is_local() else ""
        density = uilayout.normalize(self.cfg.data.get("ui_density"))
        text = "%s · %s · %s%s · v%s · 布局%s" % (
            info.get("name", self.cfg.provider), model, ready, extra,
            APP_VERSION, density)
        if self._ctx_limit > 0:
            text += " · 上下文 " + context_usage_str(self._ctx_used,
                                                    self._ctx_limit)
        self.status.setText(text)

    def set_context_usage(self, used, limit):
        """回填上下文用量（每次请求前由控制器调用）"""
        self._ctx_used = int(used or 0)
        self._ctx_limit = int(limit or 0)
        self._update_status()

    def show_hint(self, text, duration=4000):
        """状态栏临时提示，随后恢复"""
        self.status.setText(text)
        if self._hint_timer is not None:
            self._hint_timer.stop()
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(lambda: self._update_status())
        self._hint_timer.start(duration)

    # ------------------------------------------------------------------
    # 窗口行为
    # ------------------------------------------------------------------
    def _restore_geometry(self):
        screen = QApplication.desktop().availableGeometry(self)
        size = self.cfg.appearance.get("window_size")
        if size:
            self.resize(int(size[0]), int(size[1]))
        # 小屏保护：窗口不超过可用区域（保留标题栏可见）
        m = uilayout.metrics(self.cfg.data.get("ui_density"))
        max_w = max(m["min_window"][0], screen.width() - 40)
        max_h = max(m["min_window"][1], screen.height() - 90)
        self.resize(max(m["min_window"][0], min(self.width(), max_w)),
                    max(m["min_window"][1], min(self.height(), max_h)))
        pos = self.cfg.appearance.get("window_position")
        if pos:
            x = min(max(int(pos[0]), screen.left()),
                    max(screen.left(), screen.right() - 100))
            y = min(max(int(pos[1]), screen.top()),
                    max(screen.top(), screen.bottom() - 60))
            self.move(x, y)
        else:
            self.move(screen.right() - self.width() - 60,
                      max(screen.top() + 12, screen.bottom() - self.height() - 60))

    def save_geometry(self):
        self.cfg.appearance["window_position"] = [self.x(), self.y()]
        self.cfg.appearance["window_size"] = [self.width(), self.height()]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "grip"):
            self.grip.move(self.container.width() - 24, self.container.height() - 24)

    # ---- 开关动画 ----
    def showEvent(self, e):
        super().showEvent(e)
        self.setWindowOpacity(1.0)

    def play_open_animation(self):
        """展开：淡入 + 上移"""
        start_pos = QPoint(self.x(), self.y() + 12)
        self.move(start_pos)
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        pos_anim = QPropertyAnimation(self, b"pos", self)
        pos_anim.setDuration(200)
        pos_anim.setStartValue(start_pos)
        pos_anim.setEndValue(QPoint(self.x(), self.y() - 12))
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        pos_anim.start()
        self._open_anims = (anim, pos_anim)

    def _play_minimize(self):
        """收起：淡出 + 下移，然后发信号"""
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(150)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        pos_anim = QPropertyAnimation(self, b"pos", self)
        pos_anim.setDuration(150)
        pos_anim.setStartValue(QPoint(self.x(), self.y()))
        pos_anim.setEndValue(QPoint(self.x(), self.y() + 10))

        def _done():
            self.setWindowOpacity(1.0)
            self.hide()
            self.minimize_requested.emit()

        anim.finished.connect(_done)
        anim.start()
        pos_anim.start()
        self._close_anims = (anim, pos_anim)

    # 交互控件：这些控件收到鼠标事件时必须放行，否则按钮/输入框点不动。
    _INTERACTIVE = (QPushButton, QComboBox, QTextEdit, QTextBrowser,
                    QLineEdit, QSlider, QScrollBar, QSpinBox, QListWidget,
                    QCheckBox, QMenu)

    def _belongs_to_window(self, w):
        """判断控件是否属于本主窗口子树（排除其它窗口）。"""
        seen = 0
        while w is not None and seen < 64:
            if w is self:
                return True
            if isinstance(w, QWidget) and w.isWindow() and w is not self:
                return False
            parent = w.parent() if hasattr(w, "parent") else None
            if not isinstance(parent, QWidget):
                # 顶层 QObject 没有 QWidget 父亲；只有 self 自身才算本窗口
                return w is self
            w = parent
            seen += 1
        return False

    def _drag_allowed(self, obj, e):
        """标题栏 / 背景空白 / 状态栏 / 气泡空白等均可拖；交互控件放行。

        v13.8：只按「接收事件的控件本身」判定，不再用 widgetAt 在移动中反复
        判断；否则鼠标一滑过按钮就断，表现为「只有特定位置能拖」。
        """
        if not self._belongs_to_window(obj):
            return False
        if obj is getattr(self, "grip", None):
            return False
        if isinstance(obj, self._INTERACTIVE):
            return False
        # QLabel 若允许选中文本，交给它自己处理（气泡正文仍需可选中复制）
        if isinstance(obj, QLabel):
            flags = obj.textInteractionFlags()
            if flags & (Qt.TextSelectableByMouse | Qt.TextBrowserInteraction):
                return False
        return True

    def eventFilter(self, obj, e):
        try:
            return self._event_filter_impl(obj, e)
        except Exception:                       # noqa: BLE001
            return False

    def _event_filter_impl(self, obj, e):
        t = e.type()
        # 缩放手柄优先（保持原有行为）
        if obj is getattr(self, "grip", None):
            if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                self._resize_pos = e.globalPos()
                self._start_geo = self.geometry()
                return True
            if t == QEvent.MouseMove and (e.buttons() & Qt.LeftButton) \
                    and self._resize_pos is not None:
                delta = e.globalPos() - self._resize_pos
                g = self._start_geo
                self.resize(max(self.minimumWidth(), g.width() + delta.x()),
                            max(self.minimumHeight(), g.height() + delta.y()))
                return True
            if t == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton:
                self._resize_pos = None
                return True

        if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            # v13.8：只在「按下」时判定一次并锁定。旧实现在 MouseMove 里反复
            # 用 widgetAt 判定，鼠标滑过按钮/输入框就中断拖拽 → 只能拖特定位置。
            if self._drag_allowed(obj, e):
                self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
                self._drag_active = True
            else:
                self._drag_pos = None
                self._drag_active = False
        elif t == QEvent.MouseMove and (e.buttons() & Qt.LeftButton):
            if self._drag_active and self._drag_pos is not None:
                self.move(e.globalPos() - self._drag_pos)
                return True
        elif t == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton:
            self._drag_pos = None
            self._drag_active = False

        # v13.8：消息气泡右键菜单（复制 / 编辑 / 收藏 / 删除单条）
        if t == QEvent.ContextMenu and obj is not None:
            w = obj if isinstance(obj, (UserBubble, AssistantBubble)) else None
            if w is None and isinstance(obj, QWidget):
                cur = obj
                for _ in range(4):
                    cur = cur.parentWidget() if cur else None
                    if isinstance(cur, (UserBubble, AssistantBubble)):
                        w = cur
                        break
            if w is not None:
                self._bubble_context_menu(w, e.globalPos())
                return True

        if obj is self.messages_widget and t == QEvent.Resize:
            if self._stick_bottom:
                self._do_scroll_bottom()
        return super().eventFilter(obj, e)

    def closeEvent(self, e):
        self.save_geometry()
        self.cfg.save()
        self.closed.emit()
        e.ignore()
        self.hide()

    # ------------------------------------------------------------------
    def _on_send_clicked(self):
        text = self.input.toPlainText().strip()
        attachments = self.attachments()
        if not text and not attachments:
            return
        self.input.clear()
        self.clear_attachments()
        self.send_requested.emit(text, attachments)

    # ------------------------------------------------------------------
    # 滚动：新增消息自动贴底；用户上滚后暂停贴底，滚回底部恢复
    # ------------------------------------------------------------------
    def _scroll_bottom(self):
        self._stick_bottom = True
        self._do_scroll_bottom()

    def _do_scroll_bottom(self):
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_scroll_value(self, value):
        sb = self.scroll.verticalScrollBar()
        self._stick_bottom = value >= sb.maximum() - 40

    def _maybe_scroll(self):
        if self._stick_bottom:
            self._do_scroll_bottom()
