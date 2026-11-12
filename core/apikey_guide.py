# -*- coding: utf-8 -*-
"""应用内「申请 API Key」过程说明（v13.4）。

纯数据 + 纯逻辑，零联网、零第三方依赖：桌面设置页、命令面板、新手引导、
CLI 可以共用同一份说明，避免文案散落各处、改一处漏三处。

申请地址与 Base URL 直接取自 ``core.config.PROVIDERS``（单一真源），
本模块只补充「分服务商的具体步骤与注意事项」。
"""
from core.config import PROVIDERS

# 通用步骤模板（{name} / {key_url} / {base_url} 由 guide_for 填充）
GENERAL_STEPS = [
    ("打开控制台", "在浏览器打开该服务商的开放平台：{key_url}"),
    ("注册并登录", "用手机号 / 邮箱完成注册；国内平台通常需要实名认证后才可创建密钥。"),
    ("创建 API Key", "进入「API Keys / 访问密钥」页面 → 点「创建新的 API Key」→ "
                     "**立刻复制**。多数平台只完整显示一次，关闭后就看不到全文了。"),
    ("填入星语", "回到应用：设置 → 服务商选择「{name}」→ 把 Key 粘贴到 API Key 输入框 → 保存。"),
    ("验证连通", "点设置页「获取模型列表」；能拉到模型说明 Key 与 Base URL 都正确。"
                 "也可在命令面板执行「🩺 运行环境自检」。"),
    ("开始对话", "回到主窗口发一句话。若报 401，用命令面板「📋 API 诊断」查看脱敏后的分类与建议。"),
]

GENERAL_NOTES = [
    "API Key 只保存在本机的配置目录（config.json），星语不会把它上传到任何第三方。",
    "不要把 Key 提交到 Git、贴进聊天或截图分享；「导出配置」生成的 zip 含 Key，请妥善保管。",
    "Base URL 填到 /v1 或平台给出的兼容前缀即可，不要带 /chat/completions。",
    "免费额度与速率限制由各平台决定；欠费 / 超限通常表现为 401 / 402 / 429。",
    "若不想申请 Key：可选「网页版接入」（浏览器登录态）或本地 Ollama / GGUF 模型。",
]

# 各服务商的差异化提示（键与 PROVIDERS 对齐；未列出的走通用说明）
PROVIDER_HINTS = {
    "zhipu": [
        "推荐先用 glm-4-flash：官方免费模型，注册创建 Key 后即可零成本试用。",
        "控制台路径：开放平台 → 用户中心 → API Keys。",
    ],
    "siliconflow": [
        "新用户有赠送额度，Qwen / GLM / DeepSeek 多款模型可免费调用。",
        "模型名带厂商前缀（如 Qwen/Qwen2.5-7B-Instruct），直接从「获取模型列表」里选即可。",
    ],
    "deepseek": [
        "DeepSeek 开放平台需要充值后才能调用（单价很低）；deepseek-reasoner 是推理模型，"
        "开启「深度思考」时会自动优先使用。",
        "只支持 OpenAI 兼容的 /chat/completions，Base URL 固定 https://api.deepseek.com/v1。",
    ],
    "dashscope": [
        "阿里云百炼新用户有较大的免费 Token 额度，需在控制台开通「百炼」服务。",
        "兼容模式 Base URL 以 /compatible-mode/v1 结尾，不要用旧版 SDK 地址。",
    ],
    "openrouter": [
        "模型名带 :free 后缀的是免费模型，有速率限制；付费模型走同一把 Key。",
        "可在 Keys 页面给 Key 设置额度上限，避免意外扣费。",
    ],
    "groq": [
        "Groq 免费额度充足、推理极快；部分模型有每分钟请求数限制。",
    ],
    "custom": [
        "自定义 OpenAI 兼容服务：Base URL 与 Key 由你的服务提供方给出，"
        "也可留空 Key（本地网关不鉴权时）。",
    ],
}

