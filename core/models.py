# -*- coding: utf-8 -*-
"""模型注册中心：

- 免费模型标记（用于下拉框展示「免费」徽标）
- 推理模型 / 视觉模型识别（深度思考开关、图片自动切换）
- 模型列表后台刷新（自动更新免费模型）
- 本地 Ollama / LM Studio 自动探测
"""
import time

from PyQt5.QtCore import QThread, pyqtSignal

from core import api as api_mod
from core import apidiag
from core import apierrors

# ---------------------------------------------------------------------------
# 已知免费模型（各平台策略常变，此处为常见集合，仅用于徽标展示）
# ---------------------------------------------------------------------------
KNOWN_FREE = {
    "zhipu": {"glm-4-flash", "glm-4-flashx", "glm-4v-flash"},
    "siliconflow": {
        "Qwen/Qwen2.5-7B-Instruct",
        "Qwen/Qwen2.5-VL-7B-Instruct",
        "THUDM/glm-4-9b-chat",
        "Qwen/QwQ-32B",
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "internlm/internlm2_5-7b-chat",
    },
    "groq": None,        # Groq 全部模型均有免费额度
    "openrouter": None,  # 以 :free 后缀判断
    "ollama": None,      # 本地模型全部免费
    "lmstudio": None,
    "together": {"meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"},
}

# 推理（思考过程）模型
REASONING_MODELS = {
    "zhipu": ["glm-z1-air", "glm-z1-flash", "glm-z1-airx"],
    "siliconflow": ["Qwen/QwQ-32B", "Qwen/Qwen3-8B",
                    "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"],
    "deepseek": ["deepseek-reasoner"],
    "dashscope": ["qwq-plus", "qwq-32b", "qwq-32b-preview"],
    "groq": ["deepseek-r1-distill-llama-70b", "qwen-qwq-32b"],
    "openrouter": ["deepseek/deepseek-r1:free"],
    "ollama": ["deepseek-r1:7b", "deepseek-r1:8b", "deepseek-r1:14b",
               "qwq:32b", "qwq:latest"],
}

# 视觉（图片理解）模型
VISION_MODELS = {
    "zhipu": ["glm-4v-flash", "glm-4v", "glm-4v-plus"],
    "siliconflow": ["Qwen/Qwen2.5-VL-7B-Instruct", "Qwen/Qwen2.5-VL-32B-Instruct",
                    "Qwen/Qwen2-VL-7B-Instruct"],
    "dashscope": ["qwen-vl-max", "qwen-vl-plus", "qwen2-vl-7b-instruct",
                  "qwen2.5-vl-7b-instruct"],
    "groq": ["llama-3.2-11b-vision-preview", "llama-3.2-90b-vision-preview"],
    "openrouter": ["qwen/qwen-2.5-vl-7b-instruct:free"],
    "ollama": ["llama3.2-vision", "llama3.2-vision:11b", "qwen2.5vl",
               "qwen2.5vl:7b", "minicpm-v"],
    "hunyuan": ["hunyuan-vision-latest"],
    "mistral": ["pixtral-12b-2409", "pixtral-large-latest"],
}

_REASONING_HINTS = ("r1", "reasoner", "qwq", "z1", "thinking", "reasoning", "o1", "o3")
# 视觉模型名常见关键词（启发式，非官方参数）。
# 注意：minicpm5-1b 等纯文本模型不会命中其中任何一项（它是 "minicpm5"，
# 既不含 "minicpm-v" 也不含 "minicpmo"），因此仍正确判为「不支持图片」；
# 而 MiniCPM-V / MiniCPM-o、InternVL、CogVLM、LLaVA、Moondream、SmolVLM、
# Florence、Idefics、Qwen-VL / Qwen2-VL / Qwen2.5-VL、Pixtral 等可正确识别。
_VISION_HINTS = (
    "vl", "vision", "4v", "gpt-4o", "claude-3", "gemini",
    "minicpm-v", "minicpmo", "internvl", "cogvlm", "llava",
    "moondream", "phi-3-vision", "smolvlm", "florence", "idefics",
    "qwen-vl", "qwen2-vl", "qwen2.5-vl", "pixtral",
)


# v13.6：端点判定抽到零依赖的 core.endpoints（三端同源）。这里保留同名
# 包装函数，让设置页 / ModelFetcher 的 ``model_reg.resolve_endpoint`` 调用不变。
from core import endpoints as _endpoints  # noqa: E402


def normalize_base_url(url):
    return _endpoints.normalize_base_url(url)


