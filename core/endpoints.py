# -*- coding: utf-8 -*-
"""本地模型服务端点判定（v13.6）。

纯标准库、零依赖、三端同源：桌面设置页、ModelFetcher、CLI 诊断共用同一份
判定，避免「按服务商名硬编码端点」导致的模型列表拉不到。

背景：旧实现里 ``key == "ollama"`` 就固定请求 ``localhost:11434/api/tags``，
完全忽略用户填写的 Base URL。当用户在 Ollama 项填了 LM Studio 的 1234 端口
时，模型列表永远为空 —— 表现就是「设置里改不了模型 / 默认 lmstudio」。
"""
import re

_OLLAMA_DEFAULT_TAGS = "http://localhost:11434/api/tags"


def normalize_base_url(url):
    """清理粘贴进来的 Base URL（去首尾空白、内部换行与空格、末尾斜杠）。

    真实配置里曾出现 ``http://127.0.0.1:1234\\n/v1``（粘贴带换行），
    会让请求直接失败，这里统一归一化。
    """
    return re.sub(r"\s+", "", (url or "").strip()).rstrip("/")


def resolve_endpoint(provider_key, base_url="", info=None):
    """决定「获取模型列表」走 Ollama /api/tags 还是 OpenAI 兼容 /v1/models。

    以**实际地址**为准，服务商名只在地址为空时作缺省兜底；同时返回错配
    提示，帮助把「Ollama 填了 LM Studio 端口」这类配置纠正过来。

    返回 {mode, is_ollama, base_url, tags_url, mismatch, hint, suggest_provider}
    """
    url = normalize_base_url(base_url)
    low = url.lower()
    if url:
        mode = "ollama" if (":11434" in low or "/api/tags" in low) else "openai"
    else:
        mode = "ollama" if provider_key == "ollama" else "openai"

    if mode == "ollama":
        if "/api/tags" in low:
            tags = url
        elif url:
            tags = url + "/api/tags"
        else:
            tags = _OLLAMA_DEFAULT_TAGS
    else:
        tags = _OLLAMA_DEFAULT_TAGS

    mismatch, hint, suggest = False, "", None
    if provider_key == "ollama" and mode == "openai" and url:
        mismatch = True
        suggest = "lmstudio" if ":1234" in low else "custom"
        hint = ("当前是「Ollama」服务商，但 Base URL 为 %s。本次已按 "
                "OpenAI 兼容 /v1/models 拉取；若这是 LM Studio（端口 1234），"
                "建议改选「LM Studio 本地」服务商。" % url)
    elif provider_key == "lmstudio" and mode == "ollama" and url:
        mismatch = True
        suggest = "ollama"
        hint = ("当前是「LM Studio」服务商，但 Base URL 指向 Ollama(11434)；"
                "本次已按 /api/tags 拉取，建议核对服务商。")
    return {
        "mode": mode,
        "is_ollama": mode == "ollama",
        "base_url": url,
        "tags_url": tags,
        "mismatch": mismatch,
        "hint": hint,
        "suggest_provider": suggest,
    }
