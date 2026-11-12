# -*- coding: utf-8 -*-
"""模型库对话框：阿里魔塔 GGUF 模型下载与管理。

三个页签：
- 🔍 发现   全站搜索 ModelScope 模型
- ⭐ 推荐   精选本地模型（按内存友好度排序）
- 📦 已下载  本地 models/ 目录的 GGUF（可启动 llama-server / 删除）

顶部状态条显示 llama.cpp 运行时是否可用（本地推理必需）。
"""
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QTabWidget, QWidget,
                             QScrollArea, QFrame, QComboBox, QProgressBar,
                             QMessageBox, QFileDialog)

from core import modelscope as ms
from core import local_llm
from ui.theme import get_theme, build_qss


# ---------------------------------------------------------------------------
# 后台线程
# ---------------------------------------------------------------------------
class SearchWorker(QThread):
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self._q = query

    def run(self):
        try:
            self.done.emit(ms.search_models(self._q))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class FilesWorker(QThread):
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, model_id, parent=None):
        super().__init__(parent)
        self._id = model_id

    def run(self):
        try:
            self.done.emit(ms.list_gguf_files(self._id))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class DownloadWorker(QThread):
    progress = pyqtSignal(int, int, str)     # done, total, 当前文件名
    finished = pyqtSignal(list)              # 完成的文件路径
    failed = pyqtSignal(str)

    def __init__(self, model_id, files, parent=None):
        super().__init__(parent)
        self._id = model_id
        self._files = files                  # [{name, size}]
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        dest_dir = local_llm.models_dir()
        done_paths, base = [], 0
        total = sum(f["size"] for f in self._files)
        try:
            for f in self._files:
                dest = os.path.join(dest_dir, f["name"])
                if os.path.exists(dest) and \
                        os.path.getsize(dest) >= f["size"]:
                    base += f["size"]
                    done_paths.append(dest)
                    self.progress.emit(base, total, f["name"])
                    continue

                def _cb(d, t, _base=base):
                    self.progress.emit(_base + d, total, f["name"])
                ms.download(self._id, f["name"], dest, on_progress=_cb,
                            should_stop=lambda: self._stop)
                done_paths.append(dest)
                base += f["size"]
            self.finished.emit(done_paths)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# 模型卡片
