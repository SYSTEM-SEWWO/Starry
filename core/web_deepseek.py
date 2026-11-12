# -*- coding: utf-8 -*-
"""DeepSeek 网页版适配器 —— 给 chat.deepseek.com 「套上马具」。

通过浏览器自动化接入 DeepSeek 网页版（免费额度 / R1 深度思考 / 联网搜索），
对上层暴露与 core.api.ChatClient 完全一致的流式接口，因此：
    - 设置里把服务商切到「DeepSeek 网页版」即可使用，无需 API Key
    - 思考过程、流式输出、随时停止、对话分支等既有能力原样生效

登录：首次使用时会弹出真实浏览器窗口，登录一次后登录态持久化，
之后每次自动带上（可选无头模式，见设置 → 网页接入）。
"""
import os

from core.browser_llm import (WebChatClient, BrowserLLMError,
                              playwright_available, browser_guidance)

SITE_URL = "https://chat.deepseek.com/"

# 网页版可用「模型」（网页版由站点决定实际模型，这里只作展示与记录）
WEB_MODELS = ["deepseek-chat（网页版）", "deepseek-reasoner（网页版）"]


class DeepSeekWebClient(WebChatClient):
    """DeepSeek 网页版客户端（马具）"""
    SITE = "deepseek"
    URL = SITE_URL
    TITLE = "DeepSeek 网页版"

    # DeepSeek 站点选择器微调（基类已提供通用备选，这里按站点优先级排序）
    SELECTORS = {
        "input": ["textarea#chat-input", "textarea[class*='chat-input']",
                  "#chat-input textarea", "textarea"],
        "send": ["div[role='button'].ds-icon-button--active",
                 "div[role='button'][aria-label*='发送']",
                 ".ds-send-button"],
        "answer_block": ["div.ds-message--assistant", ".ds-message--assistant",
                         "[class*='assistant']"],
        "answer": [".ds-markdown", ".markdown", "[class*='markdown']"],
        "reasoning": ["div.ds-think-content", ".ds-think-content"],
        "stop": ["div[role='button'][aria-label*='停止']",
                 ".ds-stop-button"],
        "new_chat": ["text=开启新对话", "text=新对话", "a[href='/']"],
        "logged_in": ["img[class*='avatar']", "[class*='avatar']"],
        "logged_out": ["text=登录", "a[href*='login']",
                       "button:has-text('登录')"],
    }


def default_profile_dir():
    return os.path.join(os.path.expanduser("~"), ".starry", "browser", "deepseek")


def create_web_client(cfg=None, headless=None, url_override=None):
    """按配置创建 DeepSeek 网页版客户端（设置页/控制器共用）"""
    data = (cfg.data if cfg is not None else {}) or {}
    web_cfg = data.get("web_deepseek", {}) or {}
    hs = web_cfg.get("headless", False) if headless is None else headless
    model = (cfg.model() if cfg is not None else "") or WEB_MODELS[0]
    return DeepSeekWebClient(
        model=model,
        headless=bool(hs),
        profile_dir=web_cfg.get("profile_dir") or default_profile_dir(),
        url_override=url_override,
        selectors=web_cfg.get("selectors") or None,
        timeout=int(web_cfg.get("timeout", 180) or 180),
    )


def web_status_text(cfg=None):
    """设置页状态行文案：环境就绪度 + 登录态探测结果"""
    if not playwright_available():
        return ("✗ 未就绪", "需要安装 Playwright：pip install playwright\n"
                            "然后执行 playwright install chromium")
    try:
        client = create_web_client(cfg)
    except Exception as e:                         # noqa: BLE001
        return ("✗ 未就绪", str(e)[:120])
    ok, detail = client.login_status()
    if ok:
        return ("✓ 已就绪（已登录）", "登录态已持久化，可直接使用网页版模式")
    return ("⚠ 未登录", detail)


__all__ = ["DeepSeekWebClient", "create_web_client", "default_profile_dir",
           "web_status_text", "WEB_MODELS", "SITE_URL", "BrowserLLMError",
           "playwright_available", "browser_guidance"]
