# -*- coding: utf-8 -*-
"""网关仪表盘（Gateway Dashboard）—— 所有模型通道的统一观测台。

布局：
    顶部    品牌标题 + 全局指标（今日请求 / 成功率 / 平均延迟 / Token）
    左栏    服务商列表（液态卡片：状态灯 · 今日请求 · 平均延迟 · Key 数 · 预算预警）
    右上    选中服务商详情：60 分钟延迟折线 + 密钥池管理（轮询/退避）
            + 每日 token 预算（80% 预警 / 100% 告警）
    右下    实时请求日志流（成功绿 / 失败红，最新在上）
    底部    路由策略（自动 / 最低延迟 / 手动）+ 健康检查 + 工作原理说明

v7：健康检查并行化（8 并发 + 实时进度，最坏 76s → 约 12s）；
新增每日 token 预算消耗条与预警。

动效：GlowOrb 流动光斑背景、卡片级联展开、MetricRing 扫过、Sparkline
绘制动画、NumberRoll 数字滚动、StatusDot 呼吸灯。
"""
import time

from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QProgressBar, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from core.config import PROVIDERS
from core.gateway import (GatewayStats, KeyPool, ROUTE_POLICIES,
                          check_providers_parallel,
                          budget_status, load_budgets, save_budgets,
                          _fmt_tokens)
from ui import liquid as LQ
from ui import theme as T


# ---------------------------------------------------------------------------
# 后台健康检查线程（v7：并行探活，8 并发；最坏 19 家 × 4s ≈ 76s → 约 12s）
# ---------------------------------------------------------------------------
class _HealthWorker(QThread):
    progress = pyqtSignal(str, str, str)      # provider, status, detail
    tick = pyqtSignal(int, int)              # checked, total（进度）
    finished_all = pyqtSignal()

    def __init__(self, keys=None):
        super().__init__()
        self._keys = keys or {}
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        items = []
        web_like = []
        for pkey, pinfo in PROVIDERS.items():
            if (pinfo or {}).get("web"):
                # 网页版：浏览器 harness 不适用 HTTP 探活，标记为特殊状态
                web_like.append(pkey)
                continue
            if pkey == "custom":
                continue
            items.append((pkey, pinfo, self._keys.get(pkey, "")))
        total = len(PROVIDERS)
        for pkey in web_like:
            self.progress.emit(pkey, "web", "浏览器接入（登录态持久化）")
            self.tick.emit(len(web_like), total)

        def _on_done(pkey, status, detail, done, tot):
            self.progress.emit(pkey, status, detail)
            self.tick.emit(len(web_like) + done, total)

        check_providers_parallel(items, timeout=4, max_workers=8,
                                 on_done=_on_done,
                                 should_stop=lambda: self._stop)
        self.finished_all.emit()


def _mask_key(key):
    k = key or ""
    if len(k) <= 8:
        return k[:2] + "****"
    return k[:6] + "****" + k[-4:]


def _fmt_ms(ms):
    ms = int(ms or 0)
    if ms <= 0:
        return "—"
    if ms >= 1000:
        return "%.1fs" % (ms / 1000.0)
    return "%dms" % ms


class _ProviderCard(LQ.LiquidCard):
    """左栏服务商卡片"""
    clicked = pyqtSignal(str)

    def __init__(self, pkey, parent=None):
        super().__init__(parent)
        self.pkey = pkey
        self._selected = False
        self.dot = LQ.StatusDot(self, 9)
        self.name = QLabel(PROVIDERS.get(pkey, {}).get("name", pkey))
        self.name.setObjectName("GlassTitle")
        self.sub = QLabel("")
        self.sub.setObjectName("ChipText")
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.dot)
        head.addWidget(self.name, 1)
        self.layout().addLayout(head)
        self.layout().addWidget(self.sub)
        self._apply_style()

    def _apply_style(self):
        self.name.setStyleSheet(
            "font-size: 13px; background: transparent;"
            + ("color: %s;" % self._accent() if self._selected else ""))

    def _accent(self):
        return getattr(self, "_theme_color", "#0eaf7e")

    def apply_theme(self, t):
        super().apply_theme(t)
        self._theme_color = t.get("accent", "#0eaf7e")
        self._apply_style()

    def set_selected(self, on):
        self._selected = bool(on)
        self.animate_glow(0.55 if on else 0.0, LQ.T.DUR_FAST)
        self._apply_style()

    def mousePressEvent(self, e):
        self.clicked.emit(self.pkey)
        super().mousePressEvent(e)


