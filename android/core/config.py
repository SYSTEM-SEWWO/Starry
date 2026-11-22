# -*- coding: utf-8 -*-
"""配置管理：内置免费/付费 API 提供商预设、API Key、模型与外观设置。

配置文件位置：
    Windows : %APPDATA%/ai-desktop-assistant/config.json
    macOS   : ~/Library/Application Support/ai-desktop-assistant/config.json
    Linux   : ~/.config/ai-desktop-assistant/config.json
"""
import copy
import hashlib
import json
import os
import re
import sys
import tempfile

APP_ID = "ai-desktop-assistant"
APP_NAME = "星语 · Starry"
APP_VERSION = "15.0.0"

# ---------------------------------------------------------------------------
# 内置提供商预设（全部为 OpenAI 兼容 /chat/completions 接口，Ollama 亦兼容）
# ---------------------------------------------------------------------------
PROVIDERS = {
    "zhipu": {
        "name": "智谱 AI · GLM-4-Flash（免费）",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-flashx", "glm-4-air", "glm-4-plus",
                   "glm-4v-flash", "glm-4v-plus", "glm-z1-air", "glm-z1-flash"],
        "default_model": "glm-4-flash",
        "local": False,
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "desc": "智谱开放平台。glm-4-flash 模型免费，注册后在用户中心创建 API Key 即可。",
    },
    "siliconflow": {
        "name": "硅基流动 SiliconFlow（免费模型）",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": [
            "Qwen/Qwen2.5-7B-Instruct",
            "Qwen/Qwen2.5-14B-Instruct",
            "Qwen/Qwen2.5-VL-7B-Instruct",
            "THUDM/glm-4-9b-chat",
            "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
            "Qwen/QwQ-32B",
        ],
        "default_model": "Qwen/Qwen2.5-7B-Instruct",
        "local": False,
        "key_url": "https://cloud.siliconflow.cn/account/ak",
        "desc": "硅基流动。新用户赠送额度，Qwen / GLM / DeepSeek 等多款模型免费调用，QwQ 系列支持思考过程。",
    },
    "deepseek": {
        "name": "DeepSeek（深度思考）",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "local": False,
        "key_url": "https://platform.deepseek.com/api_keys",
        "desc": "deepseek-reasoner 为推理模型，可完整呈现思考过程。充值可用，价格极低。",
    },
    "dashscope": {
        "name": "阿里百炼 DashScope（免费额度）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-turbo", "qwen-long", "qwq-plus",
                   "qwen-vl-max", "qwen-vl-plus"],
        "default_model": "qwen-plus",
        "local": False,
        "key_url": "https://bailian.console.aliyun.com/?apiKey=1",
        "desc": "阿里云百炼平台，新用户有大量免费 Token 额度，qwq-plus 支持思考过程。",
    },
    "openrouter": {
        "name": "OpenRouter（含免费模型）",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "deepseek/deepseek-r1:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen-2.5-vl-7b-instruct:free",
        ],
        "default_model": "deepseek/deepseek-r1:free",
        "local": False,
        "key_url": "https://openrouter.ai/keys",
        "desc": "OpenRouter 聚合平台，模型名带 :free 后缀的免费（有速率限制）。",
    },
    "groq": {
        "name": "Groq（免费高速）",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "deepseek-r1-distill-llama-70b",
                   "qwen-2.5-32b", "llama-3.2-11b-vision-preview",
                   "llama-3.2-90b-vision-preview"],
        "default_model": "llama-3.3-70b-versatile",
        "local": False,
        "key_url": "https://console.groq.com/keys",
        "desc": "Groq 推理速度极快，免费额度充足。",
    },
    "moonshot": {
        "name": "Moonshot · Kimi（长上下文）",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "default_model": "moonshot-v1-8k",
        "local": False,
        "key_url": "https://platform.moonshot.cn/console/api-keys",
        "desc": "Kimi 长上下文模型，最长 128K，适合长文档分析。新用户有免费额度。",
    },
    "minimax": {
        "name": "MiniMax（海螺 AI）",
        "base_url": "https://api.minimax.chat/v1",
        "models": ["MiniMax-Text-01", "abab6.5s-chat"],
        "default_model": "abab6.5s-chat",
        "local": False,
        "key_url": "https://www.minimaxi.com/user-center/basic-information",
        "desc": "MiniMax 开放平台，abab 系列对话模型。",
    },
    "hunyuan": {
        "name": "腾讯混元（免费额度）",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "models": ["hunyuan-turbos-latest", "hunyuan-lite", "hunyuan-vision-latest"],
        "default_model": "hunyuan-turbos-latest",
        "local": False,
        "key_url": "https://console.cloud.tencent.com/hunyuan/api-key",
        "desc": "腾讯混元大模型，OpenAI 兼容接口，新用户有免费调用额度。",
    },
    "qianfan": {
        "name": "百度千帆（免费额度）",
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": ["ernie-4.5-turbo-128k", "ernie-speed", "ernie-lite"],
        "default_model": "ernie-4.5-turbo-128k",
        "local": False,
        "key_url": "https://console.bce.baidu.com/qianfan/ais/console/apiKey",
        "desc": "百度智能云千帆平台，文心系列模型，注册即有免费额度。",
    },
    "together": {
        "name": "Together AI（含免费模型）",
        "base_url": "https://api.together.xyz/v1",
        "models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
                   "Qwen/Qwen2.5-72B-Instruct-Turbo",
                   "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"],
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        "local": False,
        "key_url": "https://api.together.ai/settings/api-keys",
        "desc": "Together AI 聚合推理平台，带 -Free 后缀的模型免费。",
    },
    "mistral": {
        "name": "Mistral AI（免费额度）",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-small-latest", "pixtral-12b-2409"],
        "default_model": "mistral-small-latest",
        "local": False,
        "key_url": "https://console.mistral.ai/api-keys",
        "desc": "Mistral 官方 API，pixtral 支持图片理解，有免费试用额度。",
    },
    "perplexity": {
        "name": "Perplexity（联网搜索）",
        "base_url": "https://api.perplexity.ai",
        "models": ["sonar", "sonar-pro"],
        "default_model": "sonar",
        "local": False,
        "key_url": "https://www.perplexity.ai/settings/api",
        "desc": "Perplexity 联网模型，回答自带引用来源，适合时事查询。",
    },
    "azure": {
        "name": "Azure OpenAI（企业）",
        "base_url": "",
        "models": [],
        "default_model": "",
        "local": False,
        "desc": "企业 Azure 部署：Base URL 填 https://{资源名}.openai.azure.com/openai/deployments/{部署名}，Key 填 Azure API Key。",
    },
    "ollama": {
        "name": "Ollama 本地模型（完全免费）",
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen2.5:7b", "deepseek-r1:7b", "llama3.1:8b",
                   "qwen2.5vl:7b", "llama3.2-vision:11b"],
        "default_model": "qwen2.5:7b",
        "local": True,
        "tags_url": "http://localhost:11434/api/tags",
        "desc": "本地运行，无需联网、无需 API Key。先安装 Ollama（ollama.com），再执行 ollama run qwen2.5:7b。",
    },
    "lmstudio": {
        "name": "LM Studio 本地（完全免费）",
        "base_url": "http://localhost:1234/v1",
        "models": [],
        "default_model": "",
        "local": True,
        "desc": "在 LM Studio 中加载模型并启动本地 OpenAI 兼容服务后即可使用。",
    },
    "modelscope_local": {
        "name": "魔塔本地模型 · GGUF（llama.cpp）",
        "base_url": "http://127.0.0.1:8080/v1",
        "models": [],
        "default_model": "",
        "local": True,
        "desc": "从阿里魔塔下载 GGUF 模型到本地，由 llama-server 加载（OpenAI 兼容）。"
                "在设置 → 本地模型页打开「模型库」下载与管理。",
    },
    "web_deepseek": {
        "name": "DeepSeek 网页版（浏览器接入）",
        "base_url": "https://chat.deepseek.com",
        "models": ["deepseek-chat（网页版）", "deepseek-reasoner（网页版）"],
        "default_model": "deepseek-chat（网页版）",
        "local": False,
        "web": True,
        "key_url": "https://chat.deepseek.com",
        "desc": "无需 API Key：通过浏览器打开 DeepSeek 网页版提问，"
                "免费额度 / R1 深度思考 / 联网搜索都能用。首次使用需在弹出的"
                "浏览器中登录一次（登录态自动持久化）。",
    },
    "web_zhipu": {
        "name": "智谱清言网页版（浏览器接入）",
        "base_url": "https://chatglm.cn",
        "models": ["glm-4（网页版）", "glm-4-plus（网页版）"],
        "default_model": "glm-4（网页版）",
        "local": False,
        "web": True,
        "key_url": "https://chatglm.cn",
        "desc": "无需 API Key：浏览器打开智谱清言网页版提问（GLM-4 免费额度 / "
                "联网搜索）。社区维护站点，选择器失效时可在设置 → 网页接入页"
                "的「选择器覆盖」中自救。",
    },
    "web_doubao": {
        "name": "豆包网页版（浏览器接入）",
        "base_url": "https://www.doubao.com",
        "models": ["doubao-pro（网页版）", "doubao-lite（网页版）"],
        "default_model": "doubao-pro（网页版）",
        "local": False,
        "web": True,
        "key_url": "https://www.doubao.com",
        "desc": "无需 API Key：浏览器打开豆包网页版提问（免费额度）。社区维护"
                "站点，选择器失效时可在设置 → 网页接入页的「选择器覆盖」中自救。",
    },
    "custom": {
        "name": "自定义 OpenAI 兼容接口",
        "base_url": "",
        "models": [],
        "default_model": "",
        "local": False,
        "desc": "任何 OpenAI 兼容的 /chat/completions 接口均可接入，填入 Base URL 与 Key 即可。",
    },
}

