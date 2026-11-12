# -*- coding: utf-8 -*-
"""大模型 API 客户端。

- ChatClient          : OpenAI 兼容 /chat/completions 流式客户端（支持 reasoning_content 思考流）
- list_models         : 拉取 OpenAI 兼容 /models 模型列表
- list_ollama_models  : 拉取 Ollama 本地已安装模型列表
"""
import json

import requests

from core import apidiag
from core import apierrors


class ChatError(Exception):
    """API 调用错误（携带可读信息 + v13.2 结构化脱敏详情）。

    `detail` 是 `core.apierrors` 产出的 dict；UI 可用 `apierrors.full_text()`
    渲染分类、建议与退避策略。旧代码只传 message，行为完全不变。
    """

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail if isinstance(detail, dict) else {}


class ToolsUnsupportedError(ChatError):
    """当前模型/服务商不支持 tools 参数（调用方应降级为普通对话）"""
    pass


def _friendly_http_error(status, body="", operation="api"):
    """把 HTTP 错误翻译成中文**可操作**提示，并沉淀脱敏诊断记录。

    v13.2：保留原有中文文案（不破坏既有行为），但
      * 上游响应体先经 `apierrors.redact()` 脱敏，不再原样展示；
      * 追加一条可操作建议，用户知道下一步该做什么；
      * 每条失败写入 `core.apidiag`，事后可在「API 诊断」中追溯。
    """
    err = apierrors.from_http(status, body, operation=operation)
    hint = {
        401: "API Key 无效或未授权，请在设置中检查 Key 是否正确",
        402: "账户额度不足，请充值或更换服务商/模型",
        403: "没有访问权限（可能是模型需要额外申请）",
        404: "接口或模型不存在，请检查 Base URL 与模型名",
        429: "请求过于频繁或免费额度已用完，请稍后再试或切换模型",
        500: "服务商内部错误，请稍后重试",
        502: "服务商网关错误，请稍后重试",
        503: "服务商暂时不可用（可能过载），请稍后重试",
    }.get(status)
    base = ("HTTP %d：%s" % (status, hint) if hint
            else "接口返回 HTTP %d：%s" % (status, apierrors.redact(body, 120)))
    advice = err.get("advice") or []
    return base + ("\n建议：%s" % advice[0] if advice else "")


