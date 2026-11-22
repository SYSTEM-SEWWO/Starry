# -*- coding: utf-8 -*-
"""本地 AI 工作室 —— LocModel 公开功能规格的完整复刻界面。

规格来源：https://locmodel.com/ 与 /changelog.html（v3.6.0）
页面：概览/硬件 · 推理引擎 · 模型管理 · 本地画图 · 视频生成 ·
      Agent · 作品库 · 画布

设计约束（吸取前几轮教训）：
  * 窗口本身是普通 QDialog，由全局玻璃钩子统一套圆角，不自己做装饰；
  * 不用 QMessageBox（在部分平台/玻璃父窗口下会 native 崩溃），
    所有反馈走窗口底部状态栏；
  * 耗时操作用普通 threading.Thread + QTimer 轮询状态字典，
    不用 QThread（实测与 QDialog 生命周期纠缠会崩溃）。
"""
import os
import threading

from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QPixmap
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                             QFormLayout, QGraphicsItem, QGraphicsPixmapItem,
                             QGraphicsScene, QGraphicsView, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QProgressBar,
                             QPushButton, QSpinBox, QSplitter, QStackedWidget,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from core import (agentfs, artworks, enginemgr, genstudio, ggufmgr,
                  hwprobe, runconfig, tiering)

_NAV = [
    ("🖥", "硬件体检", "显卡 / CPU / 内存 / 模型盘与可运行模型推荐"),
    ("⚙", "推理引擎", "llama.cpp / 画图 / 视频 / 对口型引擎安装与导入"),
    ("📦", "模型管理", "GGUF 导入、HuggingFace 搜索、显存分层与本地服务"),
    ("🖼", "本地画图", "Z-Image / FLUX，中文提示词，画幅/步数/种子可调"),
    ("🎬", "视频生成", "Wan2.2 文生视频 / 首帧续写，480P / 720P"),
    ("🤖", "Agent", "指定文件夹，生成计划、读写文件、执行命令并验证"),
    ("🗂", "作品库", "生成的图片与视频，标签、搜索、打开与导出"),
    ("🎨", "画布", "把作品图片放到画布上自由排布"),
]