DEFAULT_CONFIG = {
    "provider": "lmstudio",            # v13.6：默认本地优先（LM Studio），开箱即用
    "base_urls": {},                 # 各提供商自定义 Base URL
    "api_keys": {},                  # 各提供商 API Key
    "models": {},                    # 各提供商当前选择的模型
    "temperature": 0.7,
    "top_p": 1.0,                    # Top-P 采样（1.0 = 不下发，由模型默认决定）
    "max_tokens": 4096,
    "reasoning_effort": "medium",    # 思考强度：off / low / medium / high（需模型支持）
    "context_window": 32768,         # 上下文大小（token 上限，超出自动裁剪历史）
    "system_prompt": "你是一个友善、聪明、干练的桌面 AI 助手，请用简洁清晰的中文回答。",
    "stream": True,
    "history_limit": 20,             # 携带的最近消息条数
    "deep_thinking": False,          # 深度思考：优先使用推理模型
    "auto_refresh_models": True,     # 启动时自动拉取最新模型列表
    "auto_route_model": False,       # v13.4：按本轮请求特征自动选模型（默认关，向后兼容）
    # v13.5：开发者调试 / 自动缩放 / 缓存策略（全部默认关闭，向后兼容）
    "debug_mode": False,
    "log_level": "INFO",
    "auto_ui_scale": False,
    "auto_clean_tmp": False,
    "library_auto": True,            # 资料库：提问时自动注入相关片段
    "model_overrides": {},           # {"provider|model": {temperature,top_p,max_tokens,reasoning_effort,context_window}}
    "model_cache": {},               # {provider: {"models": [...], "ts": ...}}
    "web_deepseek": {                # 网页版接入（浏览器 harness）
        "headless": False,           # 无头模式（登录后可用，不弹浏览器窗口）
        "timeout": 180,              # 单次回答最长等待秒数
        "profile_dir": "",           # 浏览器 profile 目录（默认 ~/.starry/browser/deepseek）
        "selectors": {},             # 自定义选择器（站点改版时覆盖默认值）
    },
    "web_zhipu": {                   # 智谱清言网页版（社区维护）
        "headless": False,
        "timeout": 180,
        "profile_dir": "",
        "selectors": {},
    },
    "web_doubao": {                  # 豆包网页版（社区维护）
        "headless": False,
        "timeout": 180,
        "profile_dir": "",
        "selectors": {},
    },
    "gateway": {                     # 模型网关（仪表盘）
        "route_policy": "auto",      # auto / fastest / manual
        "manual_provider": "",       # manual 策略下的目标服务商
        "keys": {},                  # {provider: [{"key","enabled"}]}
    },
    "mcp_servers": [],               # MCP 工具服务器（v7.3）：[{name, command, args, env, enabled}]
    "appearance": {
        "always_on_top": True,
        "theme": "light",            # light（翠绿·白，默认）/ sky（天蓝·白）/ dark（墨绿·夜）/ sky_dark（深蓝·夜）
        "font_size": 14,
        "ball_size": 56,
        "ball_position": None,       # [x, y]
        "window_position": None,     # [x, y]
        "window_size": [620, 860],
        "minimize_to_ball": True,
        # v13.7 主窗口背景自定义：空值 = 跟随主题毛玻璃
        "background_color": "",
        "background_image": "",
        "background_opacity": 35,      # 0-100，自定义色/图叠加强度
        "background_mode": "theme",    # theme / color / image
        "message_selection": False,   # 是否显示消息勾选框
    },
    # v13.6.5：栏目密度与布局迁移标记（一次性升级旧窗口尺寸）
    "ui_density": "宽松",
    "layout_version": 2,
    "ball_moods": True,           # v13.9：悬浮球不定时小表情
    # v15.0：本地 AI 工作室（LocModel 公开规格复刻）
    "local_studio": {
        "context": 8192,           # 8K / 16K / 32K / 64K
        "think_mode": False,
        "lan_access": False,
        # 非公开引擎需自行填写来源；llama.cpp 有官方直链无需填写
        "engine_urls": {},
        # 本地生成命令模板，占位符见 core/genstudio.render_command
        "generators": {},
    },
}


