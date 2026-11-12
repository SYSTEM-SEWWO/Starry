# -*- coding: utf-8 -*-
"""多站点网页接入注册表（v7）—— 把浏览器 harness 从「DeepSeek 专用」泛化。

v6 只有 DeepSeek 一个站点；v7 起，同一套马具（core/browser_llm.py 的
WebChatClient）可以接入多个网页版 AI：

    web_deepseek  DeepSeek 网页版   chat.deepseek.com   官方维护
    web_zhipu     智谱清言网页版    chatglm.cn          社区维护
    web_doubao    豆包网页版        doubao.com          社区维护

「社区维护」的含义：选择器按公开可观察的页面结构编写，未经站点方保证；
站点改版后可能失效——此时无需升级软件，在
**设置 → 网页接入 → 选择器覆盖（高级）** 中改成新结构即可（每个键支持
多个候选用逗号分隔，留空则回退内置默认）。

新增一个站点 = 在 SITES 中加一条记录（选择器 + URL + 模型展示名），
主控制器、设置页、网关仪表盘、命令面板会自动识别（它们遍历 PROVIDERS
中带 web 标记的服务商）。
"""
import os

from core.browser_llm import (WebChatClient, BrowserLLMError,
                              playwright_available, browser_guidance)
from core.web_deepseek import DeepSeekWebClient

SITE_URL = "https://chat.deepseek.com/"

# 网页版可用「模型」（网页版由站点决定实际模型，这里只作展示与记录）
WEB_MODELS = ["deepseek-chat（网页版）", "deepseek-reasoner（网页版）"]


# ---------------------------------------------------------------------------
# 站点注册表
# ---------------------------------------------------------------------------
SITES = {
    # ---- 官方维护：DeepSeek（v6 首发站点） ----
    "web_deepseek": {
        "name": "DeepSeek 网页版",
        "url": "https://chat.deepseek.com/",
        "models": ["deepseek-chat（网页版）", "deepseek-reasoner（网页版）"],
        "selectors": DeepSeekWebClient.SELECTORS,
        "profile": "deepseek",
        "maintained": "随版本官方维护",
        "note": "免费额度 / R1 深度思考 / 联网搜索",
    },
    # ---- 社区维护：智谱清言 ----
    "web_zhipu": {
        "name": "智谱清言网页版",
        "url": "https://chatglm.cn/",
        "models": ["glm-4（网页版）", "glm-4-plus（网页版）"],
        "selectors": {
            "input": ["div[contenteditable='true']",
                      "textarea[placeholder*='问题']",
                      ".input-box textarea", "textarea"],
            "send": ["button[aria-label*='发送']",
                     "div[role='button'][aria-label*='发送']",
                     "button.send"],
            "answer_block": ["[class*='answer']", ".markdown-body",
                             "[class*='markdown']"],
            "answer": [".markdown-body", "[class*='markdown']"],
            "reasoning": ["[class*='think']", "[class*='reason']"],
            "stop": ["button[aria-label*='停止']",
                     "div[role='button'][aria-label*='停止']"],
            "new_chat": ["text=开启新对话", "text=新对话", "a[href='/']"],
            "logged_in": ["img[class*='avatar']", "[class*='avatar']"],
            "logged_out": ["text=登录", "button:has-text('登录')",
                           "a[href*='login']"],
        },
        "profile": "zhipu",
        "maintained": "社区维护（失效请在设置页改选择器）",
        "note": "GLM-4 免费额度 / 联网搜索",
    },
    # ---- 社区维护：豆包 ----
    "web_doubao": {
        "name": "豆包网页版",
        "url": "https://www.doubao.com/chat/",
        "models": ["doubao-pro（网页版）", "doubao-lite（网页版）"],
        "selectors": {
            "input": ["div[data-testid='chat-input']",
                      "div[contenteditable='true']", "textarea"],
            "send": ["button[data-testid='chat-button-send']",
                     "button[aria-label*='发送']",
                     "div[role='button'][aria-label*='发送']"],
            "answer_block": ["[data-testid='message']", "[class*='message']"],
            "answer": ["[class*='markdown']", ".markdown"],
            "reasoning": [],
            "stop": ["button[aria-label*='停止']",
                     "div[role='button'][aria-label*='停止']"],
            "new_chat": ["text=开启新对话", "text=新对话"],
            "logged_in": ["img[class*='avatar']", "[class*='avatar']"],
            "logged_out": ["text=登录", "button:has-text('登录')",
                           "a[href*='login']"],
        },
        "profile": "doubao",
        "maintained": "社区维护（失效请在设置页改选择器）",
        "note": "字节跳动豆包 / 免费额度",
    },
}