class LocalStudioDialog(QDialog):
    """本地 AI 工作室主窗口。"""

    def __init__(self, cfg, assistant=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.app = assistant
        self.setWindowTitle("🌐 本地 AI 工作室")
        self.resize(1040, 760)
        self._state = {}                 # 后台任务状态（线程写，QTimer 读）
        self._bars = {}                  # 各任务的进度条（轮询时更新）
        self._timers = []
        self._plan = None
        self._hw = None
        self._server_handle = None
        self._build_ui()
        self._start_poller()
        self._refresh_all()

    # ------------------------------------------------------------------
    # 框架
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("🌐 本地 AI 工作室")
        title.setStyleSheet("font-size:17px;font-weight:700;")
        head.addWidget(title)
        sub = QLabel("复刻 LocModel 公开功能规格 · 全部本地运行，数据不出门")
        sub.setObjectName("MutedLabel")
        head.addWidget(sub)
        head.addStretch(1)
        root.addLayout(head)

        body = QSplitter(Qt.Horizontal)
        self.nav = QListWidget()
        self.nav.setFixedWidth(190)
        for icon, name, _desc in _NAV:
            self.nav.addItem(QListWidgetItem("%s  %s" % (icon, name)))
        self.nav.setCurrentRow(0)
        body.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.pages = [
            self._page_hardware(), self._page_engines(), self._page_models(),
            self._page_image(), self._page_video(), self._page_agent(),
            self._page_artworks(), self._page_canvas(),
        ]
        for p in self.pages:
            self.stack.addWidget(p)
        body.addWidget(self.stack)
        body.setStretchFactor(1, 1)
        root.addWidget(body, 1)

        foot = QHBoxLayout()
        self.status = QLabel("就绪")
        self.status.setObjectName("MutedLabel")
        self.status.setWordWrap(True)
        foot.addWidget(self.status, 1)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        foot.addWidget(close)
        root.addLayout(foot)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.currentRowChanged.connect(
            lambda i: self._set_status(_NAV[i][2] if 0 <= i < len(_NAV) else ""))

    def _set_status(self, text):
        self.status.setText(str(text)[:400])

    def _start_poller(self):
        """QTimer 轮询后台状态字典，避免跨线程直接调用 Qt 控件。"""
        t = QTimer(self)
        t.setInterval(250)
        t.timeout.connect(self._poll_tasks)
        t.start()
        self._timers.append(t)

    def _poll_tasks(self):
        for key, st in list(self._state.items()):
            if st.get("ui_progress") is not None and key in self._bars:
                self._bars[key].setValue(int(st.get("ui_progress", 0)))
            if st.get("done") and not st.get("ui_seen"):
                st["ui_seen"] = True
                self._set_status(st.get("message", "任务完成"))
                cb = st.get("on_done")
                if cb:
                    try:
                        cb(st)
                    except Exception as e:          # noqa: BLE001
                        self._set_status("回调失败：%s" % e)

    def _run_bg(self, key, fn, label="", on_done=None):
        """普通 Python 线程执行 fn(state)，UI 只通过轮询读取。"""
        st = {"done": False, "message": label or "执行中…", "ui_seen": False,
              "ui_progress": None, "result": None, "on_done": on_done}
        self._state[key] = st

        def wrapper():
            try:
                result = fn(st)
                st["result"] = result
                st["message"] = (result.get("error") or result.get("message")
                                 or "%s 完成" % label) if isinstance(result, dict) \
                    else "%s 完成" % label
            except Exception as e:                 # noqa: BLE001
                st["message"] = "%s 失败：%s" % (label, str(e)[:200])
                st["result"] = {"ok": False, "error": str(e)[:200]}
            finally:
                st["done"] = True

        threading.Thread(target=wrapper, daemon=True).start()
        self._set_status(label or "执行中…")
        return st

    def _refresh_all(self):
        self._refresh_hw()
        self._refresh_engines()
        self._refresh_models()
        self._refresh_artworks()

    # ------------------------------------------------------------------
    # 1) 硬件体检
    # ------------------------------------------------------------------
    def _page_hardware(self):
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        btn = QPushButton("🔍 重新检测硬件")
        btn.clicked.connect(self._refresh_hw)
        bar.addWidget(btn)
        bar.addStretch(1)
        v.addLayout(bar)
        self.hw_text = QPlainTextEdit()
        self.hw_text.setReadOnly(True)
        v.addWidget(QLabel("硬件体检（真实探测，不含臆造参数）"))
        v.addWidget(self.hw_text, 1)
        v.addWidget(QLabel("可运行模型推荐（速度为启发式估算，非实测）"))
        self.hw_table = QTableWidget(0, 5)
        self.hw_table.setHorizontalHeaderLabels(
            ["模型", "体积 GB", "量化", "预计 tok/s", "适配"])
        self.hw_table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.hw_table, 1)
        return w

    def _refresh_hw(self):
        self._set_status("正在检测硬件…")
        try:
            self._hw = hwprobe.probe()
            self.hw_text.setPlainText(hwprobe.format_hw(self._hw))
            recs = hwprobe.recommend(self._hw, ggufmgr.builtin_catalog())
            self.hw_table.setRowCount(len(recs))
            for i, m in enumerate(recs):
                vals = [m["name"], "%.1f" % m.get("size_gb", 0),
                        m.get("quant", ""), "%.1f" % m.get("tps", 0),
                        "%s（首载约 %ss）" % (m.get("fit"), m.get("first_load"))]
                for j, val in enumerate(vals):
                    self.hw_table.setItem(i, j, QTableWidgetItem(str(val)))
            self._set_status("硬件体检完成：%d 个显卡、%d 种后端、%d 条推荐" % (
                len(self._hw["gpus"]), len(self._hw["backends"]), len(recs)))
        except Exception as e:                     # noqa: BLE001
            self._set_status("检测失败：%s" % e)

    # ------------------------------------------------------------------
    # 2) 推理引擎
    # ------------------------------------------------------------------
    def _page_engines(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.engine_table = QTableWidget(0, 4)
        self.engine_table.setHorizontalHeaderLabels(
            ["引擎", "状态", "后端", "说明"])
        self.engine_table.horizontalHeader().setStretchLastSection(True)
        self.engine_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.engine_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.engine_table.clicked.connect(lambda *_: self._on_engine_selected())
        v.addWidget(self.engine_table, 2)

        form = QFormLayout()
        self.engine_backend = QComboBox()
        self.engine_backend.addItems(["CUDA", "Vulkan", "Intel", "CPU"])
        form.addRow("下载后端", self.engine_backend)
        row = QHBoxLayout()
        for label, slot in (("⬇ 下载安装", self._download_engine),
                            ("📂 导入本地 ZIP", self._import_engine),
                            ("🗑 移除", self._remove_engine)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        form.addRow("", row)
        self.engine_bar = QProgressBar()
        form.addRow("进度", self.engine_bar)
        self.engine_note = QPlainTextEdit()
        self.engine_note.setReadOnly(True)
        self.engine_note.setMaximumHeight(110)
        form.addRow("说明", self.engine_note)
        v.addLayout(form)
        self._bars["engine"] = self.engine_bar
        return w

    def _refresh_engines(self):
        rows = enginemgr.status()
        self.engine_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["name"], "✅ 已安装" if r["installed"] else "未安装",
                    "/".join(r["backends"]), r["desc"]]
            for j, val in enumerate(vals):
                self.engine_table.setItem(i, j, QTableWidgetItem(str(val)))
        self.engine_table.selectRow(0)
        self._on_engine_selected()

    def _selected_engine(self):
        row = self.engine_table.currentRow()
        rows = enginemgr.status()
        return rows[row]["kind"] if 0 <= row < len(rows) else None

    def _on_engine_selected(self):
        kind = self._selected_engine()
        if not kind:
            return
        spec = enginemgr.ENGINES.get(kind, {})
        self.engine_note.setPlainText(
            spec.get("desc", "") + "\n" +
            ("公开官方构建，可直接下载。" if spec.get("official") else
             "该引擎非公开直链：请在设置 local_studio.engine_urls 填写来源，"
             "或使用「导入本地 ZIP」离线安装。"))
        self.engine_backend.clear()
        self.engine_backend.addItems(spec.get("backends", ["CPU"]))

    def _download_engine(self):
        kind = self._selected_engine()
        if not kind:
            self._set_status("请先选择一个引擎")
            return
        backend = self.engine_backend.currentText()
        url, source = enginemgr.engine_url(kind, backend, self.cfg)
        if not url:
            self._set_status(source)
            return

        def work(st):
            def progress(done, total, pct, speed, eta):
                st["ui_progress"] = pct
                st["message"] = "%s %.1f%% · %s MB/s · 剩余 %ss（%s）" % (
                    backend, pct, speed, eta, source)
            return enginemgr.download(kind, backend, self.cfg,
                                      progress=progress)

        self._run_bg("engine", work, "正在下载 %s · %s" % (kind, backend),
                     lambda st: self._refresh_engines())

    def _import_engine(self):
        kind = self._selected_engine()
        if not kind:
            self._set_status("请先选择引擎")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "导入本地引擎 ZIP", "", "ZIP 安装包 (*.zip)")
        if not path:
            return
        result = enginemgr.import_zip(kind, path)
        self._set_status(result.get("error") or result.get("warning")
                         or "引擎导入成功：%s" % result.get("path"))
        self._refresh_engines()

    def _remove_engine(self):
        kind = self._selected_engine()
        if not kind:
            return
        ok = enginemgr.remove_engine(kind)
        self._set_status("已移除引擎" if ok else "移除失败或引擎未安装")
        self._refresh_engines()

    # ------------------------------------------------------------------
    # 3) 模型管理
    # ------------------------------------------------------------------
    def _page_models(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("已安装 GGUF（版本 / 大小 / 量化 / 运行状态）"))
        self.model_table = QTableWidget(0, 6)
        self.model_table.setHorizontalHeaderLabels(
            ["模型", "大小 GB", "量化", "参数 B", "上下文", "状态"])
        self.model_table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.model_table, 2)
        bar = QHBoxLayout()
        for label, slot in (("📂 导入 GGUF", self._import_gguf),
                            ("🔄 刷新", self._refresh_models),
                            ("🗑 删除所选", self._delete_model)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch(1)
        v.addLayout(bar)

        g = QGroupBox("HuggingFace 在线搜索 / 下载")
        f = QFormLayout(g)
        sr = QHBoxLayout()
        self.hf_query = QLineEdit()
        self.hf_query.setPlaceholderText("搜索 GGUF 模型，如 Qwen2.5 7B")
        sr.addWidget(self.hf_query, 1)
        b = QPushButton("🔍 搜索")
        b.clicked.connect(self._hf_search)
        sr.addWidget(b)
        f.addRow("", sr)
        self.hf_list = QListWidget()
        self.hf_list.setMaximumHeight(100)
        f.addRow("结果", self.hf_list)
        dr = QHBoxLayout()
        b = QPushButton("⬇ 下载所选文件")
        b.clicked.connect(self._hf_download)
        dr.addWidget(b)
        self.hf_bar = QProgressBar()
        dr.addWidget(self.hf_bar, 1)
        f.addRow("", dr)
        v.addWidget(g)
        self._bars["hf"] = self.hf_bar

        g2 = QGroupBox("显存智能分层 + 本地服务（8K / 16K / 32K / 64K · 思考 · 局域网）")
        f2 = QFormLayout(g2)
        rr = QHBoxLayout()
        self.tier_size = QLineEdit("17")
        rr.addWidget(self.tier_size)
        self.tier_moe = QCheckBox("MoE 专家模型")
        rr.addWidget(self.tier_moe)
        b = QPushButton("生成分层方案")
        b.clicked.connect(self._make_tier)
        rr.addWidget(b)
        f2.addRow("模型体积 GB", rr)
        self.tier_text = QPlainTextEdit()
        self.tier_text.setReadOnly(True)
        self.tier_text.setMaximumHeight(150)
        f2.addRow("方案", self.tier_text)

        r2 = QHBoxLayout()
        self.ctx_combo = QComboBox()
        for n in runconfig.CONTEXT_OPTIONS:
            self.ctx_combo.addItem(runconfig.CONTEXT_LABELS[n], n)
        self.ctx_combo.setCurrentIndex(0)
        r2.addWidget(QLabel("上下文"))
        r2.addWidget(self.ctx_combo)
        self.think_check = QCheckBox("思考模式")
        r2.addWidget(self.think_check)
        self.lan_check = QCheckBox("局域网访问")
        r2.addWidget(self.lan_check)
        f2.addRow("运行参数", r2)

        r3 = QHBoxLayout()
        for label, slot in (("▶ 启动服务", self._start_server),
                            ("⏹ 停止服务", self._stop_server),
                            ("📊 服务状态", self._server_status)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            r3.addWidget(b)
        f2.addRow("", r3)
        self.server_text = QPlainTextEdit()
        self.server_text.setReadOnly(True)
        self.server_text.setMaximumHeight(90)
        f2.addRow("状态", self.server_text)
        v.addWidget(g2)
        return w

    def _refresh_models(self):
        rows = ggufmgr.scan_models()
        self.model_table.setRowCount(len(rows))
        for i, m in enumerate(rows):
            vals = [m.get("display_name", m["name"]), "%.2f" % m["size_gb"],
                    m.get("quant", ""), m.get("params_b", ""),
                    m.get("ctx", ""), "运行中" if m.get("running") else "已安装"]
            for j, val in enumerate(vals):
                self.model_table.setItem(i, j, QTableWidgetItem(str(val)))

    def _import_gguf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入本地 GGUF（不转换、不上传）", "",
            "GGUF 模型 (*.gguf)")
        if not path:
            return
        r = ggufmgr.import_file(path)
        self._set_status(r.get("error") or "已导入：%s" % r.get("path"))
        self._refresh_models()

    def _delete_model(self):
        row = self.model_table.currentRow()
        rows = ggufmgr.scan_models(include_meta=False)
        if not (0 <= row < len(rows)):
            self._set_status("请先选择模型")
            return
        # 内联二次确认（不用 QMessageBox）
        if getattr(self, "_pending_model_delete", None) != row:
            self._pending_model_delete = row
            self._set_status("再点一次「删除所选」确认删除：%s" % rows[row]["name"])
            QTimer.singleShot(6000, lambda: setattr(
                self, "_pending_model_delete", None))
            return
        self._pending_model_delete = None
        ok = ggufmgr.delete_model(rows[row]["path"])
        self._set_status("已删除" if ok else "删除失败")
        self._refresh_models()

    def _hf_search(self):
        q = self.hf_query.text().strip()
        if not q:
            self._set_status("请输入搜索关键词")
            return
        self._set_status("正在搜索 HuggingFace…")

        def work(st):
            r = ggufmgr.hf_search(q)
            st["items"] = r.get("items", [])
            return r

        def done(st):
            self.hf_list.clear()
            for m in st.get("items", []):
                for f in m.get("files", [])[:2]:
                    self.hf_list.addItem("%s :: %s" % (m["id"], f))
            r = st.get("result") or {}
            self._set_status(r.get("error") or "找到 %d 个模型" %
                             len(st.get("items", [])))

        self._run_bg("hf", work, "搜索中…", done)

    def _hf_download(self):
        item = self.hf_list.currentItem()
        if not item:
            self._set_status("请先选择要下载的模型文件")
            return
        repo, filename = item.text().split(" :: ", 1)

        def work(st):
            def progress(done, total, pct):
                st["ui_progress"] = pct
                st["message"] = "下载 %s %.1f%%" % (filename, pct)
            return ggufmgr.hf_download(repo, filename, progress=progress)

        self._run_bg("hf_dl", work, "开始下载…",
                     lambda st: self._refresh_models())

    def _make_tier(self):
        try:
            size = float(self.tier_size.text())
        except ValueError:
            self._set_status("请输入有效的模型体积（GB）")
            return
        try:
            r = tiering.plan(size, self._hw or hwprobe.probe(),
                             moe=self.tier_moe.isChecked(),
                             ctx_tokens=int(self.ctx_combo.currentData()))
            self.tier_text.setPlainText(tiering.format_plan(r))
            self._set_status("分层方案已生成（估算，非实测）")
        except Exception as e:                     # noqa: BLE001
            self._set_status("生成方案失败：%s" % e)

    def _selected_model_path(self):
        row = self.model_table.currentRow()
        rows = ggufmgr.scan_models(include_meta=False)
        return rows[row]["path"] if 0 <= row < len(rows) else None

    def _start_server(self):
        path = self._selected_model_path()
        if not path:
            self._set_status("请先在列表中选择一个已安装模型")
            return
        ctx = int(self.ctx_combo.currentData())
        lan = self.lan_check.isChecked()
        r = runconfig.start(path, ctx=ctx, lan=lan)
        self._server_handle = r
        self.server_text.setPlainText(runconfig.format_status())
        self._set_status("本地服务已启动 · %s · %s" % (
            runconfig.CONTEXT_LABELS.get(ctx, ctx),
            "局域网可访问" if lan else "仅本机"))

    def _stop_server(self):
        # 通过 local_llm 的进程管理关闭（保留句柄缓存）
        try:
            h = getattr(self, "_server_handle", None)
            if h is None:
                self._set_status("当前会话未持有服务句柄，请在助手主程序停止服务")
                return
            h.stop()
            self.server_text.setPlainText("本地服务已停止")
            self._set_status("本地服务已停止")
        except Exception as e:                     # noqa: BLE001
            self._set_status("停止失败：%s" % e)

    def _server_status(self):
        self.server_text.setPlainText(runconfig.format_status())
        self._set_status("已刷新服务状态")

    # ------------------------------------------------------------------
    # 4) 本地画图
    # ------------------------------------------------------------------
    def _page_image(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.img_prompt = QPlainTextEdit()
        self.img_prompt.setPlaceholderText(
            "用中文描述主体、场景、风格与光线（本机推理，不上传）")
        self.img_prompt.setMaximumHeight(90)
        f.addRow("提示词", self.img_prompt)
        row = QHBoxLayout()
        self.img_model = QComboBox()
        self.img_model.addItems(genstudio.IMAGE_MODELS)
        row.addWidget(self.img_model)
        self.img_aspect = QComboBox()
        self.img_aspect.addItems(list(genstudio.ASPECTS))
        row.addWidget(self.img_aspect)
        f.addRow("模型 / 画幅", row)
        row2 = QHBoxLayout()
        for lbl, attr, val in (("步数", "img_steps", 20), ("张数", "img_count", 4)):
            sp = QSpinBox()
            sp.setRange(1, 100 if attr == "img_steps" else 8)
            sp.setValue(val)
            setattr(self, attr, sp)
            row2.addWidget(QLabel(lbl))
            row2.addWidget(sp)
        self.img_seed = QLineEdit("-1（随机，可复现请填固定值）")
        row2.addWidget(QLabel("种子"))
        row2.addWidget(self.img_seed)
        f.addRow("参数", row2)
        r3 = QHBoxLayout()
        self.img_ref = QLineEdit()
        self.img_ref.setReadOnly(True)
        r3.addWidget(self.img_ref, 1)
        b = QPushButton("选择参考图")
        b.clicked.connect(lambda: self._pick_file(self.img_ref, "参考图", "图片 (*.png *.jpg *.jpeg *.webp)"))
        r3.addWidget(b)
        f.addRow("参考图重绘", r3)
        self.img_negative = QLineEdit()
        f.addRow("反向提示词", self.img_negative)
        b = QPushButton("🖼 本地生成")
        b.setObjectName("PrimaryAction")
        b.clicked.connect(self._gen_image)
        f.addRow("", b)
        self.img_bar = QProgressBar()
        f.addRow("进度", self.img_bar)
        v.addLayout(f)
        self.img_out = QPlainTextEdit()
        self.img_out.setReadOnly(True)
        v.addWidget(QLabel("生成结果（自动进入作品库）"))
        v.addWidget(self.img_out, 1)
        self._bars["image"] = self.img_bar
        return w

    def _pick_file(self, edit, title, filt):
        path, _ = QFileDialog.getOpenFileName(self, title, "", filt)
        if path:
            edit.setText(path)

    def _gen_image(self):
        t = genstudio.new_image_task(
            self.img_prompt.toPlainText(),
            model=self.img_model.currentText(),
            aspect=self.img_aspect.currentText(),
            steps=self.img_steps.value(), count=self.img_count.value(),
            seed=self.img_seed.text(), reference=self.img_ref.text(),
            negative=self.img_negative.text(), cfg=self.cfg)
        if not t["prompt"]:
            self._set_status("请先输入提示词")
            return

        def work(st):
            def progress(pct, msg):
                st["ui_progress"] = pct
                st["message"] = msg
            return genstudio.run_task(t, self.cfg, progress=progress)

        def done(st):
            r = st.get("result") or {}
            if r.get("ok"):
                for p in r["outputs"]:
                    artworks.save_tags(p, ["生成", t["model"]], t["prompt"])
                self.img_out.appendPlainText(
                    "✅ %s · %.1fs → %s" % (
                        genstudio.format_task(t), r["elapsed"],
                        ", ".join(r["outputs"])))
                self._refresh_artworks()
            else:
                self.img_out.appendPlainText("❌ %s" % r.get("error", ""))

        self._run_bg("image", work, "正在本地生成图片…", done)

    # ------------------------------------------------------------------
    # 5) 视频生成
    # ------------------------------------------------------------------
    def _page_video(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.vid_prompt = QPlainTextEdit()
        self.vid_prompt.setPlaceholderText("描述主体、动作、镜头和氛围")
        self.vid_prompt.setMaximumHeight(80)
        f.addRow("提示词", self.vid_prompt)
        row = QHBoxLayout()
        self.vid_model = QComboBox()
        self.vid_model.addItems(genstudio.VIDEO_MODELS)
        row.addWidget(self.vid_model)
        self.vid_spec = QComboBox()
        self.vid_spec.addItems(list(genstudio.VIDEO_SPECS))
        row.addWidget(self.vid_spec)
        f.addRow("模型 / 画幅", row)
        row2 = QHBoxLayout()
        self.vid_duration = QSpinBox()
        self.vid_duration.setRange(1, 30)
        self.vid_duration.setValue(5)
        self.vid_steps = QSpinBox()
        self.vid_steps.setRange(1, 100)
        self.vid_steps.setValue(25)
        self.vid_seed = QLineEdit("-1")
        for lbl, wd in (("时长", self.vid_duration), ("步数", self.vid_steps)):
            row2.addWidget(QLabel(lbl))
            row2.addWidget(wd)
        row2.addWidget(QLabel("种子"))
        row2.addWidget(self.vid_seed)
        f.addRow("参数", row2)
        r3 = QHBoxLayout()
        self.vid_frame = QLineEdit()
        self.vid_frame.setReadOnly(True)
        r3.addWidget(self.vid_frame, 1)
        b = QPushButton("选择首帧图")
        b.clicked.connect(lambda: self._pick_file(
            self.vid_frame, "首帧图", "图片 (*.png *.jpg *.jpeg)"))
        r3.addWidget(b)
        f.addRow("首帧续写", r3)
        self.vid_negative = QLineEdit()
        f.addRow("反向提示词", self.vid_negative)
        self.vid_lipsync = QComboBox()
        self.vid_lipsync.addItem("（关闭对口型）", "")
        self.vid_lipsync.addItems(genstudio.LIPSYNC_VERSIONS)
        f.addRow("对口型 v3.6", self.vid_lipsync)
        b = QPushButton("🎬 本地生成视频")
        b.setObjectName("PrimaryAction")
        b.clicked.connect(self._gen_video)
        f.addRow("", b)
        self.vid_bar = QProgressBar()
        f.addRow("进度 / 耗时", self.vid_bar)
        v.addLayout(f)
        self.vid_out = QPlainTextEdit()
        self.vid_out.setReadOnly(True)
        v.addWidget(self.vid_out, 1)
        self._bars["video"] = self.vid_bar
        return w

    def _gen_video(self):
        ls = self.vid_lipsync.currentData()
        t = genstudio.new_video_task(
            self.vid_prompt.toPlainText(), self.vid_model.currentText(),
            self.vid_spec.currentText(), self.vid_frame.text(),
            self.vid_duration.value(), self.vid_steps.value(),
            self.vid_seed.text(), self.vid_negative.text(),
            lipsync_version=ls, cfg=self.cfg)
        if not t["prompt"] and not t.get("first_frame"):
            self._set_status("请输入提示词或选择首帧图")
            return

        def work(st):
            def progress(pct, msg):
                st["ui_progress"] = pct
                st["message"] = msg
            return genstudio.run_task(t, self.cfg, progress=progress)

        def done(st):
            r = st.get("result") or {}
            if r.get("ok"):
                for p in r["outputs"]:
                    artworks.save_tags(p, ["生成", t["model"]], t["prompt"])
                self.vid_out.appendPlainText(
                    "✅ %s · %.1fs → %s" % (
                        genstudio.format_task(t), r["elapsed"],
                        ", ".join(r["outputs"])))
                self._refresh_artworks()
            else:
                self.vid_out.appendPlainText("❌ %s" % r.get("error", ""))

        self._run_bg("video", work, "正在本地生成视频…", done)

    # ------------------------------------------------------------------
    # 6) Agent
    # ------------------------------------------------------------------
    def _page_agent(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        row = QHBoxLayout()
        self.agent_root = QLineEdit()
        self.agent_root.setReadOnly(True)
        row.addWidget(self.agent_root, 1)
        b = QPushButton("选择工作文件夹")
        b.clicked.connect(self._pick_agent_root)
        row.addWidget(b)
        f.addRow("工作文件夹", row)
        self.agent_goal = QLineEdit()
        self.agent_goal.setPlaceholderText("交代一句任务目标")
        f.addRow("目标", self.agent_goal)
        row2 = QHBoxLayout()
        self.agent_step = QLineEdit()
        self.agent_step.setPlaceholderText("例如：写入 result.txt")
        row2.addWidget(self.agent_step, 1)
        for label, slot in (("＋ 添加步骤", self._agent_add_step),
                            ("▶ 执行下一步", self._agent_run_step),
                            ("✓ 验证输出", self._agent_verify)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row2.addWidget(b)
        f.addRow("计划", row2)
        v.addLayout(f)
        self.agent_view = QPlainTextEdit()
        self.agent_view.setReadOnly(True)
        v.addWidget(self.agent_view, 1)
        v.addWidget(QLabel(
            "安全：仅在所选文件夹内读写；删除 / 移动 / 访问外部内容会先请求确认，"
            "不会自动执行。"))
        return w

    def _pick_agent_root(self):
        path = QFileDialog.getExistingDirectory(self, "选择 Agent 工作文件夹")
        if path:
            self.agent_root.setText(agentfs.set_root(path))
            self._plan = agentfs.Plan(self.agent_goal.text(), self.agent_root.text())
            self.agent_view.setPlainText("工作目录：%s" % path)

    def _agent_plan(self):
        if self._plan is None or self._plan.root != self.agent_root.text():
            self._plan = agentfs.Plan(self.agent_goal.text(), self.agent_root.text())
        if self.agent_goal.text() and not self._plan.goal:
            self._plan.goal = self.agent_goal.text()
        return self._plan

    def _agent_add_step(self):
        text = self.agent_step.text().strip()
        if not text:
            self._set_status("请输入步骤内容")
            return
        self._agent_plan().add(text)
        self.agent_step.clear()
        self.agent_view.setPlainText(self._agent_plan().summary())

    def _agent_run_step(self):
        plan = self._agent_plan()
        root = self.agent_root.text()
        if not root:
            self._set_status("请先选择工作文件夹")
            return
        pending = next((s for s in plan.steps if s["status"] == "pending"), None)
        if not pending:
            self._set_status("没有待执行步骤，请先添加")
            return
        plan.start(pending["id"])
        # 支持内联语法：write:文件名=内容 / mkdir:目录 / run:命令
        text = pending["text"]
        try:
            if text.startswith("write:"):
                body = text[6:]
                name, _, content = body.partition("=")
                result = agentfs.write(root, name.strip(), content)
                plan.finish(pending["id"], "已写入 %s" % result, True)
            elif text.startswith("mkdir:"):
                result = agentfs.mkdir(root, text[6:].strip())
                plan.finish(pending["id"], "已创建 %s" % result, True)
            elif text.startswith("run:"):
                r = agentfs.run_command(root, text[4:].strip())
                if r.get("need_confirm"):
                    plan.finish(pending["id"], "需要确认：" + r.get("error", ""), False)
                    self._set_status(r.get("error", ""))
                else:
                    plan.finish(pending["id"],
                                (r.get("output") or r.get("error") or "")[:300],
                                bool(r.get("ok")))
            elif text.startswith("read:"):
                plan.finish(pending["id"], agentfs.read(root, text[5:].strip())[:500], True)
            else:
                # 普通描述步骤：交给本地模型在助手主流程执行；此处标记完成说明
                plan.finish(pending["id"],
                            "描述性步骤，可通过助手对话让本地模型执行：%s" % text,
                            True)
        except Exception as e:                     # noqa: BLE001
            plan.finish(pending["id"], "失败：%s" % e, False)
        self.agent_view.setPlainText(plan.summary())
        self._set_status("步骤 #%d 已执行 · 进度 %d%%" % (
            pending["id"], plan.progress()))

    def _agent_verify(self):
        plan = self._agent_plan()
        root = self.agent_root.text()
        if not root:
            self._set_status("请先选择工作文件夹")
            return
        # 从 write: 步骤推导应存在的文件，做到「完成后验证输出」
        expect = []
        for s in plan.steps:
            if s["text"].startswith("write:"):
                expect.append(s["text"][6:].partition("=")[0].strip())
        r = agentfs.verify(root, expect_files=expect)
        plan.finished = True
        self.agent_view.setPlainText(
            plan.summary() + "\n\n验证：\n" +
            "\n".join("  %s %s" % ("✓" if c["ok"] else "✕", c["check"])
                      for c in r["checks"]))
        self._set_status("验证%s" % ("通过" if r["ok"] else "未通过"))

    # ------------------------------------------------------------------
    # 7) 作品库
    # ------------------------------------------------------------------
    def _page_artworks(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.art_query = QLineEdit()
        self.art_query.setPlaceholderText("按文件名 / 标签 / 提示词搜索")
        self.art_query.returnPressed.connect(self._refresh_artworks)
        row.addWidget(self.art_query, 1)
        for label, slot in (("🔍", self._refresh_artworks),
                            ("📂 打开", self._open_artwork),
                            ("📤 导出", self._export_artworks),
                            ("🗑 删除", self._delete_artwork)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        self.art_list = QListWidget()
        self.art_list.doubleClicked.connect(self._open_artwork)
        v.addWidget(self.art_list, 2)
        self.art_preview = QLabel("预览")
        self.art_preview.setAlignment(Qt.AlignCenter)
        self.art_preview.setMinimumHeight(180)
        self.art_list.currentRowChanged.connect(self._preview_artwork)
        v.addWidget(self.art_preview, 1)
        return w

    def _art_rows(self):
        return artworks.search(self.art_query.text().strip())

    def _refresh_artworks(self):
        rows = self._art_rows()
        self.art_list.clear()
        for r in rows:
            icon = "🖼" if r["kind"] == "image" else "🎬"
            self.art_list.addItem("%s %s · %.1f KB · %s" % (
                icon, r["name"], r["size"] / 1024.0,
                ",".join(r["tags"]) or "-"))
        self._set_status("作品库：%d 项" % len(rows))

    def _art_path(self):
        rows = self._art_rows()
        i = self.art_list.currentRow()
        return rows[i]["path"] if 0 <= i < len(rows) else None

    def _preview_artwork(self, row):
        path = self._art_path()
        if not path:
            return
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            pix = QPixmap(path)
            if not pix.isNull():
                self.art_preview.setPixmap(
                    pix.scaled(self.art_preview.size(),
                               Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self.art_preview.setText("🎬 视频：%s" % os.path.basename(path))

    def _open_artwork(self):
        path = self._art_path()
        if not path:
            self._set_status("请先选择作品")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _export_artworks(self):
        rows = self._art_rows()
        selected = [self.art_list.item(i) for i in range(self.art_list.count())
                    if self.art_list.item(i).isSelected()]
        if not selected:
            selected = [self.art_list.currentItem()]
        paths = [rows[i]["path"] for i in range(len(rows))
                 if self.art_list.item(i) in selected and i < len(rows)]
        if not paths:
            self._set_status("请先选择要导出的作品")
            return
        dest = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not dest:
            return
        r = artworks.export(paths, dest)
        self._set_status("已导出 %d 项到 %s" % (r["ok"], dest))

    def _delete_artwork(self):
        path = self._art_path()
        if not path:
            self._set_status("请先选择作品")
            return
        if getattr(self, "_pending_art_delete", None) != path:
            self._pending_art_delete = path
            self._set_status("再点一次「删除」确认移入回收站：%s" %
                             os.path.basename(path))
            QTimer.singleShot(6000, lambda: setattr(
                self, "_pending_art_delete", None))
            return
        self._pending_art_delete = None
        r = artworks.delete(path)
        self._set_status(r.get("error") or ("已移入回收站" if r.get("trashed")
                                            else "已删除"))
        self._refresh_artworks()

    # ------------------------------------------------------------------
    # 8) 画布
    # ------------------------------------------------------------------
    def _page_canvas(self):
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        b = QPushButton("＋ 添加选中作品到画布")
        b.clicked.connect(self._canvas_add)
        bar.addWidget(b)
        b = QPushButton("↺ 清空画布")
        b.clicked.connect(lambda: self.canvas_scene.clear())
        bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(QLabel("双击作品库图片可直接打开；画布内可拖动排列"))
        v.addLayout(bar)
        self.canvas_scene = QGraphicsScene(self)
        self.canvas_view = QGraphicsView(self.canvas_scene)
        v.addWidget(self.canvas_view, 1)
        return w

    def _canvas_add(self):
        path = self._art_path()
        if not path or not path.lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            self._set_status("请先在作品库选择一张图片")
            return
        pix = QPixmap(path)
        if pix.isNull():
            self._set_status("图片无法加载")
            return
        item = QGraphicsPixmapItem(pix.scaled(
            320, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        item.setFlag(QGraphicsItem.ItemIsMovable, True)
        item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        n = len(self.canvas_scene.items())
        item.setPos(30 + (n % 4) * 340, 30 + (n // 4) * 340)
        self.canvas_scene.addItem(item)
        self._set_status("已添加到画布：%s" % os.path.basename(path))

    def closeEvent(self, e):
        for t in self._timers:
            try:
                t.stop()
            except Exception:
                pass
        super().closeEvent(e)