class GatewayDialog(QDialog):
    """模型网关仪表盘"""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("模型网关 · Gateway")
        self.resize(940, 680)
        self.setMinimumSize(820, 600)
        self._theme = T.get_theme(cfg.appearance.get("theme", "light")
                                  if hasattr(cfg, "appearance") else "light")
        self.stats = GatewayStats.instance()
        self.keys = KeyPool(cfg)
        self._health = {}                # provider -> (status, detail)
        self._selected = None
        self._cards = {}
        self._worker = None

        self.setStyleSheet(LQ.liquid_dialog_qss(self._theme))
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._build_ui()
        self._refresh_all()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_live)
        self._timer.start(3000)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)

        host = QWidget(self)
        host.setObjectName("GlassHost")
        host_lay = QVBoxLayout(host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(0)
        root.addWidget(host)

        # 光斑背景（最底层）
        self.orb = LQ.GlowOrb(host)
        self.orb.lower()

        # ---- 顶部标题 ----
        title_row = QHBoxLayout()
        title_row.setContentsMargins(20, 16, 20, 0)
        title = QLabel("🌐 模型网关")
        title.setObjectName("GlassTitle")
        title.setStyleSheet("font-size: 17px;")
        sub = QLabel("统一观测与管理所有模型通道 —— 密钥轮询 · 失败退避 · 实时用量")
        sub.setObjectName("ChipText")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(sub)
        host_lay.addLayout(title_row)

        # ---- 全局指标 ----
        metrics = QHBoxLayout()
        metrics.setContentsMargins(20, 12, 20, 4)
        metrics.setSpacing(12)
        self.ring_success = LQ.MetricRing(self, 78, 7)
        self.roll_today = LQ.NumberRoll(self, "0")
        self.roll_today.setObjectName("MetricValue")
        self.roll_latency = LQ.NumberRoll(self, "0")
        self.roll_latency.setObjectName("MetricValue")
        self.roll_tokens = LQ.NumberRoll(self, "0")
        self.roll_tokens.setObjectName("MetricValue")
        self.roll_today.set_fmt(lambda v: "%d" % round(v))
        self.roll_latency.set_fmt(lambda v: _fmt_ms(v))
        self.roll_tokens.set_fmt(lambda v: _fmt_tokens(round(v)))
        metrics.addLayout(self._metric_block(self.ring_success, "成功率", ""))
        metrics.addLayout(self._metric_block(self.roll_today, "今日请求", ""))
        metrics.addLayout(self._metric_block(self.roll_latency, "平均延迟", ""))
        metrics.addLayout(self._metric_block(self.roll_tokens, "累计 Token", ""))
        metrics.addStretch(1)
        self.btn_health = QPushButton("🩺 健康检查")
        self.btn_health.clicked.connect(self._run_health_check)
        metrics.addWidget(self.btn_health, 0, Qt.AlignTop)
        host_lay.addLayout(metrics)

        # ---- 主体：左右分栏 ----
        body = QHBoxLayout()
        body.setContentsMargins(14, 8, 14, 8)
        body.setSpacing(12)

        # 左：服务商列表
        left = LQ.LiquidGlass(self, T.RADIUS_M)
        left.layout().setContentsMargins(12, 12, 12, 12)
        cap = QLabel("服务商通道")
        cap.setObjectName("MetricLabel")
        left.layout().addWidget(cap)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.provider_list = QVBoxLayout(inner)
        self.provider_list.setContentsMargins(0, 0, 0, 0)
        self.provider_list.setSpacing(8)
        scroll.setWidget(inner)
        left.layout().addWidget(scroll, 1)
        left.setFixedWidth(268)
        body.addWidget(left)

        # 右：上下两区
        right = QVBoxLayout()
        right.setSpacing(12)

        # 右上：详情
        self.detail = LQ.LiquidGlass(self, T.RADIUS_M)
        dl = self.detail.layout()
        self.detail_title = QLabel("服务商详情")
        self.detail_title.setObjectName("GlassTitle")
        dl.addWidget(self.detail_title)
        self.spark = LQ.Sparkline(self, 110)
        dl.addWidget(self.spark)
        keys_row = QHBoxLayout()
        keys_row.setSpacing(8)
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("添加 API Key（多 Key 自动轮询、失败自动退避）")
        self.btn_add_key = QPushButton("添加")
        self.btn_add_key.setObjectName("AccentButton")
        self.btn_add_key.clicked.connect(self._on_add_key)
        keys_row.addWidget(self.key_input, 1)
        keys_row.addWidget(self.btn_add_key)
        dl.addLayout(keys_row)
        self.key_list = QListWidget()
        self.key_list.setMaximumHeight(120)
        dl.addWidget(self.key_list)
        self.frozen_label = QLabel("")
        self.frozen_label.setObjectName("ChipText")
        self.frozen_label.setWordWrap(True)
        dl.addWidget(self.frozen_label)
        # v7：每日 token 预算（超过 80% 预警、100% 告警）
        budget_row = QHBoxLayout()
        budget_row.setSpacing(8)
        self.budget_input = QLineEdit()
        self.budget_input.setPlaceholderText("每日 token 预算（如 100000，留空清除）")
        self.btn_set_budget = QPushButton("设预算")
        self.btn_set_budget.setObjectName("AccentButton")
        self.btn_set_budget.clicked.connect(self._on_set_budget)
        budget_row.addWidget(self.budget_input, 1)
        budget_row.addWidget(self.btn_set_budget)
        dl.addLayout(budget_row)
        self.budget_bar = QProgressBar()
        self.budget_bar.setFixedHeight(10)
        self.budget_bar.setTextVisible(False)
        self.budget_bar.setObjectName("BudgetBar")
        dl.addWidget(self.budget_bar)
        self.budget_label = QLabel("")
        self.budget_label.setObjectName("ChipText")
        self.budget_label.setWordWrap(True)
        dl.addWidget(self.budget_label)
        right.addWidget(self.detail, 3)

        # 右下：日志流
        self.logbox = LQ.LiquidGlass(self, T.RADIUS_M)
        ll = self.logbox.layout()
        log_cap = QLabel("实时请求日志")
        log_cap.setObjectName("MetricLabel")
        ll.addWidget(log_cap)
        self.log_list = QListWidget()
        self.log_list.setAlternatingRowColors(False)
        ll.addWidget(self.log_list, 1)
        right.addWidget(self.logbox, 2)

        body.addLayout(right, 1)
        host_lay.addLayout(body, 1)

        # ---- 底部：路由策略 + 说明 ----
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 4, 20, 14)
        foot.setSpacing(8)
        foot.addWidget(QLabel("路由策略："))
        self.route_box = QComboBox()
        for k, v in ROUTE_POLICIES.items():
            self.route_box.addItem(v, k)
        cur = (self.cfg.data.get("gateway") or {}).get("route_policy", "auto")
        idx = self.route_box.findData(cur)
        if idx >= 0:
            self.route_box.setCurrentIndex(idx)
        self.route_box.currentIndexChanged.connect(self._on_route_changed)
        foot.addWidget(self.route_box)
        self.route_hint = QLabel("")
        self.route_hint.setObjectName("ChipText")
        foot.addWidget(self.route_hint, 1)
        host_lay.addLayout(foot)
        self._update_route_hint()

    def _metric_block(self, widget, label, sub=""):
        box = QVBoxLayout()
        box.setSpacing(2)
        row = QHBoxLayout()
        row.addWidget(widget)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(label_wrap(label))
        if sub:
            texts.addWidget(label_wrap(sub))
        row.addLayout(texts)
        row.addStretch(1)
        box.addLayout(row)
        return box

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------
    def _refresh_all(self):
        self._refresh_metrics()
        self._refresh_providers()
        self._refresh_detail()
        self._refresh_logs()

    def _refresh_live(self):
        self._refresh_metrics()
        self._refresh_logs()
        self._refresh_providers()
        if self._selected:
            self._refresh_detail(keep_spark=True)

    def _refresh_metrics(self):
        ov = self.stats.overall()
        self.roll_today.set_target(ov["today"])
        self.roll_latency.set_target(ov["avg_latency"])
        self.roll_tokens.set_target(ov["tokens"])
        self.ring_success.set_value(ov["success_rate"],
                                    "%.0f%%" % (ov["success_rate"] * 100),
                                    "%d 次调用" % ov["requests"])

    def _refresh_providers(self):
        summary = self.stats.summary()
        budgets = budget_status(budgets=load_budgets())
        for pkey in PROVIDERS:
            if pkey not in self._cards:
                card = _ProviderCard(pkey, self)
                card.clicked.connect(self._on_select_provider)
                self._cards[pkey] = card
                self.provider_list.addWidget(card)
                # 级联展开动效（对话框可能在延时到达前已关闭，
                # liquid._val_anim 已对已删除 widget 防御，这里双保险）
                def _glow(c=card):
                    try:
                        c.animate_glow(0.25, LQ.T.DUR_BASE)
                    except RuntimeError:
                        pass
                QTimer.singleShot(40 * len(self._cards), _glow)
            d = summary.get(pkey, {})
            health = self._health.get(pkey)
            if health:
                status = health[0]
            elif d.get("requests"):
                status = "online" if d.get("success_rate", 0) > 0.5 else "limited"
            else:
                status = "unconfigured"
            card = self._cards[pkey]
            card.dot.set_status("busy" if status == "web" else status)
            budget_tag = ""
            bst = budgets.get(pkey)
            if bst and bst.get("budget"):
                if bst["level"] == "over":
                    budget_tag = " · ⛔ 预算 %d%%" % int(bst["ratio"] * 100)
                elif bst["level"] == "warn":
                    budget_tag = " · ⚠ 预算 %d%%" % int(bst["ratio"] * 100)
            if PROVIDERS.get(pkey, {}).get("web"):
                # 网页版通道：不用「Key 数」语义（它没有 Key，只有登录态）
                card.sub.setText("浏览器接入 · 登录态持久化 · 免 API Key"
                                 + budget_tag)
            else:
                nkeys = len([k for k, en, av in self.keys.list_keys(pkey)
                             if k])
                card.sub.setText(
                    "今日 %d 次 · 均延 %s · %d 个 Key"
                    % (d.get("today", 0), _fmt_ms(d.get("avg_latency", 0)),
                       nkeys) + budget_tag)
            card.set_selected(pkey == self._selected)
        self.provider_list.addStretch(1)

    def _refresh_detail(self, keep_spark=False):
        if not self._selected:
            self.detail_title.setText("点击左侧服务商查看详情")
            self.spark.set_data([])
            self.key_list.clear()
            self.frozen_label.setText("")
            self.budget_input.clear()
            self.budget_bar.setValue(0)
            self.budget_label.setText("")
            return
        pkey = self._selected
        pinfo = PROVIDERS.get(pkey, {})
        d = self.stats.summary().get(pkey, {})
        health = self._health.get(pkey)
        status = health[0] if health else ("online" if d.get("requests")
                                           else "unconfigured")
        self.detail_title.setText("%s —— %s" % (
            pinfo.get("name", pkey),
            {"online": "● 在线", "limited": "● 受限",
             "error": "● 异常", "unconfigured": "● 未配置",
             "web": "● 浏览器接入"}.get(status, "● 未知")))
        if not keep_spark:
            series = self.stats.series(minutes=60, buckets=48)
            self.spark.set_data(series, metric="lat")
        # 密钥池
        self.key_list.clear()
        for k, enabled, avail in self.keys.list_keys(pkey):
            if not k:
                continue
            state = "✓ 启用" if enabled else "⏸ 已停用"
            if enabled and not avail:
                state = "❄ 冷却中"
            item = QListWidgetItem("%s   %s" % (_mask_key(k), state))
            item.setToolTip(k)
            btn_del = QPushButton("删除")
            btn_del.setObjectName("DangerButton")
            btn_del.setFixedWidth(52)
            btn_del.clicked.connect(
                lambda _=False, kk=k: self._on_remove_key(pkey, kk))
            btn_toggle = QPushButton("停用" if enabled else "启用")
            btn_toggle.setFixedWidth(52)
            btn_toggle.clicked.connect(
                lambda _=False, kk=k: self._on_toggle_key(pkey, kk))
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(4, 0, 4, 0)
            row.addWidget(item_label(_mask_key(k)), 1)
            row.addWidget(item_label(state))
            row.addWidget(btn_toggle)
            row.addWidget(btn_del)
            self.key_list.addItem(item)
            self.key_list.setItemWidget(item, w)
        frozen = self.keys.frozen_info(pkey)
        if frozen:
            self.frozen_label.setText(
                "❄ %d 个 Key 处于失败退避冷却（%s 秒后自动恢复）"
                % (len(frozen), ", ".join(str(s) for _, s in frozen)))
        else:
            self.frozen_label.setText("")
        # v7：预算展示（输入框未被聚焦时才回填，避免打断用户输入）
        if not self.budget_input.hasFocus():
            cur_b = load_budgets().get(pkey, 0)
            self.budget_input.setText(str(cur_b) if cur_b else "")
            self.budget_input.setPlaceholderText(
                "每日 token 预算（如 100000，留空清除）")
        # v7.1（HR P1-1）：统计口径明示——仅本助手请求的本地估算值
        self.budget_input.setToolTip(
            "口径：仅统计本助手发起的请求，本地估算 token（CJK 1 字 ≈ 1 token）；"
            "官网/其他客户端的用量不计入。超支不会拦截对话，仅作提醒。")
        bst = budget_status(budgets=load_budgets()).get(pkey)
        if bst and bst.get("budget"):
            pct = min(100, int(bst["ratio"] * 100))
            self.budget_bar.setValue(pct)
            if bst["level"] == "over":
                self.budget_bar.setStyleSheet(
                    "QProgressBar{background:rgba(255,255,255,0.08);"
                    "border-radius:5px;}"
                    "QProgressBar::chunk{background:#e5484d;border-radius:5px;}")
                self.budget_label.setText(
                    "⛔ 今日已用 %s / %s token（%d%%）—— 已超每日预算"
                    "（不会拦截对话，仅作提醒 · 仅统计本助手请求）"
                    % (_fmt_tokens(bst["used"]), _fmt_tokens(bst["budget"]),
                       int(bst["ratio"] * 100)))
            elif bst["level"] == "warn":
                self.budget_bar.setStyleSheet(
                    "QProgressBar{background:rgba(255,255,255,0.08);"
                    "border-radius:5px;}"
                    "QProgressBar::chunk{background:#f5a623;border-radius:5px;}")
                self.budget_label.setText(
                    "⚠ 今日已用 %s / %s token（%d%%）—— 接近每日预算"
                    "（不会拦截对话，仅作提醒 · 仅统计本助手请求）"
                    % (_fmt_tokens(bst["used"]), _fmt_tokens(bst["budget"]),
                       int(bst["ratio"] * 100)))
            else:
                self.budget_bar.setStyleSheet(
                    "QProgressBar{background:rgba(255,255,255,0.08);"
                    "border-radius:5px;}"
                    "QProgressBar::chunk{background:#30a46c;border-radius:5px;}")
                self.budget_label.setText(
                    "今日已用 %s / %s token（%d%%）· 仅统计本助手请求"
                    % (_fmt_tokens(bst["used"]), _fmt_tokens(bst["budget"]),
                       int(bst["ratio"] * 100)))
        else:
            self.budget_bar.setValue(0)
            self.budget_bar.setStyleSheet(
                "QProgressBar{background:rgba(255,255,255,0.08);"
                "border-radius:5px;}")
            self.budget_label.setText("未设预算 · 设为 0 或留空清除")

    def _on_set_budget(self):
        pkey = self._selected
        if not pkey:
            return
        text = (self.budget_input.text() or "").strip()
        budgets = load_budgets()
        try:
            val = int(float(text)) if text else 0
        except ValueError:
            self.budget_label.setText("⚠ 预算需为数字（token 数）")
            return
        if val > 0:
            budgets[pkey] = val
            self.budget_label.setText("已设置每日预算 %s token"
                                      "（仅统计本助手请求，不会拦截对话）"
                                      % _fmt_tokens(val))
        else:
            budgets.pop(pkey, None)
            self.budget_label.setText("已清除预算")
        save_budgets(budgets)
        self._refresh_providers()

    def _refresh_logs(self):
        recs = self.stats.records(limit=60)
        self.log_list.clear()
        for r in recs:
            ts = time.strftime("%H:%M:%S", time.localtime(r.get("ts", 0)))
            toks = r.get("tokens", 0)
            toks_s = ("%.1fK" % (toks / 1000.0)) if toks >= 1000 else str(toks)
            text = "%s  %s · %s · %s · %s tok" % (
                ts, r.get("provider", "?"), r.get("model", "?"),
                _fmt_ms(r.get("latency", 0)), toks_s)
            if not r.get("ok") and r.get("error"):
                text += "  ⚠ %s" % r["error"]
            item = QListWidgetItem(text)
            if r.get("ok"):
                item.setForeground(QColor(self._theme["text"]))
            else:
                item.setForeground(QColor(self._theme["danger"]))
                item.setToolTip(r.get("error", ""))
            self.log_list.addItem(item)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_select_provider(self, pkey):
        self._selected = pkey
        self._refresh_providers()
        self._refresh_detail()

    def _on_add_key(self):
        if not self._selected:
            return
        key = self.key_input.text().strip()
        if not key:
            return
        if self.keys.add_key(self._selected, key):
            self.key_input.clear()
            self._refresh_detail()
            self._refresh_providers()

    def _on_remove_key(self, pkey, key):
        self.keys.remove_key(pkey, key)
        self._refresh_detail()
        self._refresh_providers()

    def _on_toggle_key(self, pkey, key):
        cur = dict((k, en) for k, en, _ in self.keys.list_keys(pkey))
        self.keys.set_enabled(pkey, key, not cur.get(key, True))
        self._refresh_detail()
        self._refresh_providers()

    def _on_route_changed(self, _idx):
        policy = self.route_box.currentData()
        gw = self.cfg.data.setdefault("gateway", {})
        gw["route_policy"] = policy
        try:
            self.cfg.save()
        except Exception:                          # noqa: BLE001
            pass
        self._update_route_hint()

    def _update_route_hint(self):
        policy = self.route_box.currentData()
        hints = {
            "auto": "使用当前设置中选择的服务商",
            "fastest": "按网关统计数据，自动选择平均延迟最低的服务商",
            "manual": "固定使用左侧选中的服务商（作为下次请求目标）",
        }
        self.route_hint.setText(hints.get(policy, ""))

    def _run_health_check(self):
        if self._worker is not None and self._worker.isRunning():
            return
        keys = {}
        for pkey in PROVIDERS:
            k = self.keys.next_key(pkey)
            if k:
                keys[pkey] = k
        self.btn_health.setEnabled(False)
        self.btn_health.setText("🩺 检查中 0/%d…" % len(PROVIDERS))
        self._health = {}
        self._refresh_providers()
        self._worker = _HealthWorker(keys)
        self._worker.progress.connect(self._on_health_progress)
        self._worker.tick.connect(self._on_health_tick)
        self._worker.finished_all.connect(self._on_health_done)
        self._worker.start()

    def _on_health_tick(self, done, total):
        self.btn_health.setText("🩺 检查中 %d/%d…" % (done, total))

    def _on_health_progress(self, pkey, status, detail):
        self._health[pkey] = (status, detail)
        if pkey in self._cards:
            self._cards[pkey].dot.set_status(
                "busy" if status == "web" else status)
            self._cards[pkey].dot.setToolTip(detail)

    def _on_health_done(self):
        self.btn_health.setEnabled(True)
        self.btn_health.setText("🩺 健康检查")
        self._refresh_providers()
        if self._selected:
            self._refresh_detail(keep_spark=True)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def apply_theme(self, t):
        self._theme = t or self._theme
        self.setStyleSheet(LQ.liquid_dialog_qss(self._theme))
        self.orb.apply_theme(self._theme)
        for w in self.findChildren(LQ.LiquidGlass):
            w.apply_theme(self._theme)
        for w in self.findChildren(LQ.Sparkline):
            w.apply_theme(self._theme)
        for w in self.findChildren(LQ.MetricRing):
            w.apply_theme(self._theme)
        for w in self.findChildren(LQ.StatusDot):
            w.apply_theme(self._theme)
        for w in self.findChildren(LQ.NumberRoll):
            w.apply_theme(self._theme)
        self._refresh_logs()
        if self._selected:
            self._refresh_detail(keep_spark=True)

    def resizeEvent(self, e):
        self.orb.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(e)

    def closeEvent(self, e):
        self._timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        super().closeEvent(e)


def label_wrap(text):
    lb = QLabel(text)
    lb.setObjectName("MetricLabel")
    return lb


def item_label(text):
    lb = QLabel(text)
    lb.setObjectName("ChipText")
    return lb