def resolve_endpoint(provider_key, base_url="", info=None):
    return _endpoints.resolve_endpoint(provider_key, base_url, info)


def is_free_model(name, provider=None):
    """尽力而为地判断模型是否免费"""
    if not name:
        return False
    if name.endswith(":free"):
        return True
    known = KNOWN_FREE.get(provider or "", set())
    if known is None:                      # 该平台全部免费
        return True
    return name in known


def is_reasoning_model(name, provider=None):
    """是否为会返回思考过程的推理模型"""
    if not name:
        return False
    if provider and name in REASONING_MODELS.get(provider, []):
        return True
    low = name.lower()
    return any(h in low for h in _REASONING_HINTS)


def is_vision_model(name, provider=None):
    """是否为支持图片理解的视觉模型"""
    if not name:
        return False
    if provider and name in VISION_MODELS.get(provider, []):
        return True
    low = name.lower()
    return any(h in low for h in _VISION_HINTS)


def display_name(name, provider=None):
    """下拉框展示名（免费模型加徽标）"""
    return "%s（免费）" % name if is_free_model(name, provider) else name


def merge_models(*groups):
    """合并多组模型名：去重、保序、去空"""
    seen, out = set(), []
    for group in groups:
        for m in group or []:
            if m and m not in seen:
                seen.add(m)
                out.append(m)
    return out


def pick_models(models, provider, predicate):
    """按条件挑选模型（保持原顺序）"""
    return [m for m in (models or []) if predicate(m, provider)]


# ---------------------------------------------------------------------------
# 后台线程：拉取模型列表 / 探测本地服务
# ---------------------------------------------------------------------------
class ModelFetcher(QThread):
    """拉取服务商模型列表（OpenAI /models 或 Ollama /api/tags）。

    v13.2：新增 `failed_detail(dict)` 信号，把 `core.apierrors` 的结构化
    分类 / 建议 / 脱敏摘要传给 UI；原有 `failed(str)` 信号保持不变。
    """
    done = pyqtSignal(list)
    failed = pyqtSignal(str)
    failed_detail = pyqtSignal(dict)

    def __init__(self, base_url, api_key, is_ollama=False, tags_url="", parent=None):
        super().__init__(parent)
        self._base = base_url
        self._key = api_key
        self._ollama = is_ollama
        self._tags_url = tags_url

    def run(self):
        try:
            if self._ollama:
                models = api_mod.list_ollama_models(self._tags_url)
            else:
                models = api_mod.list_models(self._base, self._key)
            self.done.emit(models)
        except Exception as e:  # noqa: BLE001
            detail = getattr(e, "detail", None)
            if not isinstance(detail, dict) or not detail:
                detail = apierrors.from_exception(e, "model_fetch")
            apidiag.record("model_fetch", detail, scope="model_fetch")
            self.failed_detail.emit(detail)
            self.failed.emit(str(e))


class LocalProbe(QThread):
    """后台探测本地 Ollama / LM Studio / llama-server（魔塔 GGUF）是否在运行"""
    result = pyqtSignal(str, list)     # ("ollama"|"lmstudio"|"modelscope_local", models)
    finished_all = pyqtSignal()

    def run(self):
        try:
            models = api_mod.list_ollama_models(timeout=3)
            if models:
                self.result.emit("ollama", models)
        except Exception:
            pass
        try:
            models = api_mod.list_models("http://localhost:1234/v1", "", timeout=3)
            if models:
                self.result.emit("lmstudio", models)
        except Exception:
            pass
        try:
            from core import local_llm
            if local_llm.is_running(timeout=2):
                models = api_mod.list_models(local_llm.base_url(), "", timeout=3)
                if models:
                    self.result.emit("modelscope_local", models)
        except Exception:
            pass
        self.finished_all.emit()


# ---------------------------------------------------------------------------
# 配置中的模型缓存读写
# ---------------------------------------------------------------------------
def cache_get(cfg, provider):
    entry = (cfg.data.get("model_cache") or {}).get(provider) or {}
    return list(entry.get("models") or [])


def cache_put(cfg, provider, models):
    cfg.data.setdefault("model_cache", {})[provider] = {
        "models": list(models or []),
        "ts": int(time.time()),
    }


def cache_age_str(cfg, provider):
    entry = (cfg.data.get("model_cache") or {}).get(provider) or {}
    ts = entry.get("ts")
    if not ts:
        return ""
    minutes = max(0, int((time.time() - ts) / 60))
    if minutes < 1:
        return "刚刚更新"
    if minutes < 60:
        return "%d 分钟前更新" % minutes
    return "%d 小时前更新" % (minutes // 60)
