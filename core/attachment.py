# -*- coding: utf-8 -*-
"""附件模块：图片 / 文件 / 截图 → OpenAI 多模态消息。

支持：
- 图片（png/jpg/jpeg/webp/gif/bmp）→ image_url 部件（视觉模型）
- 文本类文件（txt/md/py/js/json/csv/xml/html/log/yaml/yml 等）→ 以文本块嵌入
- PDF → 提取文本嵌入（需 pypdf，未安装时给出提示）
"""
import base64
import os

from PyQt5.QtCore import QBuffer, QIODevice
from PyQt5.QtGui import QImage

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".java", ".c", ".cpp",
    ".h", ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".json", ".jsonl",
    ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".log", ".sql", ".tex",
}

MAX_TEXT_CHARS = 6000        # 文本附件截断长度
MAX_FILE_BYTES = 5 * 1024 * 1024   # 5MB


class Attachment:
    """一个待发送的附件"""

    IMAGE = "image"
    FILE = "file"

    def __init__(self, kind, name, size=0, image=None, text=None, path=""):
        self.kind = kind
        self.name = name
        self.size = size
        self.image = image          # QImage（kind=image）
        self.text = text            # 提取出的文本（kind=file）
        self.path = path

    # ---------------- 展示 ----------------
    def size_str(self):
        if self.size < 1024:
            return "%d B" % self.size
        if self.size < 1024 * 1024:
            return "%.1f KB" % (self.size / 1024.0)
        return "%.1f MB" % (self.size / 1024.0 / 1024.0)

    def thumbnail(self, px=44):
        if self.image is None or self.image.isNull():
            return None
        from PyQt5.QtCore import Qt
        pix = QImage_to_pixmap(self.image)
        return pix.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    # ---------------- 消息部件 ----------------
    def data_url(self):
        """图片 → base64 data URL"""
        if self.image is None or self.image.isNull():
            return ""
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        self.image.save(buf, "PNG")
        b64 = base64.b64encode(bytes(buf.data())).decode("ascii")
        return "data:image/png;base64," + b64

    def as_text_block(self):
        """文件 → 文本块（嵌入用户消息）"""
        if self.kind == self.IMAGE:
            return "[图片：%s]" % self.name
        body = self.text or ""
        if len(body) > MAX_TEXT_CHARS:
            body = body[:MAX_TEXT_CHARS] + "\n……（内容过长已截断）"
        if not body.strip():
            return "📎 附件：%s（%s，未能提取到文本内容）" % (self.name, self.size_str())
        return "📎 附件：%s（%s）\n```\n%s\n```" % (self.name, self.size_str(), body)


def QImage_to_pixmap(image):
    from PyQt5.QtGui import QPixmap
    return QPixmap.fromImage(image)


# ---------------------------------------------------------------------------
def _read_text(path, limit=MAX_FILE_BYTES):
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(limit)
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError as e:
            raise ValueError("读取失败：%s" % e)
    with open(path, "rb") as f:
        return f.read(limit).decode("utf-8", errors="replace")


def _extract_pdf_text(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(path)
    except Exception:  # noqa: BLE001
        return None
    parts, total = [], 0
    for page in reader.pages[:10]:
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        parts.append(t)
        total += len(t)
        if total > MAX_TEXT_CHARS:
            break
    return "\n".join(parts)[:MAX_TEXT_CHARS]


def load_file_attachment(path):
    """把磁盘文件加载为 Attachment（按扩展名路由）"""
    path = str(path)
    if not os.path.isfile(path):
        raise ValueError("文件不存在：%s" % path)
    size = os.path.getsize(path)
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    if size > MAX_FILE_BYTES:
        raise ValueError("文件过大（%s），上限 5MB" % name)

    if ext in IMAGE_EXTS:
        img = QImage(path)
        if img.isNull():
            raise ValueError("无法解析图片：%s" % name)
        return Attachment(Attachment.IMAGE, name, size, image=img, path=path)

    if ext == ".pdf":
        text = _extract_pdf_text(path)
        if text is None:
            raise ValueError("PDF 解析需要 pypdf：pip install pypdf")
        return Attachment(Attachment.FILE, name, size, text=text, path=path)

    if ext in TEXT_EXTS or ext == "":
        return Attachment(Attachment.FILE, name, size,
                          text=_read_text(path), path=path)

    # 未知类型：尝试按文本读取
    try:
        return Attachment(Attachment.FILE, name, size,
                          text=_read_text(path), path=path)
    except ValueError:
        raise ValueError("暂不支持的文件类型：%s" % ext)


def image_attachment(image, name="图片"):
    """从 QImage 创建附件"""
    return Attachment(Attachment.IMAGE, name, 0, image=image)
