# -*- coding: utf-8 -*-
"""Agent Mail —— 本地优先的邮件读取 + 摘要 + 草拟。

设计取向（对应 WorkBuddy 差距清单 #2「Agent Mail / 邮件智能体」）：

- **本地优先**：凭据仅存于本机配置（与现有 ``api_keys`` 同机同权），
  不上传任何第三方服务器；UI 明确提示使用「应用专用密码」。
- **零新依赖**：IMAP 直接走标准库 ``imaplib``，不引入第三方邮件库。
- **可离线测试**：IMAP 交互全部经可注入的 ``imaplib`` 接口，单元测试用
  假对象断言，无需真实邮箱。
- **摘要 / 草拟**：复用现有 ``ChatClient``（OpenAI 兼容）把邮件内容交给模型
  生成要点摘要或草拟回复。

安全提示：配置文件为本地明文（与 ``api_keys`` 同级），请勿在共享/公开机器上
写入真实密码；生产环境建议改用系统钥匙串（后续可扩展）。
"""
import email
from email import policy
import imaplib
import quopri
import re

DEFAULT_FOLDER = "INBOX"
PREVIEW_CHARS = 1400


def _decode_mime(value):
    """把邮件头解码为可读 unicode。

    ``email.message_from_bytes`` 对 8-bit 头会用 surrogateescape 存为 str，
    对 RFC2047 编码头会先解码为正常 unicode。两种情形都能正确还原：
    优先用 surrogateescape 还原（无编码声明的原始字节），失败则原样返回。
    """
    if not value:
        return ""
    try:
        return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except Exception:
        return str(value)


def _body_text(msg):
    """从 email.message 中提取纯文本正文（优先 text/plain）。"""
    if msg.is_multipart():
        plain = None
        for part in msg.walk():
            ct = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ct == "text/plain":
                plain = part
                break
            elif ct == "text/html" and plain is None:
                plain = part
        if plain is None:
            return ""
        try:
            payload = plain.get_payload(decode=True)
        except Exception:
            payload = plain.get_payload()
        charset = plain.get_content_charset() or "utf-8"
        if isinstance(payload, bytes):
            try:
                text = payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                text = payload.decode("utf-8", errors="replace")
        else:
            text = str(payload)
        if plain.get_content_type().lower() == "text/html":
            text = _strip_html(text)
        return text
    try:
        payload = msg.get_payload(decode=True)
    except Exception:
        payload = msg.get_payload()
    if isinstance(payload, bytes):
        charset = msg.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = payload.decode("utf-8", errors="replace")
    else:
        text = str(payload)
    return text


def _strip_html(html):
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|li|tr|h[1-6])>", "\n", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = quopri.decodestring(html.encode("utf-8", "replace")).decode(
        "utf-8", "replace") if False else html
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"&lt;", "<", html)
    html = re.sub(r"&gt;", ">", html)
    return re.sub(r"\n{3,}", "\n\n", html).strip()


def parse_message(uid, raw_bytes):
    """把一封邮件的原始字节解析为便于摘要的字典。"""
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    subject = _decode_mime(msg.get("Subject", ""))
    from_ = _decode_mime(msg.get("From", ""))
    date_ = _decode_mime(msg.get("Date", ""))
    to_ = _decode_mime(msg.get("To", ""))
    body = _body_text(msg)
    preview = body.strip()[:PREVIEW_CHARS]
    return {
        "uid": uid,
        "subject": subject,
        "from": from_,
        "to": to_,
        "date": date_,
        "body": body.strip(),
        "preview": preview,
        "snippet": (preview[:160] + ("…" if len(preview) > 160 else "")),
    }