def is_android():
    """是否运行在 Android / Chaquopy 上。

    判据取自 Toga 0.5.7 ``toga/platform.py::get_current_platform`` 的官方做法：
    ``sys.getandroidapilevel`` 只在 Android 上存在。另加两个环境变量/路径兜底，
    覆盖部分裁剪过的 Chaquopy 运行时。
    """
    try:
        if hasattr(sys, "getandroidapilevel"):
            return True
    except Exception:                                    # noqa: BLE001
        pass
    return bool(os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"))


def _safe_makedirs(path):
    """逐级回退创建目录，**绝不向上抛 OSError**。

    v12.0 安卓闪退根因修复：v11.5 的 ``os.makedirs(path, exist_ok=True)``
    没有任何保护，一旦沙盒路径只读 / HOME 指向不可写位置 / 存储配额耗尽，
    异常会沿 ``AppConfig.load() -> StarryApp.startup()`` 冒泡到 Toga，
    进程直接被系统杀掉（用户看到的「安装后闪退」）。
    """
    candidates = [path]
    try:
        tmp = os.path.join(tempfile.gettempdir(), APP_ID)
        if os.path.normcase(tmp) != os.path.normcase(path):
            candidates.append(tmp)
    except Exception:                                    # noqa: BLE001
        pass
    try:
        candidates.append(os.path.join(os.getcwd(), ".starry-data", APP_ID))
    except Exception:                                    # noqa: BLE001
        pass
    last = path
    for candidate in candidates:
        last = candidate
        try:
            os.makedirs(candidate, exist_ok=True)
            if os.access(candidate, os.W_OK):
                return candidate
        except Exception:                                # noqa: BLE001
            continue
    return last


def get_config_dir():
    """返回配置文件目录（自动创建，永不抛异常）。

    桌面端优先级（v13.2 企业级修复）：
      0. ``STARRY_DATA_DIR`` —— **显式数据目录**，企业部署 / 便携模式 /
         多实例隔离 / 自动化测试专用。设置后直接作为配置目录使用，
         不再拼 APP_ID，也不再回退到用户真实 APPDATA。
         此前 Windows 分支只读 APPDATA、忽略该变量，导致「测试隔离」形同虚设，
         自动化会读写用户真实 config.json（含 API Key），属高风险缺陷。
      1. Windows：``%APPDATA%/<APP_ID>``；macOS：Application Support；
         Linux：``XDG_CONFIG_HOME`` 或 ``~/.config``。

    Android 优先级（保持原有语义，不受 STARRY_DATA_DIR 影响）：
      1. ``STARRY_CONFIG_DIR`` —— 由 Toga 的 ``app.paths.config`` 注入；
      2. ``HOME/.config``；
      3. ``tempfile.gettempdir()``。
    """
    if not is_android():
        override = os.environ.get("STARRY_DATA_DIR")
        if override:
            try:
                os.makedirs(override, exist_ok=True)
                if os.path.isdir(override) and os.access(override, os.W_OK):
                    return override
            except OSError:
                pass                      # 显式目录不可用时安全回退默认位置

    if is_android():
        injected = os.environ.get("STARRY_CONFIG_DIR")
        if injected and os.path.isdir(injected) and os.access(injected, os.W_OK):
            return _safe_makedirs(os.path.join(injected, APP_ID))
        home = os.environ.get("HOME")
        if home and os.path.isdir(home) and os.access(home, os.W_OK):
            return _safe_makedirs(os.path.join(home, ".config", APP_ID))
        return _safe_makedirs(os.path.join(tempfile.gettempdir(), APP_ID))

    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return _safe_makedirs(os.path.join(base, APP_ID))


def _deep_merge(base, override):
    result = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# 商业许可密钥校验（v7.5 安全：离线确定性校验，无网络、无新依赖）
# ---------------------------------------------------------------------------
# 设计目标：杜绝「在关于页随便填一串字符就冒充正版」的乱象。
# 采用与签发端一致的确定性算法（HMAC 思想的 hashlib 实现）：
#   - 密钥格式 XXXX-XXXX-XXXX-XXXX（16 位大写字母数字）
#   - 末 4 位 = sha256(固定盐 + 前 12 位)[:4].upper() 校验位
#   - 随机串因末 4 位大概率不匹配而被拒绝
# 说明：这是客户端软件的「防滥用」门槛，而非防逆向的硬墙；真正的正版
# 管控应由服务端按同样算法签发密钥。本实现让签发/校验两端自洽、可单测。
_LICENSE_SALT = b"starry-commercial-edition-2026"


def normalize_license_key(key):
    """去分隔符、转大写，得到纯 16 位字符串。"""
    return re.sub(r"[^A-Za-z0-9]", "", (key or "").upper())


def _license_checksum(head12):
    """由前 12 位计算出应有的末 4 位校验位（大写十六进制，落在 A-Z0-9 内）"""
    return hashlib.sha256(_LICENSE_SALT + head12.encode("utf-8")
                          ).hexdigest()[:4].upper()


def validate_license_key(key):
    """校验许可密钥格式与校验位。合法返回 True，任意伪造串返回 False。"""
    k = normalize_license_key(key)
    if len(k) != 16:
        return False
    return k[12:] == _license_checksum(k[:12])


def generate_license_key(rng=None):
    """按同样算法签发一个合法密钥（离线演示 / 自测用，生产应由服务端签发）"""
    import random
    r = rng or random
    head = "".join(r.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                   for _ in range(12))
    return "%s-%s-%s-%s" % (head[0:4], head[4:8], head[8:12],
                            _license_checksum(head))


def is_license_valid(config):
    """给定配置，判断已填密钥是否通过校验。"""
    key = (config.data.get("license_key") or "").strip()
    return bool(key) and validate_license_key(key)


class AppConfig:
    """应用配置（load/save + 各提供商键值管理）"""

    def __init__(self, data=None):
        self.data = _deep_merge(DEFAULT_CONFIG, data or {})
        # v7.3：企业商用合规字段（首次运行 EULA 同意 + 商业许可密钥）
        self.data.setdefault("accepted_eula", False)
        self.data.setdefault("eula_accept_token", "")      # v7.5：防篡改令牌
        self.data.setdefault("license_key", "")
        self.data.setdefault("license_verified", False)    # v7.5：密钥是否通过校验

    # ---------------- 持久化 ----------------
    @classmethod
    def load(cls):
        """加载配置；任何磁盘/解析/合并异常都退化为内存默认配置。

        v12.0：安卓端启动路径的硬性契约 —— ``load()`` 永不抛异常，
        因此 ``StarryApp.startup()`` 不会因为读配置而闪退。
        """
        try:
            path = os.path.join(get_config_dir(), "config.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return cls(json.load(f))
        except Exception:                                # noqa: BLE001
            pass
        return cls()

    def save(self):
        path = os.path.join(get_config_dir(), "config.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            # v7.5 安全：配置文件含 API Key / 许可密钥，限定仅本人可读写
            if os.name == "posix":
                try:
                    os.chmod(path, 0o600)
                except Exception:                       # noqa: BLE001
                    pass
        except Exception:
            pass

    # ---------------- 提供商 ----------------
    @property
    def provider(self):
        return self.data.get("provider", "lmstudio")

    def set_provider(self, key):
        self.data["provider"] = key if key in PROVIDERS else "custom"

    def provider_info(self, provider=None):
        return PROVIDERS.get(provider or self.provider, PROVIDERS["custom"])

    def base_url(self, provider=None):
        p = provider or self.provider
        return (self.data["base_urls"].get(p)
                or PROVIDERS.get(p, {}).get("base_url") or "").strip()

    def set_base_url(self, url, provider=None):
        p = provider or self.provider
        self.data["base_urls"][p] = (url or "").strip()

    def api_key(self, provider=None):
        p = provider or self.provider
        return (self.data["api_keys"].get(p) or "").strip()

    def set_api_key(self, key, provider=None):
        p = provider or self.provider
        self.data["api_keys"][p] = (key or "").strip()

    def model(self, provider=None):
        p = provider or self.provider
        saved = (self.data["models"].get(p) or "").strip()
        if saved:
            return saved
        preset = PROVIDERS.get(p, {}).get("default_model") or ""
        if preset:
            return preset
        # v13.6：LM Studio / 魔塔本地 / 自定义等服务商没有预设模型，
        # 回退到「获取模型列表」缓存里的首个模型，避免返回空模型名。
        entry = (self.data.get("model_cache") or {}).get(p) or {}
        cached = entry.get("models") if isinstance(entry, dict) else entry
        for m in (cached or []):
            if m and str(m).strip():
                return str(m).strip()
        return ""

    def set_model(self, model, provider=None):
        p = provider or self.provider
        self.data["models"][p] = model

    # ---------------- 模型级参数覆盖 ----------------
    @staticmethod
    def override_key(provider, model):
        return "%s|%s" % (provider, model)

    def override_key_current(self, provider=None):
        p = provider or self.provider
        return self.override_key(p, self.model(p))

    def get_override(self, provider=None, model=None):
        """取某模型的参数覆盖（无则空 dict）"""
        p = provider or self.provider
        m = model if model is not None else self.model(p)
        return dict(self.data.get("model_overrides", {}).get(
            self.override_key(p, m)) or {})

    def set_override(self, params, provider=None, model=None):
        p = provider or self.provider
        m = model if model is not None else self.model(p)
        self.data.setdefault("model_overrides", {})[
            self.override_key(p, m)] = dict(params or {})
        self.save()

    def clear_override(self, provider=None, model=None):
        p = provider or self.provider
        m = model if model is not None else self.model(p)
        self.data.get("model_overrides", {}).pop(self.override_key(p, m), None)
        self.save()

    def effective(self, name, provider=None, model=None):
        """取生效参数：模型级覆盖 > 全局值"""
        ov = self.get_override(provider, model)
        if name in ov and ov[name] is not None:
            return ov[name]
        return self.data.get(name)

    def is_local(self, provider=None):
        return bool(self.provider_info(provider).get("local"))

    def is_ready(self):
        """当前提供商是否已配置可用"""
        if not self.base_url() or not self.model():
            return False
        if self.is_local():
            return True
        return bool(self.api_key())

    # ---------------- 外观 ----------------
    @property
    def appearance(self):
        return self.data["appearance"]
