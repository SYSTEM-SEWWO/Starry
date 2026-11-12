# -*- coding: utf-8 -*-
"""模型管理控制器。

职责（从 AssistantApp 剥离的独立关注点）：
- 启动时用缓存立即填充模型下拉 → 后台拉取最新列表 → 探测本地服务
- 本地 Ollama / LM Studio 模型自动并入列表
- 携带图片时自动切换视觉模型；🧠 深度思考时切换 / 恢复推理模型

仅依赖 ChatWindow 的最小接口（set_models / show_hint / set_deep_thinking），
通过 settings_provider 回调访问设置对话框（避免循环引用）。
"""
from PyQt5.QtCore import QObject, QTimer

from core import models as model_reg
from core.config import PROVIDERS


class ModelController(QObject):
    """模型列表与自动切换的控制器（UI 线程内使用）"""

    def __init__(self, cfg, window, settings_provider=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.window = window
        self._settings_provider = settings_provider or (lambda: None)
        self._local_online = {"ollama": False, "lmstudio": False,
                              "modelscope_local": False}
        self._pre_deep_model = ""
        self._auto_deep_model = ""   # v13.6：记录「自动切换过去」的模型
        self._fetcher = None
        self._probe_thread = None
        self._local_timer = None
        # v13.2：启动自动刷新失败后静默降级 + 本次会话退避，避免反复打扰
        self._auto_refresh_disabled = False
        self._refresh_failures = 0
        self._last_failure = {}
        self._manual_refresh = False

    # ------------------------------------------------------------------
    # 启动时序
    # ------------------------------------------------------------------
    def init(self):
        """缓存填充 → 后台刷新 → 本地探测（周期）"""
        self.reload_combo()
        if self.cfg.data.get("auto_refresh_models", True):
            QTimer.singleShot(1200, self.refresh_models)
        QTimer.singleShot(500, self.probe_local)
        # 本地服务可能稍后启动，周期性探测
        self._local_timer = QTimer(self)
        self._local_timer.timeout.connect(self.probe_local)
        self._local_timer.start(60000)

    # ------------------------------------------------------------------
    # 模型下拉
    # ------------------------------------------------------------------
    def reload_combo(self):
        provider = self.cfg.provider
        info = self.cfg.provider_info()
        preset = list(info.get("models") or [])
        cached = model_reg.cache_get(self.cfg, provider)
        merged = model_reg.merge_models(preset, cached)
        display = [(model_reg.display_name(m, provider), m) for m in merged]
        self.window.set_models(display, self.cfg.model())
        settings = self._settings_provider()
        if settings is not None:
            settings.refresh_model_list()

    # ------------------------------------------------------------------
    # 云端模型列表刷新
    # ------------------------------------------------------------------
    def refresh_models(self, manual=False):
        """刷新模型列表。

        v13.2 修复「一开始就报错 HTTP 401」：
          * 启动自动刷新（manual=False）失败时**静默降级**——只写脱敏诊断，
            不再把 401 toast 弹到主界面打扰用户；
          * 失败后本次会话禁用自动刷新（退避），避免每次操作重复失败；
          * 只有用户在设置里**手动**点「测试连接 / 获取模型」才给出可操作提示。
        """
        self._manual_refresh = bool(manual)
        if self._auto_refresh_disabled and not manual:
            return
        # 启动时 model_controller.init() 与 assistant.py 各注册了一次定时刷新；
        # 已有请求在途时直接跳过，避免同一失效 Key 连打两次上游。
        running = getattr(self._fetcher, "isRunning", None)
        if self._fetcher is not None and callable(running) and running():
            return
        provider = self.cfg.provider
        info = self.cfg.provider_info()
        if info.get("local"):
            self.probe_local()
            return
        if not self.cfg.api_key():
            return
        fetcher = model_reg.ModelFetcher(
            self.cfg.base_url(), self.cfg.api_key(),
            is_ollama=False, parent=self)
        fetcher.done.connect(lambda models: self._on_models_refreshed(provider, models))
        # 向后兼容：v13.1 的调用方（含 selftest 的 FakeFetcher）可能只有
        # failed(str) 信号，缺少新增的 failed_detail(dict) 时不能崩。
        if hasattr(fetcher, "failed_detail"):
            fetcher.failed_detail.connect(self._on_models_failed_detail)
        fetcher.failed.connect(self._on_models_failed)
        fetcher.start()
        self._fetcher = fetcher

    def _on_models_failed_detail(self, detail):
        self._last_failure = dict(detail or {})
        self._refresh_failures += 1
        if not self._manual_refresh:
            self._auto_refresh_disabled = True       # 静默退避

    def _on_models_failed(self, err):
        from core import apierrors
        detail = self._last_failure or apierrors.from_exception(err, "model_fetch")
        if self._manual_refresh:
            self.window.show_hint(apierrors.one_line(detail))
        # 自动刷新失败：不 show_hint，详情已在「API 诊断」中可追溯
        self._last_failure = {}

    def retry_refresh(self):
        """供设置 / 诊断面板显式重试（解除本次会话的退避）。"""
        self._auto_refresh_disabled = False
        self.refresh_models(manual=True)

    def last_failure(self):
        """返回最近一次刷新的脱敏诊断（供 UI 展示）。"""
        return dict(self._last_failure)

    def _on_models_refreshed(self, provider, models):
        if not models:
            return
        preset = list(self.cfg.provider_info(provider).get("models") or [])
        merged = model_reg.merge_models(preset, models)
        model_reg.cache_put(self.cfg, provider, merged)
        self.cfg.save()
        if provider == self.cfg.provider:
            display = [(model_reg.display_name(m, provider), m) for m in merged]
            self.window.set_models(display, self.cfg.model())
            self.window.show_hint("模型列表已更新（%d 个）" % len(merged))

    # ------------------------------------------------------------------
    # 本地服务探测（Ollama / LM Studio）
    # ------------------------------------------------------------------
    def probe_local(self):
        probe = model_reg.LocalProbe(parent=self)
        probe.result.connect(self._on_local_detected)
        probe.start()
        self._probe_thread = probe

    def _on_local_detected(self, kind, models):
        if not models:
            return
        self._local_online[kind] = True
        PROVIDERS[kind]["models"] = model_reg.merge_models(
            PROVIDERS[kind].get("models"), models)
        if self.cfg.provider == kind:
            self.reload_combo()
            label = {"ollama": "Ollama", "lmstudio": "LM Studio",
                     "modelscope_local": "魔塔本地模型"}.get(kind, kind)
            self.window.show_hint("已连接本地 %s（%d 个模型）"
                                  % (label, len(models)))

    # ------------------------------------------------------------------
    # 视觉模型自动切换
    # ------------------------------------------------------------------
    def ensure_vision_model(self):
        """携带图片时，若当前模型不支持视觉则自动切换到可用的视觉模型。

        返回 ``True`` 表示「当前模型现在可以看图」（要么本来就能，要么已切换成功）；
        返回 ``False`` 表示模型池里没有任何可用的视觉模型，调用方需自行兜底
        （例如本地忽略图片，避免把图片发往不支持视觉的模型导致服务端 HTTP 400）。
        """
        provider = self.cfg.provider
        current = self.cfg.model()
        if model_reg.is_vision_model(current, provider):
            return True
        pool = model_reg.merge_models(self.cfg.provider_info().get("models"),
                                      model_reg.cache_get(self.cfg, provider))
        candidates = model_reg.pick_models(pool, provider, model_reg.is_vision_model)
        if not candidates:
            return False
        self.cfg.set_model(candidates[0])
        self.cfg.save()
        self.reload_combo()
        self.window.show_hint("检测到图片，已自动切换到视觉模型：%s" % candidates[0])
        return True

    # ------------------------------------------------------------------
    # 🧠 深度思考：推理模型切换 / 恢复
    # ------------------------------------------------------------------
    def set_deep_thinking(self, on):
        provider = self.cfg.provider
        info = self.cfg.provider_info()
        candidates = model_reg.pick_models(info.get("models"), provider,
                                           model_reg.is_reasoning_model)
        # 也考虑缓存中刷新到的模型
        cached = model_reg.pick_models(model_reg.cache_get(self.cfg, provider),
                                       provider, model_reg.is_reasoning_model)
        for m in cached:
            if m not in candidates:
                candidates.append(m)

        if on:
            if not candidates:
                self.window.set_deep_thinking(False)
                self.window.show_hint("当前服务商暂无推理模型，可在设置中切换服务商")
                return
            current = self.cfg.model()
            # v13.6：用户已手动选定推理模型时尊重其选择，不再强制改成第一个
            # 推理模型（旧行为会让「设置里改的模型」被立刻覆盖回去）。
            if model_reg.is_reasoning_model(current, provider):
                if not self._pre_deep_model:
                    self._pre_deep_model = current
                self.cfg.data["deep_thinking"] = True
                self.cfg.save()
                self.window.show_hint("保持当前推理模型：%s" % current)
                return
            self._pre_deep_model = current
            self._auto_deep_model = candidates[0]
            self.cfg.set_model(candidates[0])
            self.window.show_hint("已切换到推理模型：%s（将展示思考过程）" % candidates[0])
        else:
            current = self.cfg.model()
            auto = self._auto_deep_model
            restore = self._pre_deep_model or info.get("default_model") or ""
            # 仅当当前模型仍是「当初自动切换过去的那个」时才恢复，
            # 否则说明用户后来手动改过模型，不能覆盖。
            if restore and (not auto or current == auto) and restore != current:
                self.cfg.set_model(restore)
                self.window.show_hint("已切回模型：%s" % restore)
            self._auto_deep_model = ""
        self.cfg.data["deep_thinking"] = bool(on)
        self.cfg.save()
        self.reload_combo()
