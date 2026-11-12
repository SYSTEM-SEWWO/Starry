# -*- coding: utf-8 -*-
"""浏览器 Harness —— 把网页版大模型对话页「套上马具」，包装成流式客户端。

思路（对齐 WorkBuddy 式浏览器接入）：
    不逆向任何私有 API，而是用 Playwright 驱动真实浏览器打开网页版对话页，
    像人一样输入问题、点击发送、盯着回答逐字出现——把「人肉操作」变成
    可流式消费的生成器。登录态随浏览器用户 profile 持久化，一次登录长期有效，
    免费额度、网页版专属模型（R1 深度思考、联网搜索）都能直接使用。

核心类：
    BrowserSession   进程级浏览器会话（profile 持久化 / 线程亲和 / 健康探测）
    WebChatClient    网页对话站点适配器基类（模板方法 + 选择器多重备选）
    BrowserLLMError  统一错误（携带中文可操作指引）

依赖：playwright（可选）。未安装时所有入口给出安装指引，不影响其余功能。
"""
import os
import shutil
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Playwright 可选导入
# ---------------------------------------------------------------------------
_HAS_PW = False
sync_playwright = None
try:                                    # pragma: no cover - 环境相关
    from playwright.sync_api import sync_playwright as _sp
    sync_playwright = _sp
    _HAS_PW = True
except Exception:                       # noqa: BLE001 - 缺依赖时降级
    _HAS_PW = False

DEFAULT_TIMEOUT = 180          # 单次回答最长等待秒数
POLL_INTERVAL = 0.25           # 回答轮询间隔（秒）
STABLE_ROUNDS = 5              # 文本连续多少轮无变化视为回答完成（×0.25s ≈ 1.25s）

PLAYWRIGHT_HINT = (
    "网页版模式需要 Playwright。请执行：\n"
    "  pip install playwright\n"
    "  playwright install chromium")


def playwright_available():
    """Playwright 是否可用（供设置页/自测探测）"""
    return _HAS_PW


class BrowserLLMError(Exception):
    """浏览器接入错误（消息为中文可操作指引）"""
    pass