# 选择器键的中文名（设置页编辑器用）
SELECTOR_LABELS = {
    "input": "输入框",
    "send": "发送按钮",
    "answer_block": "回答消息块",
    "answer": "回答正文（Markdown 区）",
    "reasoning": "思考过程（可选）",
    "stop": "停止按钮（可选）",
    "new_chat": "新对话按钮（可选）",
    "logged_in": "已登录标志（如头像）",
    "logged_out": "未登录标志（如登录按钮）",
}

_CLIENT_CACHE = {}


def site_keys():
    """全部网页站点 key（与 PROVIDERS 中带 web 标记的服务商对应）"""
    return list(SITES.keys())


def get_site(site_key):
    return SITES.get(site_key)


def is_web_site(site_key):
    return site_key in SITES


def default_profile_dir(site_key):
    sub = (SITES.get(site_key) or {}).get("profile") or site_key
    return os.path.join(os.path.expanduser("~"), ".starry", "browser", sub)


def site_models(site_key):
    return list((SITES.get(site_key) or {}).get("models") or WEB_MODELS)


def _client_class(site_key):
    """为站点生成（并缓存）WebChatClient 子类——SELECTORS 按站点定制"""
    if site_key in _CLIENT_CACHE:
        return _CLIENT_CACHE[site_key]
    site = SITES[site_key]
    cls = type("WebClient_%s" % site_key, (WebChatClient,), {
        "SITE": site_key,
        "URL": site["url"],
        "TITLE": site["name"],
        "SELECTORS": site["selectors"],
    })
    _CLIENT_CACHE[site_key] = cls
    return cls


def create_site_client(site_key, cfg=None, headless=None, url_override=None):
    """按配置创建某个网页站点的客户端（设置页/控制器共用）"""
    site = SITES.get(site_key) or SITES["web_deepseek"]
    data = (cfg.data if cfg is not None else {}) or {}
    web_cfg = data.get(site_key, {}) or {}
    hs = web_cfg.get("headless", False) if headless is None else headless
    model = ""
    if cfg is not None:
        try:
            model = cfg.model() or ""
        except Exception:                          # noqa: BLE001
            model = ""
    cls = _client_class(site_key)
    return cls(
        model=model or site["models"][0],
        headless=bool(hs),
        profile_dir=web_cfg.get("profile_dir") or default_profile_dir(site_key),
        url_override=url_override,
        selectors=web_cfg.get("selectors") or None,
        timeout=int(web_cfg.get("timeout", 180) or 180),
    )


def site_status_text(site_key, cfg=None):
    """设置页状态行文案：环境就绪度 + 登录态探测结果（任意站点通用）"""
    site = SITES.get(site_key) or SITES["web_deepseek"]
    if not playwright_available():
        return ("✗ 未就绪", "需要安装 Playwright：pip install playwright\n"
                            "然后执行 playwright install chromium")
    try:
        client = create_site_client(site_key, cfg)
    except Exception as e:                         # noqa: BLE001
        return ("✗ 未就绪", str(e)[:120])
    ok, detail = client.login_status()
    if ok:
        return ("✓ 已就绪（已登录）",
                "%s 登录态已持久化，可直接使用" % site["name"])
    return ("⚠ 未登录", detail)


def site_login_hint(site_key):
    site = SITES.get(site_key) or SITES["web_deepseek"]
    return "🌐 正在打开浏览器，请在窗口中登录 %s（登录一次即可）" % site["name"]


__all__ = ["SITES", "SELECTOR_LABELS", "site_keys", "get_site", "is_web_site",
           "default_profile_dir", "site_models", "create_site_client",
           "site_status_text", "site_login_hint", "SITE_URL", "WEB_MODELS",
           "DeepSeekWebClient", "BrowserLLMError", "playwright_available",
           "browser_guidance"]