class ChatClient:
    def __init__(self, base_url, api_key, model,
                 temperature=0.7, max_tokens=4096, timeout=(10, 180),
                 top_p=None, reasoning_effort=None):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.top_p = top_p                    # None/1.0 表示不下发
        self.reasoning_effort = reasoning_effort   # None/"off"/"low"/"medium"/"high"

    def _headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def _build_payload(self, messages, tools=None):
        """组装请求体（含生成参数与思考强度）"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if self.top_p is not None and abs(float(self.top_p) - 1.0) > 1e-6:
            payload["top_p"] = round(float(self.top_p), 3)
        if self.reasoning_effort and self.reasoning_effort != "off":
            # OpenAI o-series / OpenRouter 等新协议的思考强度字段
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def chat_stream(self, messages, should_stop=None):
        """流式对话生成器。

        逐条 yield ("reasoning", 文本) / ("content", 文本)。
        should_stop: 可选的可调用对象，返回 True 时提前终止。
        """
        if not self.base_url:
            raise ChatError("未配置 API 地址（Base URL）")
        if not self.model:
            raise ChatError("未选择模型，请在右上角下拉框或设置中选择")

        url = self.base_url + "/chat/completions"
        payload = self._build_payload(messages)
        try:
            resp = requests.post(url, headers=self._headers(), json=payload,
                                 stream=True, timeout=self.timeout)
        except requests.exceptions.ConnectTimeout:
            raise ChatError("连接超时，请检查网络或 Base URL")
        except requests.exceptions.ReadTimeout:
            raise ChatError("读取超时，模型响应时间过长")
        except requests.exceptions.ConnectionError as e:
            raise ChatError("网络连接失败：%s" % e)
        except requests.RequestException as e:
            raise ChatError("请求失败：%s" % e)

        # 强制 UTF-8：SSE 流式响应常不带 charset，requests 会默认按 ISO-8859-1(latin-1)
        # 解码，导致中文变成 ä½ å¥½ 这类乱码。LLM 接口始终为 UTF-8，这里显式锁定。
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            body = apierrors.redact(resp.text)
            err = apierrors.from_http(resp.status_code, resp.text or "", "chat")
            apidiag.record("chat", err, scope="http")
            raise ChatError(_friendly_http_error(resp.status_code, body), err)

        for raw in resp.iter_lines(decode_unicode=True):
            if should_stop and should_stop():
                return
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise ChatError(apierrors.redact(obj["error"]))
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            # 思考过程（不同厂商字段名略有差异）
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            content = delta.get("content")
            if reasoning:
                yield ("reasoning", reasoning)
            if content:
                yield ("content", content)


    def chat_agent_stream(self, messages, tools, should_stop=None):
        """带工具调用的流式对话生成器。

        tools: OpenAI tools 数组（[{"type":"function","function":{...}}]）
        逐条 yield ("reasoning", 文本) / ("content", 文本)，
        流结束时若模型请求工具调用，额外 yield ("tool_calls", [调用列表])。
        服务商不支持 tools 时抛 ToolsUnsupportedError。
        """
        if not self.base_url:
            raise ChatError("未配置 API 地址（Base URL）")
        if not self.model:
            raise ChatError("未选择模型，请在右上角下拉框或设置中选择")

        url = self.base_url + "/chat/completions"
        payload = self._build_payload(messages, tools)
        try:
            resp = requests.post(url, headers=self._headers(), json=payload,
                                 stream=True, timeout=self.timeout)
        except requests.exceptions.ConnectTimeout:
            raise ChatError("连接超时，请检查网络或 Base URL")
        except requests.exceptions.ReadTimeout:
            raise ChatError("读取超时，模型响应时间过长")
        except requests.exceptions.ConnectionError as e:
            raise ChatError("网络连接失败：%s" % e)
        except requests.RequestException as e:
            raise ChatError("请求失败：%s" % e)

        # 强制 UTF-8：SSE 流式响应常不带 charset，requests 会默认按 ISO-8859-1(latin-1)
        # 解码，导致中文变成 ä½ å¥½ 这类乱码。LLM 接口始终为 UTF-8，这里显式锁定。
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            body = apierrors.redact(resp.text)
            if resp.status_code == 400 and "tool" in body.lower():
                raise ToolsUnsupportedError(
                    "当前模型不支持工具调用（tools），已自动降级为普通对话")
            err = apierrors.from_http(resp.status_code, resp.text or "", "chat")
            apidiag.record("chat", err, scope="http")
            raise ChatError(_friendly_http_error(resp.status_code, body), err)

        tool_acc = {}                      # index -> {"id","name","arguments"}
        for raw in resp.iter_lines(decode_unicode=True):
            if should_stop and should_stop():
                return
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise ChatError(apierrors.redact(obj["error"]))
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            content = delta.get("content")
            if reasoning:
                yield ("reasoning", reasoning)
            if content:
                yield ("content", content)
            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index", 0)
                acc = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    acc["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    acc["name"] = fn["name"]
                if fn.get("arguments"):
                    acc["arguments"] += fn["arguments"]

        calls = []
        for idx in sorted(tool_acc):
            acc = tool_acc[idx]
            if not acc["name"]:
                continue
            try:
                args = json.loads(acc["arguments"] or "{}")
                if not isinstance(args, dict):
                    args = {"value": args}
            except json.JSONDecodeError:
                args = {"_raw": acc["arguments"]}
            calls.append({"id": acc["id"] or ("call_%d" % idx),
                          "name": acc["name"], "arguments": args})
        if calls:
            yield ("tool_calls", calls)


def _timeout_pair(timeout):
    """连接超时 / 读取超时分离，避免单个长超时把启动流程卡死。"""
    if isinstance(timeout, (tuple, list)):
        return tuple(timeout)
    try:
        t = float(timeout)
    except (TypeError, ValueError):
        t = 15.0
    return (min(5.0, t), t)


def list_models(base_url, api_key, timeout=15, operation="list_models"):
    """拉取 OpenAI 兼容接口的模型列表（统一错误分类 / 脱敏 / 诊断）。

    v13.2 修复：此前 401 会抛 ``HTTP 401：<上游原始响应体>``，既无可操作
    建议也可能泄露上游内容。现在所有失败都经过 `core.apierrors` 分类与
    `core.apidiag` 脱敏记录，调用方拿到的是可执行的中文提示。
    """
    base = (base_url or "").rstrip("/")
    if not base:
        err = apierrors.config_error("未配置 API 地址")
        apidiag.record(operation, err, scope="config")
        raise ChatError(apierrors.one_line(err))
    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    try:
        r = requests.get(base + "/models", headers=headers,
                         timeout=_timeout_pair(timeout))
    except requests.RequestException as e:
        err = apierrors.from_exception(e, operation)
        apidiag.record(operation, err, scope="network")
        raise ChatError(apierrors.one_line(err))
    if r.status_code != 200:
        err = apierrors.from_http(r.status_code, r.text or "", operation)
        apidiag.record(operation, err, scope="http")
        raise ChatError(_friendly_http_error(r.status_code, r.text or "",
                                             operation), err)
    try:
        data = r.json()
    except ValueError as e:
        err = apierrors.from_exception(e, operation)
        apidiag.record(operation, err, scope="parse")
        raise ChatError(apierrors.one_line(err), err)
    return [m.get("id") for m in (data.get("data") or []) if m.get("id")]


def list_ollama_models(tags_url="http://localhost:11434/api/tags", timeout=8):
    """拉取 Ollama 本地已安装模型（失败静默降级 + 脱敏诊断）。"""
    operation = "list_ollama_models"
    try:
        r = requests.get(tags_url, timeout=_timeout_pair(timeout))
    except requests.RequestException as e:
        err = apierrors.from_exception(e, operation)
        apidiag.record(operation, err, scope="local_probe")
        raise ChatError("无法连接 Ollama：%s" % apierrors.redact(e, 100))
    if r.status_code != 200:
        err = apierrors.from_http(r.status_code, r.text or "", operation)
        apidiag.record(operation, err, scope="http")
        raise ChatError(_friendly_http_error(r.status_code, r.text or "",
                                             operation), err)
    try:
        data = r.json()
    except ValueError as e:
        err = apierrors.from_exception(e, operation)
        apidiag.record(operation, err, scope="parse")
        raise ChatError(apierrors.one_line(err), err)
    return [m.get("name") for m in data.get("models", []) if m.get("name")]