# ---------------------------------------------------------------------------
class ModelCard(QFrame):
    """一个模型条目：信息 + 下载 / 量化选择 / 进度"""

    download_requested = pyqtSignal(dict)      # {"id","name","files"}
    cancel_requested = pyqtSignal(str)         # model_id

    def __init__(self, entry, theme, parent=None):
        super().__init__(parent)
        self.entry = entry                      # {"id","name","chinese_name","desc","tags"}
        self._theme = theme
        self._files = []
        self._downloading = False
        self.setObjectName("ModelCard")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel(self.entry.get("name") or self.entry["id"])
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        top.addWidget(title)
        top.addStretch(1)
        self.btn = QPushButton("⬇ 下载")
        self.btn.setObjectName("AccentButton")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self._on_download)
        top.addWidget(self.btn)
        lay.addLayout(top)

        meta = self.entry["id"]
        if self.entry.get("chinese_name"):
            meta += " · " + self.entry["chinese_name"]
        if self.entry.get("downloads"):
            meta += " · 下载 %s 次" % self.entry["downloads"]
        meta_lb = QLabel(meta)
        meta_lb.setObjectName("MutedLabel")
        meta_lb.setWordWrap(True)
        lay.addWidget(meta_lb)

        if self.entry.get("desc") or self.entry.get("tags"):
            sub = " · ".join(x for x in (self.entry.get("desc"),
                                         self.entry.get("tags")) if x)
            sub_lb = QLabel(sub)
            sub_lb.setObjectName("MutedLabel")
            sub_lb.setWordWrap(True)
            lay.addWidget(sub_lb)

        # 量化选择区（点击下载后展开）
        self.quant_row = QWidget()
        qr = QHBoxLayout(self.quant_row)
        qr.setContentsMargins(0, 0, 0, 0)
        qr.setSpacing(8)
        self.quant_combo = QComboBox()
        self.quant_combo.setMinimumWidth(260)
        self.quant_combo.currentIndexChanged.connect(self._update_quant_hint)
        qr.addWidget(self.quant_combo)
        self.confirm_btn = QPushButton("开始下载")
        self.confirm_btn.setObjectName("AccentButton")
        self.confirm_btn.setCursor(Qt.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._on_confirm)
        qr.addWidget(self.confirm_btn)
        qr.addStretch(1)
        # 分卷体积提示（多分卷量化显示总体积与分片数）
        self.quant_hint = QLabel("")
        self.quant_hint.setObjectName("MutedLabel")
        self.quant_hint.setWordWrap(True)
        qr.addWidget(self.quant_hint)
        self.quant_row.setVisible(False)
        lay.addWidget(self.quant_row)

        # 进度区（下载中展开）
        self.prog_row = QWidget()
        pr = QVBoxLayout(self.prog_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(4)
        self.prog_bar = QProgressBar()
        self.prog_bar.setTextVisible(True)
        pr.addWidget(self.prog_bar)
        self.prog_lb = QLabel("")
        self.prog_lb.setObjectName("MutedLabel")
        pr.addWidget(self.prog_lb)
        self.prog_row.setVisible(False)
        lay.addWidget(self.prog_row)

        self.setStyleSheet("""
            QFrame#ModelCard {
                background-color: %(input_bg)s;
                border: 1px solid %(border)s;
                border-radius: 12px;
            }
        """ % self._theme)

    # ---------------- 交互 ----------------
    def _on_download(self):
        if self._downloading:
            return
        self.btn.setEnabled(False)
        self.btn.setText("获取文件列表…")
        fw = FilesWorker(self.entry["id"], self)
        fw.done.connect(self._on_files)
        fw.failed.connect(self._on_files_failed)
        fw.start()
        self._fw = fw

    def _on_files(self, files):
        self.btn.setEnabled(True)
        self.btn.setText("⬇ 下载")
        if not files:
            QMessageBox.information(self, "无 GGUF 文件",
                                    "该模型仓库中没有 .gguf 量化文件。")
            return
        self._files = files
        self.quant_combo.blockSignals(True)
        self.quant_combo.clear()
        for f in files:
            self.quant_combo.addItem("%s（%s）" % (f["name"], ms.format_size(f["size"])),
                                     f["name"])
        self.quant_combo.blockSignals(False)
        # 默认选中推荐量化
        pick = ms.pick_quant(files)
        if pick:
            idx = self.quant_combo.findData(pick["name"])
            if idx >= 0:
                self.quant_combo.setCurrentIndex(idx)
        self._update_quant_hint()
        self.quant_row.setVisible(True)

    def _update_quant_hint(self):
        """分卷量化提示：显示分片数与总体积（HR v5 P2-1）"""
        name = self.quant_combo.currentData()
        if not name:
            self.quant_hint.setText("")
            return
        parts = ms.quant_parts(self._files, name)
        if len(parts) > 1:
            total = sum(x["size"] for x in self._files if x["name"] in parts)
            self.quant_hint.setText(
                "⚠ 该量化为 %d 个分卷，需全部分片下载完成（共 %s）后 llama.cpp 才能加载"
                % (len(parts), ms.format_size(total)))
            self.quant_hint.show()
        else:
            self.quant_hint.setText("")
            self.quant_hint.hide()

    def _on_files_failed(self, err):
        self.btn.setEnabled(True)
        self.btn.setText("⬇ 下载")
        QMessageBox.warning(self, "获取文件列表失败", err)

    def _on_confirm(self):
        name = self.quant_combo.currentData()
        if not name:
            return
        parts = ms.quant_parts(self._files, name)
        files = [f for f in self._files if f["name"] in parts]
        self.quant_row.setVisible(False)
        self.download_requested.emit({"id": self.entry["id"],
                                      "name": self.entry.get("name") or "",
                                      "files": files})

    def set_downloading(self, on):
        self._downloading = on
        self.prog_row.setVisible(on)
        self.btn.setVisible(not on)
        if on:
            self.prog_bar.setValue(0)
            self.prog_lb.setText("准备下载…")

    def set_progress(self, done, total, current):
        pct = int(done * 100 / total) if total else 0
        self.prog_bar.setValue(pct)
        self.prog_lb.setText("%s / %s · %s" % (ms.format_size(done),
                                               ms.format_size(total), current))


# ---------------------------------------------------------------------------
# 已下载卡片
# ---------------------------------------------------------------------------
class LocalCard(QFrame):
    """已下载模型：启动服务 / 删除"""

    start_requested = pyqtSignal(str)          # 文件路径
    delete_requested = pyqtSignal(str)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("LocalCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        name_lb = QLabel(item["name"])
        name_lb.setWordWrap(True)
        lay.addWidget(name_lb, 1)
        size_lb = QLabel(ms.format_size(item["size"]))
        size_lb.setObjectName("MutedLabel")
        lay.addWidget(size_lb)
        self.start_btn = QPushButton("▶ 启动服务")
        self.start_btn.setObjectName("AccentButton")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(lambda: self.start_requested.emit(item["path"]))
        lay.addWidget(self.start_btn)
        del_btn = QPushButton("删除")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(item["path"]))
        lay.addWidget(del_btn)

    def mark_running(self):
        self.start_btn.setText("✓ 运行中")
        self.start_btn.setEnabled(False)


# ---------------------------------------------------------------------------
# 主对话框
# ---------------------------------------------------------------------------
class ModelsDialog(QDialog):
    models_changed = pyqtSignal()               # 下载/删除后通知主程序刷新

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.cfg = config
        self._theme = get_theme(config.appearance.get("theme", "light"))
        self._fs = int(config.appearance.get("font_size", 14))
        self.setStyleSheet(build_qss(self._theme, self._fs))
        self.setWindowTitle("模型库 · 阿里魔塔 GGUF")
        self.setMinimumSize(600, 620)
        self._dl_workers = {}                   # model_id -> DownloadWorker
        self._cards = {}                        # model_id -> ModelCard
        self._server = None                     # ServerHandle
        self._build_ui()
        self._refresh_local()
        self._update_runtime_status()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- llama.cpp 运行时状态条 ----
        self.runtime_bar = QFrame()
        self.runtime_bar.setObjectName("AttachChip")
        rb = QHBoxLayout(self.runtime_bar)
        rb.setContentsMargins(12, 8, 12, 8)
        self.runtime_lb = QLabel("")
        self.runtime_lb.setWordWrap(True)
        rb.addWidget(self.runtime_lb, 1)
        root.addWidget(self.runtime_bar)

        # ---- 页签 ----
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # 发现
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setSpacing(8)
        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索魔塔模型，如 Qwen3 GGUF / DeepSeek GGUF")
        self.search_edit.returnPressed.connect(self._on_search)
        row.addWidget(self.search_edit, 1)
        self.search_btn = QPushButton("搜索")
        self.search_btn.setObjectName("AccentButton")
        self.search_btn.clicked.connect(self._on_search)
        row.addWidget(self.search_btn)
        pl.addLayout(row)
        self.search_scroll = self._make_scroll()
        pl.addWidget(self.search_scroll, 1)
        self.search_status = QLabel("输入关键词搜索 ModelScope 全站模型（GGUF 仓库优先）")
        self.search_status.setObjectName("MutedLabel")
        self.search_status.setWordWrap(True)
        pl.addWidget(self.search_status)
        tabs.addTab(page, "🔍 发现")

        # 推荐
        page2 = QWidget()
        pl2 = QVBoxLayout(page2)
        pl2.setSpacing(0)
        rec_scroll = self._make_scroll()
        rec_box = rec_scroll.widget().layout()
        for entry in ms.RECOMMENDED:
            card = ModelCard(entry, self._theme)
            card.download_requested.connect(self._start_download)
            rec_box.addWidget(card)
            self._cards[entry["id"]] = card
        rec_box.addStretch(1)
        pl2.addWidget(rec_scroll)
        tabs.addTab(page2, "⭐ 推荐")

        # 已下载
        page3 = QWidget()
        pl3 = QVBoxLayout(page3)
        pl3.setSpacing(8)
        local_scroll = self._make_scroll()
        self.local_box = local_scroll.widget().layout()
        pl3.addWidget(local_scroll, 1)
        path_row = QHBoxLayout()
        self.path_lb = QLabel(local_llm.models_dir())
        self.path_lb.setObjectName("MutedLabel")
        self.path_lb.setWordWrap(True)
        path_row.addWidget(self.path_lb, 1)
        open_btn = QPushButton("打开目录")
        open_btn.clicked.connect(self._open_dir)
        path_row.addWidget(open_btn)
        pl3.addLayout(path_row)
        tabs.addTab(page3, "📦 已下载")

        # ---- 底部按钮 ----
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _make_scroll(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        box = QVBoxLayout(inner)
        box.setSpacing(8)
        box.setContentsMargins(2, 2, 2, 2)
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------------
    def apply_theme(self, theme_name=None, font_size=None):
        if theme_name:
            self._theme = get_theme(theme_name)
        if font_size:
            self._fs = int(font_size)
        self.setStyleSheet(build_qss(self._theme, self._fs))

    def _update_runtime_status(self):
        exe = local_llm.find_llama_server()
        if exe:
            self.runtime_lb.setText(
                "✓ llama.cpp 已就绪：%s\n下载 GGUF 后可「启动服务」，"
                "然后在模型下拉框选择「魔塔本地模型」。" % exe)
        else:
            self.runtime_lb.setText(
                "✗ 未检测到 llama-server。本地推理需要 llama.cpp：\n"
                "1. 到 github.com/ggml-org/llama.cpp/releases 下载对应平台预编译包；\n"
                "2. 解压后将 llama-server 放入 PATH，或放到 %s。" % local_llm.bin_dir())

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def _on_search(self):
        q = self.search_edit.text().strip()
        if not q:
            return
        self.search_btn.setEnabled(False)
        self.search_status.setText("正在搜索「%s」…" % q)
        self._sw = SearchWorker(q, self)
        self._sw.done.connect(self._on_search_done)
        self._sw.failed.connect(self._on_search_failed)
        self._sw.start()

    def _on_search_done(self, models):
        self.search_btn.setEnabled(True)
        box = self.search_scroll.widget().layout()
        while box.count():
            item = box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not models:
            self.search_status.setText("没有找到相关模型，换个关键词试试。")
            return
        self.search_status.setText("找到 %d 个结果（GGUF 量化仓库优先）：" % len(models))
        for entry in models:
            card = ModelCard(entry, self._theme)
            card.download_requested.connect(self._start_download)
            box.addWidget(card)
            self._cards[entry["id"]] = card
        box.addStretch(1)

    def _on_search_failed(self, err):
        self.search_btn.setEnabled(True)
        self.search_status.setText("搜索失败：%s" % err)

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------
    def _start_download(self, req):
        model_id = req["id"]
        card = self._cards.get(model_id)
        if card is None:
            return
        total = sum(f["size"] for f in req["files"])
        if total > 30 * 1024 ** 3:
            QMessageBox.warning(self, "文件过大",
                                "该量化合计 %s，请确认磁盘空间充足。"
                                % ms.format_size(total))
        worker = DownloadWorker(model_id, req["files"], self)
        worker.progress.connect(lambda d, t, c: card.set_progress(d, t, c))
        worker.finished.connect(lambda paths: self._on_download_done(model_id, paths))
        worker.failed.connect(lambda err: self._on_download_failed(model_id, err))
        self._dl_workers[model_id] = worker
        card.set_downloading(True)
        worker.start()

    def _on_download_done(self, model_id, paths):
        self._dl_workers.pop(model_id, None)
        card = self._cards.get(model_id)
        if card is not None:
            card.set_downloading(False)
        self._refresh_local()
        self.models_changed.emit()
        QMessageBox.information(
            self, "下载完成",
            "%s 已下载到本地。\n\n切到「已下载」页签点「启动服务」，"
            "就绪后即可在聊天窗模型下拉框选择「魔塔本地模型」。" % model_id)

    def _on_download_failed(self, model_id, err):
        self._dl_workers.pop(model_id, None)
        card = self._cards.get(model_id)
        if card is not None:
            card.set_downloading(False)
        if "取消" not in str(err):
            QMessageBox.warning(self, "下载失败", err)

    # ------------------------------------------------------------------
    # 已下载管理
    # ------------------------------------------------------------------
    def _refresh_local(self):
        while self.local_box.count():
            item = self.local_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        items = local_llm.list_local_gguf()
        if not items:
            empty = QLabel("还没有下载模型。\n到「⭐ 推荐」或「🔍 发现」页签下载 GGUF 模型。")
            empty.setObjectName("MutedLabel")
            empty.setWordWrap(True)
            self.local_box.addWidget(empty)
        for it in items:
            card = LocalCard(it)
            card.start_requested.connect(self._start_server)
            card.delete_requested.connect(self._delete_model)
            self.local_box.addWidget(card)
        self.local_box.addStretch(1)
        self._update_runtime_status()

    def _start_server(self, path):
        exe = local_llm.find_llama_server()
        if not exe:
            QMessageBox.warning(
                self, "缺少 llama.cpp",
                "未检测到 llama-server，请先安装 llama.cpp（见顶部说明）。")
            return
        if local_llm.is_running():
            QMessageBox.information(self, "服务已在运行",
                                    "本地 llama-server 已在运行，直接到模型下拉框"
                                    "选择「魔塔本地模型」即可。")
            return
        try:
            self._server = local_llm.start_server(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "启动失败", str(e))
            return
        QMessageBox.information(
            self, "服务已启动",
            "模型已在本地加载（OpenAI 兼容 :8080）。\n\n"
            "到聊天窗右上角模型下拉框选择「魔塔本地模型 · GGUF」即可对话。")
        self._refresh_local()
        self.models_changed.emit()

    def _delete_model(self, path):
        name = os.path.basename(path)
        if QMessageBox.question(
                self, "删除模型", "确定删除 %s？\n（文件将移入回收站/彻底删除，需重新下载）"
                % name) != QMessageBox.Yes:
            return
        if local_llm.delete_gguf(path):
            self._refresh_local()
            self.models_changed.emit()
        else:
            QMessageBox.warning(self, "删除失败", "无法删除该文件。")

    def _open_dir(self):
        path = local_llm.models_dir()
        try:
            if sys_platform_open(path):
                return
        except Exception:
            pass
        QFileDialog.getOpenFileName(self, "模型目录", path)   # 兜底：让用户看到路径

    # ------------------------------------------------------------------
    def closeEvent(self, e):
        # 下载中的任务询问是否取消
        if self._dl_workers:
            if QMessageBox.question(
                    self, "关闭模型库",
                    "还有 %d 个下载任务正在进行，关闭将取消下载。确定关闭？"
                    % len(self._dl_workers)) != QMessageBox.Yes:
                e.ignore()
                return
            for w in list(self._dl_workers.values()):
                w.stop()
        super().closeEvent(e)

    def reject(self):
        if self._dl_workers:
            for w in list(self._dl_workers.values()):
                w.stop()
        super().reject()


def sys_platform_open(path):
    """跨平台打开文件管理器"""
    import subprocess
    import sys
    if sys.platform.startswith("win"):
        os.startfile(path)                      # noqa: B009
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return True