# ---------------------------------------------------------------------------
# 可执行文件探测
# ---------------------------------------------------------------------------
def _candidate_executables():
    """按平台列出常见 Chrome/Chromium 可执行文件路径"""
    out = []
    if os.environ.get("STARRY_CHROMIUM"):
        out.append(os.environ["STARRY_CHROMIUM"])
    out += [
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/snap/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    return out


def find_chromium():
    """找到可用的 Chrome/Chromium 可执行文件；找不到返回 None（用 Playwright 自带）"""
    for path in _candidate_executables():
        if path and os.path.isfile(path):
            return path
    found = shutil.which("chromium") or shutil.which("google-chrome")
    return found or None


def chromium_kernel_available():
    """Playwright **自带** Chromium 内核是否已安装（v12.0 新增）。

    与 ``find_chromium()`` 的区别：后者只找系统 Chrome/Chromium；本函数检查
    ``playwright install chromium`` 下载的浏览器。用于「一键安装内核」按钮：
    内核已就绪时直接给出反馈，不再启动线程重复下载 100+ MB。

    刻意用纯文件系统探测、不启动 ``sync_playwright()`` driver：设置页是 Qt
    主线程同步调用，启动 driver 子进程既慢又可能与事件循环冲突。
    """
    if not _HAS_PW:
        return False
    import glob
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        roots = [env]
    elif os.name == "nt":
        roots = [os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "ms-playwright")]
    else:
        roots = [os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")]
    rels = (
        os.path.join("chrome-win64", "chrome.exe"),
        os.path.join("chrome-win", "chrome.exe"),
        os.path.join("chrome-linux64", "chrome"),
        os.path.join("chrome-linux", "chrome"),
        os.path.join("chrome-headless-shell-win64", "chrome-headless-shell.exe"),
        os.path.join("chrome-headless-shell-linux64", "chrome-headless-shell"),
        os.path.join("chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
    )
    for root in roots:
        for pat in ("chromium-*", "chromium_headless_shell-*"):
            for d in glob.glob(os.path.join(root, pat)):
                if os.path.isdir(d) and any(
                        os.path.isfile(os.path.join(d, r)) for r in rels):
                    return True
    return False


def browser_guidance():
    """按当前环境返回浏览器可用性说明（设置页展示）"""
    if not _HAS_PW:
        return "未安装 Playwright——" + PLAYWRIGHT_HINT
    exe = find_chromium()
    if exe:
        return "已就绪（%s）" % exe
    return "已安装 Playwright（使用内置 Chromium）"


def _pip_install_playwright(on_line=None):
    """把 playwright 包装进当前解释器环境（venv / conda 均跟随
    sys.executable，即本进程实际使用的 Python），返回 (ok, detail)。"""
    import subprocess
    cmd = [sys.executable, "-m", "pip", "install", "playwright"]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
    except Exception as e:                         # noqa: BLE001
        return False, "无法启动 pip：%s" % str(e)[:150]
    tail = []
    for line in iter(proc.stdout.readline, ""):
        line = (line or "").rstrip()
        if not line:
            continue
        tail.append(line)
        tail = tail[-6:]
        if on_line:
            try:
                on_line(line)
            except Exception:                      # noqa: BLE001
                pass
    code = proc.wait()
    if code == 0:
        return True, "playwright 包安装完成"
    return False, "playwright 安装失败（退出码 %d）：%s" % (
        code, tail[-1] if tail else "")


def install_chromium(on_line=None, install_playwright=None):
    """在产品内一键安装浏览器内核（playwright install chromium）。

    install_playwright: None = 自动判断（缺包装包则先装）；True = 强制先装包。
    on_line: 可选回调，实时接收安装输出（str）。
    返回 (ok, detail)。全程子进程执行，不阻塞 UI（调用方放线程）。

    venv/conda 适配：pip 与 playwright 都通过 sys.executable 调用，
    装进的是「本进程实际使用的 Python 环境」，而非系统 Python。
    """
    import importlib.util
    import subprocess
    need_pkg = install_playwright
    if need_pkg is None:
        try:
            need_pkg = importlib.util.find_spec("playwright") is None
        except Exception:                          # noqa: BLE001
            need_pkg = True
    if need_pkg:
        if on_line:
            try:
                on_line("── 当前环境缺少 playwright 包，先安装 ──")
            except Exception:                      # noqa: BLE001
                pass
        ok, detail = _pip_install_playwright(on_line)
        if not ok:
            return False, detail
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
    except Exception as e:                         # noqa: BLE001
        return False, "无法启动安装进程：%s" % str(e)[:150]
    tail = []
    for line in iter(proc.stdout.readline, ""):
        line = (line or "").rstrip()
        if not line:
            continue
        tail.append(line)
        tail = tail[-6:]
        if on_line:
            try:
                on_line(line)
            except Exception:                      # noqa: BLE001
                pass
    code = proc.wait()
    if code == 0:
        return True, "浏览器内核安装完成"
    return False, "安装失败（退出码 %d）：%s" % (code, tail[-1] if tail else "")


# ---------------------------------------------------------------------------
# 浏览器会话（进程级单例）
# ---------------------------------------------------------------------------
class BrowserSession:
    """进程级浏览器会话。

    - 登录态持久化在 user_data_dir（磁盘），一次登录长期有效
    - 线程亲和：Playwright 对象只能在创建它的线程使用；换线程时自动
      以同一 profile 重建（登录态在磁盘上，无损失）
    - UI 线程「登录引导」与工作线程「提问」互斥共享，避免同一 profile
      被两个 context 同时占用
    """
    _instance = None
    _cls_lock = threading.Lock()

    def __init__(self):
        self._pw = None
        self._ctx = None
        self._page = None
        self._owner = None            # 持有 context 的线程标识
        self._lock = threading.Lock()

    # -- 单例 -------------------------------------------------------------
    @classmethod
    def instance(cls):
        with cls._cls_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -- 生命周期 ---------------------------------------------------------
    def ensure(self, profile_dir, headless=False, timeout_ms=30000):
        """确保当前线程有一个可用 context/page（必要时以同一 profile 重建）"""
        if not _HAS_PW:
            raise BrowserLLMError("未安装 Playwright。\n" + PLAYWRIGHT_HINT)
        me = threading.get_ident()
        with self._lock:
            if self._ctx is not None and self._owner != me:
                self._teardown_locked()
            if self._ctx is None or self._page is None or self._page.is_closed():
                self._launch_locked(profile_dir, headless, timeout_ms)
            return self._page

    def _launch_locked(self, profile_dir, headless, timeout_ms):
        os.makedirs(profile_dir, exist_ok=True)
        try:
            self._pw = sync_playwright().start()
            kwargs = dict(
                headless=bool(headless),
                viewport={"width": 1280, "height": 860},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                args=["--disable-blink-features=AutomationControlled",
                      "--no-default-browser-check",
                      "--disable-session-crashed-bubble"],
            )
            exe = find_chromium()
            if exe:
                kwargs["executable_path"] = exe
            self._ctx = self._pw.chromium.launch_persistent_context(
                profile_dir, **kwargs)
            self._ctx.set_default_timeout(timeout_ms)
            self._page = self._ctx.new_page()
            self._owner = threading.get_ident()
        except BrowserLLMError:
            raise
        except Exception as e:                     # noqa: BLE001
            self._teardown_locked()
            msg = str(e)
            if "Executable doesn't exist" in msg or "playwright install" in msg:
                raise BrowserLLMError(
                    "找不到浏览器内核。\n" + PLAYWRIGHT_HINT)
            raise BrowserLLMError("浏览器启动失败：%s" % msg[:200])

    def _teardown_locked(self):
        for closer, target in ((self._page, "close"),
                               (self._ctx, "close")):
            try:
                if target == "close" and closer is not None:
                    closer.close()
            except Exception:                      # noqa: BLE001
                pass
        self._page = None
        self._ctx = None
        self._owner = None
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:                          # noqa: BLE001
            pass
        self._pw = None

    def stop(self):
        with self._lock:
            self._teardown_locked()

    def is_alive(self):
        with self._lock:
            return (self._ctx is not None and self._page is not None
                    and not self._page.is_closed())


# ---------------------------------------------------------------------------
# 站点适配器基类
# ---------------------------------------------------------------------------
class WebChatClient:
    """网页对话站点适配器（模板方法）。

    接口对齐 core.api.ChatClient：
        chat_stream(messages, should_stop) -> yield ("reasoning"|"content", 文本)
        chat_agent_stream(messages, tools, should_stop) -> 同上 + ("notice", 文本)
    子类只需给出 URL 与选择器字典，即可获得完整「马具」能力。
    """
    SITE = "web"
    URL = ""
    TITLE = "网页版模型"

    # 默认选择器（站点改版时按列表顺序逐一尝试；设置中可整体覆盖）
    SELECTORS = {
        "input": ["textarea#chat-input", "textarea[class*='chat-input']",
                  "#chat-input textarea", "textarea"],
        "send": ["div[role='button'].ds-send-button",
                 "button[aria-label*='发送']",
                 "div[role='button'][aria-label*='发送']"],
        "answer_block": ["div.ds-message--assistant", ".ds-message--assistant",
                         "[class*='assistant']"],
        "answer": [".ds-markdown", ".markdown", "[class*='markdown']"],
        "reasoning": ["div.ds-think-content", ".ds-think-content",
                      "[class*='think']"],
        "stop": ["div[role='button'].ds-stop-button",
                 "button[aria-label*='停止']",
                 "div[role='button'][aria-label*='停止']"],
        "new_chat": ["text=开启新对话", "text=新对话",
                     "a[href='/']", "[class*='new-chat']"],
        "logged_in": ["img[class*='avatar']", "[class*='user-avatar']",
                      "[class*='avatar']"],
        "logged_out": ["text=登录", "a[href*='login']",
                       "button:has-text('登录')", "[class*='login']"],
    }

    def __init__(self, model="", headless=False, profile_dir=None,
                 url_override=None, selectors=None,
                 timeout=DEFAULT_TIMEOUT):
        self.model = model
        self.headless = bool(headless)
        self.profile_dir = profile_dir or os.path.join(
            os.path.expanduser("~"), ".starry", "browser", self.SITE)
        self.url = url_override or self.URL
        self.timeout = int(timeout)
        self.selectors = dict(self.SELECTORS)
        if selectors:
            for k, v in (selectors or {}).items():
                if v:
                    self.selectors[k] = list(v) if isinstance(v, (list, tuple)) else [v]
        self._stopped = False

    # ------------------------------------------------------------------
    # 提示词组装：网页版单轮发送，把最近对话以前文形式拼接（限长保护）
    # ------------------------------------------------------------------
    def compose_prompt(self, messages, max_prev=6000):
        """把消息列表组装成网页版可发送的单条文本。

        策略：只发最后一条 user 消息为「本轮问题」，此前的对话以
        「前情提要」形式附上（限长，超出截断并标注）。
        """
        items = [m for m in (messages or []) if m.get("content")]
        if not items:
            raise BrowserLLMError("没有可发送的消息内容")
        last = items[-1]
        if last.get("role") != "user":
            # 末尾不是用户消息（异常时序）：取最后一条用户消息
            last = next((m for m in reversed(items)
                         if m.get("role") == "user"), items[-1])
        prev = [m for m in items[:-1] if m is not last]
        if not prev:
            return str(last.get("content") or "")
        lines = ["（以下是之前的对话记录，请接着继续）"]
        used = 0
        for m in reversed(prev):
            role = {"user": "用户", "assistant": "助手",
                    "system": "系统"}.get(m.get("role"), m.get("role"))
            text = str(m.get("content") or "").strip()
            if not text:
                continue
            if used + len(text) > max_prev:
                room = max_prev - used
                if room > 80:
                    lines.append("%s：%s……（前文过长已截断）" % (role, text[:room]))
                else:
                    lines.append("……（更早的对话已省略）")
                break
            lines.append("%s：%s" % (role, text))
            used += len(text)
        lines.append("")
        lines.append("请回答：%s" % str(last.get("content") or ""))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 页面操作辅助
    # ------------------------------------------------------------------
    def _first_visible(self, page, key):
        """按选择器列表返回第一个可见元素 locator（找不到返回 None）"""
        for sel in self.selectors.get(key, []):
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=800):
                    return loc
            except Exception:                      # noqa: BLE001
                continue
        return None

    def _count(self, page, key):
        n = 0
        for sel in self.selectors.get(key, []):
            try:
                n = max(n, page.locator(sel).count())
            except Exception:                      # noqa: BLE001
                continue
        return n

    def _check_login(self, page):
        """登录态检测：未登录抛错并给出指引"""
        url = (page.url or "").lower()
        if "login" in url or "signin" in url:
            raise BrowserLLMError(
                "尚未登录 %s。\n请在弹出的浏览器窗口中完成登录"
                "（首次登录后会自动记住，无需反复登录）。" % self.TITLE)
        if self._first_visible(page, "logged_out") is not None and \
                self._first_visible(page, "logged_in") is None:
            raise BrowserLLMError(
                "检测到未登录 %s。\n请在弹出的浏览器窗口中完成登录后重试。"
                % self.TITLE)

    def _try_new_chat(self, page):
        """发送前尝试点击「新对话」，避免网页端历史与马具前文叠加"""
        loc = self._first_visible(page, "new_chat")
        if loc is not None:
            try:
                loc.click(timeout=1500)
                time.sleep(0.4)
            except Exception:                      # noqa: BLE001
                pass

    def _extract_reasoning(self, page):
        """可选：抓取深度思考过程文本（站点支持时）"""
        loc = self._first_visible(page, "reasoning")
        if loc is None:
            return ""
        try:
            return (loc.inner_text(timeout=800) or "").strip()
        except Exception:                          # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # 主流程（模板方法）
    # ------------------------------------------------------------------
    def chat_stream(self, messages, should_stop=None):
        if not _HAS_PW:
            raise BrowserLLMError("未安装 Playwright。\n" + PLAYWRIGHT_HINT)
        prompt = self.compose_prompt(messages)
        self._stopped = False

        page = BrowserSession.instance().ensure(
            self.profile_dir, self.headless)
        try:
            page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:                     # noqa: BLE001
            raise BrowserLLMError("无法打开 %s：%s" % (self.TITLE, str(e)[:150]))
        time.sleep(1.2)                            # 等前端框架接管页面
        self._check_login(page)

        box = self._first_visible(page, "input")
        if box is None:
            raise BrowserLLMError(
                "找不到输入框——%s 页面结构可能已更新，\n"
                "可在设置 → 网页接入中自定义选择器。" % self.TITLE)
        send = self._first_visible(page, "send")

        self._try_new_chat(page)
        before = self._count(page, "answer_block")

        try:
            box.click(timeout=3000)
            box.fill(prompt)
        except Exception as e:                     # noqa: BLE001
            raise BrowserLLMError("输入失败：%s" % str(e)[:150])
        time.sleep(0.3)

        if send is not None:
            try:
                send.click(timeout=3000)
            except Exception:                      # noqa: BLE001
                box.press("Enter")
        else:
            box.press("Enter")

        # ---- 流式轮询回答 ----
        deadline = time.time() + self.timeout
        last_text = ""
        stable = 0
        reasoning_sent = False
        while time.time() < deadline:
            if self._stopped or (should_stop and should_stop()):
                self._click_stop(page)
                return
            if not reasoning_sent:
                think = self._extract_reasoning(page)
                if think:
                    yield ("reasoning", think)
                    reasoning_sent = True
            now = self._read_last_answer(page, before)
            if now:
                if len(now) > len(last_text):
                    yield ("content", now[len(last_text):])
                    last_text = now
                    stable = 0
                elif now == last_text:
                    stable += 1
                    if stable >= STABLE_ROUNDS and \
                            self._first_visible(page, "stop") is None:
                        break
                else:
                    # 文本回退（极少见：站点重渲染）→ 以最长快照为准
                    last_text = max(last_text, now, key=len)
            time.sleep(POLL_INTERVAL)
        else:
            if last_text:
                return
            raise BrowserLLMError(
                "等待回答超时（%d 秒）。%s 可能正忙，请稍后重试。"
                % (self.timeout, self.TITLE))

    def _read_last_answer(self, page, before_count):
        """读取最新一条回答的纯文本（回答块数量超过发送前计数才采信）"""
        for sel in self.selectors.get("answer", []):
            try:
                locs = page.locator(sel)
                n = locs.count()
                if n > before_count or n > 0:
                    # 取最后一个可见的回答节点
                    for i in range(n - 1, -1, -1):
                        loc = locs.nth(i)
                        if loc.is_visible(timeout=500):
                            txt = (loc.inner_text(timeout=800) or "").strip()
                            if txt:
                                return txt
            except Exception:                      # noqa: BLE001
                continue
        return ""

    def _click_stop(self, page):
        loc = self._first_visible(page, "stop")
        if loc is not None:
            try:
                loc.click(timeout=1500)
            except Exception:                      # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # tools 降级（网页版没有函数调用）
    # ------------------------------------------------------------------
    def chat_agent_stream(self, messages, tools=None, should_stop=None):
        yield ("notice", "网页版模式暂不支持工具调用，已自动降级为普通对话")
        for item in self.chat_stream(messages, should_stop):
            yield item

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    def stop(self):
        self._stopped = True

    def close(self):
        self.stop()
        BrowserSession.instance().stop()

    def login_status(self):
        """探测登录态（设置页用）：返回 (ok, 说明)"""
        if not _HAS_PW:
            return False, "未安装 Playwright"
        try:
            page = BrowserSession.instance().ensure(
                self.profile_dir, self.headless)
            page.goto(self.url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(1.0)
            try:
                self._check_login(page)
                return True, "已登录"
            except BrowserLLMError as e:
                return False, str(e)
        except Exception as e:                     # noqa: BLE001
            return False, str(e)[:200]