class MailClient:
    """极简 IMAP 客户端（凭据由调用方从配置读取，本类不负责持久化）。"""

    def __init__(self, host, port, user, password, use_ssl=True,
                 folder=DEFAULT_FOLDER):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.use_ssl = bool(use_ssl)
        self.folder = folder or DEFAULT_FOLDER
        self._conn = None

    def connect(self, imaplib_mod=None):
        mod = imaplib_mod or imaplib
        if self.use_ssl:
            self._conn = mod.IMAP4_SSL(self.host, self.port)
        else:
            self._conn = mod.IMAP4(self.host, self.port)
        self._conn.login(self.user, self.password)
        self._conn.select(self.folder)
        return self._conn

    def fetch_recent(self, limit=10, imaplib_mod=None):
        conn = self.connect(imaplib_mod)
        status, data = conn.search(None, "ALL")
        uids = []
        if data and data[0]:
            uids = data[0].split()
        uids = uids[-max(1, int(limit)):]
        out = []
        for uid in uids:
            try:
                status, msg_data = conn.fetch(uid, "(RFC822)")
            except Exception:
                continue
            if not msg_data:
                continue
            for part in msg_data:
                if isinstance(part, tuple) and len(part) >= 2:
                    raw = part[1]
                    if isinstance(raw, bytes):
                        out.append(parse_message(uid, raw))
                    break
        return out

    def close(self):
        if self._conn is None:
            return
        try:
            self._conn.close()
            self._conn.logout()
        except Exception:
            pass
        self._conn = None

    # 上下文管理器
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _run_summary(client, prompt):
    """用 ChatClient 跑一次摘要，收集正文（忽略思考流）。"""
    chunks = []
    for kind, text in client.chat_stream(
            [{"role": "user", "content": prompt}]):
        if kind == "content":
            chunks.append(text)
    return "".join(chunks).strip()


def summarize_messages(messages, chat_factory, overall=True,
                       max_preview=PREVIEW_CHARS, should_stop=None,
                       on_message=None, on_overall=None):
    """对多封邮件逐封摘要，并可生成总览。

    messages: parse_message 产出的字典列表
    chat_factory: () -> ChatClient
    should_stop: 可选可调用，返回 True 时中断后续摘要
    on_message(message, summary): 每封摘要完成时的回调（用于 UI 流式展示）
    on_overall(text): 总览完成时的回调
    返回 (per_msg, overall_text)，per_msg 为 [(message, summary)]
    """
    per_msg = []
    for m in messages:
        if should_stop and should_stop():
            break
        prompt = (
            "请用 2-4 句话总结这封邮件的核心要点，并标出发件人、主题与"
            "关键诉求或待办：\n\n"
            "发件人：%s\n主题：%s\n时间：%s\n\n正文：\n%s"
            % (m.get("from", ""), m.get("subject", ""), m.get("date", ""),
               m.get("preview", "")[:max_preview]))
        client = chat_factory()
        summary = _run_summary(client, prompt)
        per_msg.append((m, summary))
        if on_message is not None:
            on_message(m, summary)
        if should_stop and should_stop():
            break

    overall_text = ""
    if overall and per_msg:
        if should_stop and should_stop():
            return per_msg, overall_text
        combined = "\n\n".join(
            "【%s】%s" % (m.get("subject", ""), s) for m, s in per_msg)
        prompt = ("以下是近期多封邮件的逐封摘要，请提炼一份总的「重点 + 待办」"
                  "清单，按紧急/重要排序：\n\n%s" % combined)
        client = chat_factory()
        overall_text = _run_summary(client, prompt)
        if on_overall is not None:
            on_overall(overall_text)
    return per_msg, overall_text


def draft_reply(message, chat_factory, tone="礼貌简洁"):
    """根据一封邮件草拟回复（本地优先，模型仅看到本机邮件内容）。"""
    prompt = (
        "请基于下面这封收到的邮件，草拟一封%s的回复邮件。只输出邮件正文，"
        "不要包含主题行与称呼模板以外的多余说明。\n\n"
        "发件人：%s\n主题：%s\n\n正文：\n%s"
        % (tone, message.get("from", ""), message.get("subject", ""),
           message.get("preview", "")[:PREVIEW_CHARS]))
    client = chat_factory()
    return _run_summary(client, prompt)