# 无需 Key 的服务商 → 给替代说明，而不是让用户白跑一趟控制台
NO_KEY_NOTES = {
    "web": [
        "这是网页版接入，**不需要 API Key**：在「网页接入」页登录对应网站，"
        "用浏览器登录态承载会话即可。",
        "首次使用需按提示安装浏览器内核（产品内一键安装，不内嵌 150MB 文件）。",
    ],
    "local": [
        "本地模型（Ollama / llama.cpp GGUF）在本机推理，**不需要 API Key**。",
        "确认本地服务已启动（Ollama 默认 http://localhost:11434），再用「获取模型列表」探测。",
    ],
}


def provider_keys():
    return sorted(PROVIDERS.keys())


def needs_key(provider_key):
    info = PROVIDERS.get(provider_key) or {}
    return not (info.get("web") or info.get("local"))


def check_key(api_key, provider_key="custom"):
    """本地格式自检（不联网）：返回 (是否看起来有效, 提示文案)。"""
    k = (api_key or "").strip()
    if not needs_key(provider_key):
        return True, "该服务商无需 API Key"
    if not k:
        return False, "尚未填写 API Key"
    if len(k) < 12:
        return False, "Key 长度明显偏短，请检查是否复制完整"
    if " " in k or "\n" in k:
        return False, "Key 中不应包含空格或换行"
    return True, "格式看起来正常（真实有效性需点「获取模型列表」验证）"


def guide_for(provider_key, api_key=None):
    """返回某服务商的完整申请引导（结构化，供 UI 与 CLI 共用）。"""
    key = provider_key if provider_key in PROVIDERS else "custom"
    info = PROVIDERS.get(key) or {}
    name = info.get("name", key)
    key_url = info.get("key_url", "")
    base_url = info.get("base_url", "")
    if needs_key(key):
        steps = [(t, s.format(name=name, key_url=key_url or "（见服务商官网）",
                              base_url=base_url or "（由服务商提供）"))
                 for t, s in GENERAL_STEPS]
        notes = list(GENERAL_NOTES) + list(PROVIDER_HINTS.get(key, []))
    else:
        steps = [("无需申请", "该模式不使用 API Key，直接按下面的说明使用即可。"),
                 ("开始使用", "回到主窗口，确认已选中对应服务商后发送一条消息。")]
        kind = "web" if info.get("web") else "local"
        notes = list(GENERAL_NOTES[:1]) + list(NO_KEY_NOTES[kind])
    ok, hint = check_key(api_key, key)
    return {
        "key": key,
        "name": name,
        "key_url": key_url,
        "base_url": base_url,
        "needs_key": needs_key(key),
        "steps": steps,
        "notes": notes,
        "key_ok": ok,
        "key_hint": hint,
        "desc": info.get("desc", ""),
    }


def all_guides(api_keys=None):
    """全部服务商引导（设置页左侧列表用）。"""
    keys = api_keys or {}
    return [guide_for(k, keys.get(k)) for k in provider_keys()]


def format_guide(provider_key, api_key=None):
    """纯文本渲染（CLI / 复制到剪贴板 / 无障碍场景）。"""
    g = guide_for(provider_key, api_key)
    lines = ["# 申请 API Key · %s" % g["name"], ""]
    if g["desc"]:
        lines += [g["desc"], ""]
    if g["key_url"]:
        lines += ["申请地址：%s" % g["key_url"], ""]
    if g["base_url"]:
        lines += ["Base URL：%s" % g["base_url"], ""]
    lines.append("当前 Key 状态：%s" % g["key_hint"])
    lines.append("")
    for i, (title, body) in enumerate(g["steps"], 1):
        lines.append("%d. %s" % (i, title))
        lines.append("   %s" % body)
    lines.append("")
    lines.append("注意事项：")
    for n in g["notes"]:
        lines.append("  - %s" % n)
    return "\n".join(lines)
