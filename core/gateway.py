# -*- coding: utf-8 -*-
"""模型网关（Gateway）后端 —— 统一观测与管理所有模型通道。

职责（仪表盘的「发动机」）：
    GatewayStats   请求统计：记录每次调用（服务商/模型/耗时/token/成败），
                   持久化到 ~/.starry/gateway_stats.json，提供汇总、
                   最近流水、分钟级时序（供仪表盘折线图）
    KeyPool        密钥池：每服务商多 Key 轮询 + 失败退避冻结，支撑
                   高可用与额度分担
    check_provider 健康检查：轻量探活各服务商（GET /models）
    check_providers_parallel 并行探活（v7：8 并发，最坏 76s → 约 12s）
    budget_status 用量预算：每日 token 预算消耗与预警等级（v7）
    route_pick     路由策略：自动（默认）/ 最低延迟 / 指定服务商

说明：统计与路由都是「旁路」设计——不拦截请求，失败时静默降级，
绝不影响主对话链路。
"""
import json
import os
import threading
import time

import requests

STATS_VERSION = 1
MAX_RECORDS = 5000            # 流水保留上限
MAX_AGE_DAYS = 7              # 流水保留天数


def _data_dir():
    """网关统计 / 预算的数据目录（v12.0：支持显式注入，默认行为不变）。

    历史实现固定为 ``~/.starry``。在 Windows 上 ``os.path.expanduser("~")``
    读的是 ``USERPROFILE``，测试里常用的 ``HOME`` 隔离对它无效，导致自测
    读到真实用户目录里累积的历史统计，网关 / 预算类断言大面积失败。
    新增 ``STARRY_DATA_DIR`` 作为**可选**注入点（与 v12.0 的
    ``STARRY_CONFIG_DIR`` 同构）：未设置时路径与旧版逐字一致，
    不迁移、不影响任何现有用户数据。
    """
    injected = os.environ.get("STARRY_DATA_DIR")
    if injected:
        return injected
    return os.path.join(os.path.expanduser("~"), ".starry")


def _stats_path():
    return os.path.join(_data_dir(), "gateway_stats.json")


def _now():
    return time.time()


def _fmt_tokens(n):
    n = int(n or 0)
    if n >= 1000:
        return "%.1fK" % (n / 1000.0)
    return str(n)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
class GatewayStats:
    """请求统计单例（线程安全，JSON 持久化）"""

    _instance = None
    _cls_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {"version": STATS_VERSION, "records": []}

    # -- 单例 -------------------------------------------------------------
    @classmethod
    def instance(cls):
        with cls._cls_lock:
            if cls._instance is None:
                inst = cls()
                inst.load()
                cls._instance = inst
            return cls._instance

    # -- 持久化 -----------------------------------------------------------
    def load(self):
        path = _stats_path()
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and \
                        isinstance(data.get("records"), list):
                    self._data = data
        except Exception:                          # noqa: BLE001
            self._data = {"version": STATS_VERSION, "records": []}
        self._prune()

    def save(self):
        path = _stats_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:                          # noqa: BLE001
            pass

    def _prune(self):
        cutoff = _now() - MAX_AGE_DAYS * 86400
        recs = [r for r in self._data.get("records", [])
                if float(r.get("ts", 0) or 0) >= cutoff]
        self._data["records"] = recs[-MAX_RECORDS:]

    # -- 记录 -------------------------------------------------------------
    def record(self, provider, model, ok, latency_ms=0, tokens=0, error=""):
        rec = {
            "ts": _now(),
            "provider": provider or "",
            "model": model or "",
            "ok": bool(ok),
            "latency": int(latency_ms or 0),
            "tokens": int(tokens or 0),
            "error": (error or "")[:160],
        }
        with self._lock:
            self._data.setdefault("records", []).append(rec)
            self._prune()
            self.save()
        return rec

    # -- 查询 -------------------------------------------------------------
    def records(self, limit=None):
        with self._lock:
            recs = list(self._data.get("records", []))
        recs.reverse()                             # 最新在前
        return recs[:limit] if limit else recs

    def summary(self):
        """按服务商汇总：请求数 / 成功率 / 平均延迟 / token / 最近错误"""
        with self._lock:
            recs = list(self._data.get("records", []))
        day_ago = _now() - 86400
        out = {}
        for r in recs:
            p = r.get("provider") or "unknown"
            d = out.setdefault(p, {
                "requests": 0, "ok": 0, "fail": 0,
                "today": 0, "latency_sum": 0, "latency_n": 0,
                "tokens": 0, "last_error": "", "last_ts": 0,
            })
            d["requests"] += 1
            if r.get("ok"):
                d["ok"] += 1
            else:
                d["fail"] += 1
                d["last_error"] = r.get("error") or "未知错误"
            if float(r.get("ts", 0) or 0) >= day_ago:
                d["today"] += 1
            lat = int(r.get("latency", 0) or 0)
            if lat > 0:
                d["latency_sum"] += lat
                d["latency_n"] += 1
            d["tokens"] += int(r.get("tokens", 0) or 0)
            d["last_ts"] = max(d["last_ts"], float(r.get("ts", 0) or 0))
        for d in out.values():
            d["avg_latency"] = (d["latency_sum"] // d["latency_n"]
                                if d["latency_n"] else 0)
            d["success_rate"] = (d["ok"] / d["requests"]) if d["requests"] else 0
        return out

    def overall(self):
        s = self.summary()
        total = sum(d["requests"] for d in s.values())
        ok = sum(d["ok"] for d in s.values())
        lat = [d["avg_latency"] for d in s.values() if d["avg_latency"] > 0]
        tokens = sum(d["tokens"] for d in s.values())
        today = sum(d["today"] for d in s.values())
        return {
            "requests": total, "today": today,
            "success_rate": (ok / total) if total else 0,
            "avg_latency": int(sum(lat) / len(lat)) if lat else 0,
            "tokens": tokens, "tokens_str": _fmt_tokens(tokens),
            "providers": len(s),
        }

    def series(self, minutes=60, buckets=None):
        """分钟级时序：[{"t": 分钟起点, "n": 请求数, "lat": 平均延迟}]"""
        buckets = buckets or minutes
        with self._lock:
            recs = list(self._data.get("records", []))
        now = _now()
        span = 60.0 * minutes
        start = now - span
        size = span / float(buckets)
        acc = [None] * buckets
        for r in recs:
            ts = float(r.get("ts", 0) or 0)
            if ts < start:
                continue
            idx = int((ts - start) / size)
            if idx >= buckets:
                idx = buckets - 1
            b = acc[idx]
            if b is None:
                b = acc[idx] = {"n": 0, "lat_sum": 0, "lat_n": 0}
            b["n"] += 1
            lat = int(r.get("latency", 0) or 0)
            if lat > 0:
                b["lat_sum"] += lat
                b["lat_n"] += 1
        out = []
        for i in range(buckets):
            b = acc[i] or {"n": 0, "lat_sum": 0, "lat_n": 0}
            out.append({
                "t": start + i * size,
                "n": b["n"],
                "lat": (b["lat_sum"] // b["lat_n"]) if b["lat_n"] else 0,
            })
        return out


# ---------------------------------------------------------------------------
# 密钥池
# ---------------------------------------------------------------------------
class KeyPool:
    """多密钥轮询 + 失败退避。

    keys 结构（存配置 cfg.data["gateway"]["keys"]）：
        {provider: [{"key": "sk-...", "enabled": true}, ...]}
    轮询：round-robin 跳过禁用与冻结项；全部不可用时返回 None（回退主 Key）。
    退避：单 key 连续失败 cooldown_after 次后冻结 cooldown_secs 秒。
    """

    def __init__(self, cfg=None, cooldown_after=2, cooldown_secs=120):
        self._cfg = cfg
        self._cooldown_after = cooldown_after
        self._cooldown_secs = cooldown_secs
        self._fails = {}                # key -> 连续失败次数
        self._frozen_until = {}         # key -> 解冻时间戳
        self._rr = {}                   # provider -> 轮询游标
        self._lock = threading.Lock()

    # -- 配置读写 ---------------------------------------------------------
    def _keys_of(self, provider):
        if self._cfg is None:
            return []
        gw = (self._cfg.data.get("gateway") or {})
        return list((gw.get("keys") or {}).get(provider) or [])

    def _save_keys(self, provider, items):
        if self._cfg is None:
            return
        gw = self._cfg.data.setdefault("gateway", {})
        gw.setdefault("keys", {})[provider] = items
        try:
            self._cfg.save()
        except Exception:                          # noqa: BLE001
            pass

    def add_key(self, provider, key):
        key = (key or "").strip()
        if not key:
            return False
        items = self._keys_of(provider)
        if any(i.get("key") == key for i in items):
            return False
        items.append({"key": key, "enabled": True})
        self._save_keys(provider, items)
        return True

    def remove_key(self, provider, key):
        items = [i for i in self._keys_of(provider) if i.get("key") != key]
        self._save_keys(provider, items)

    def set_enabled(self, provider, key, enabled):
        items = self._keys_of(provider)
        for i in items:
            if i.get("key") == key:
                i["enabled"] = bool(enabled)
        self._save_keys(provider, items)

    def list_keys(self, provider):
        """返回 [(key, enabled, available)]；available 综合禁用与冻结状态"""
        now = _now()
        out = []
        for i in self._keys_of(provider):
            k = i.get("key") or ""
            frozen = self._frozen_until.get(k, 0) > now
            out.append((k, bool(i.get("enabled", True)),
                        bool(i.get("enabled", True)) and not frozen))
        return out

    # -- 轮询 -------------------------------------------------------------
    def next_key(self, provider):
        """取下一个可用 key；无可用返回 None（调用方回退主 Key）"""
        now = _now()
        items = [i.get("key") for i in self._keys_of(provider)
                 if i.get("enabled", True)]
        items = [k for k in items if self._frozen_until.get(k, 0) <= now]
        if not items:
            return None
        with self._lock:
            cur = self._rr.get(provider, 0) % len(items)
            self._rr[provider] = cur + 1
            return items[cur]

    def report(self, provider, key, ok):
        """上报调用结果：累计失败 → 冻结退避"""
        if not key:
            return
        with self._lock:
            if ok:
                self._fails[key] = 0
                self._frozen_until.pop(key, None)
            else:
                n = self._fails.get(key, 0) + 1
                self._fails[key] = n
                if n >= self._cooldown_after:
                    self._frozen_until[key] = _now() + self._cooldown_secs
                    self._fails[key] = 0

    def frozen_info(self, provider):
        """冻结中的 key 及剩余秒数（仪表盘展示）"""
        now = _now()
        out = []
        for k, until in self._frozen_until.items():
            if until > now and k in [i.get("key") for i in self._keys_of(provider)]:
                out.append((k, int(until - now)))
        return out


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
def check_provider(pinfo, api_key="", timeout=8):
    """轻量探活一个服务商。

    pinfo: PROVIDERS[provider] 字典。返回 (status, detail)：
        "unconfigured"  未配置（无 Key 或本地服务未起）
        "online"        正常
        "limited"       可访问但异常（限流/权限）
        "error"         不可达
    """
    base = (pinfo or {}).get("base_url") or ""
    if not base:
        return "unconfigured", "未配置 Base URL"
    if (pinfo or {}).get("local"):
        try:
            r = requests.get(base.rstrip("/") + "/models", timeout=timeout)
            if r.status_code == 200:
                return "online", "本地服务正常"
            return "error", "HTTP %d" % r.status_code
        except requests.RequestException:
            return "unconfigured", "本地服务未启动"
    if not api_key:
        return "unconfigured", "未填写 API Key"
    try:
        r = requests.get(base.rstrip("/") + "/models",
                         headers={"Authorization": "Bearer " + api_key},
                         timeout=timeout)
    except requests.RequestException as e:
        return "error", "连接失败：%s" % str(e)[:80]
    if r.status_code == 200:
        return "online", "正常"
    if r.status_code in (401, 403):
        return "error", "Key 无效或无权限"
    if r.status_code == 429:
        return "limited", "额度受限（429）"
    return "limited", "HTTP %d" % r.status_code


def check_providers_parallel(providers, timeout=4, max_workers=8,
                             on_done=None, should_stop=None):
    """并行探活多个服务商（v7：O-1 修复）。

    providers: [(provider_key, pinfo, api_key), ...]
    on_done(provider_key, status, detail, done, total)：每完成一个回调一次
        （在 worker 线程调用，UI 侧需自行切线程/排队）
    返回 {provider_key: (status, detail)}。
    最坏耗时 ≈ ceil(N / max_workers) × timeout，19 家 × 4s 串行 76s →
    8 并发约 12s。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(providers)
    results = {}
    if not total:
        return results
    done_box = {"n": 0}
    done_lock = threading.Lock()

    def _work(item):
        key, pinfo, api_key = item
        return key, check_provider(pinfo, api_key, timeout=timeout)

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, total))) as ex:
        futures = {ex.submit(_work, it): it[0] for it in providers}
        for fut in as_completed(futures):
            if should_stop and should_stop():
                for f in futures:
                    f.cancel()
                break
            try:
                key, res = fut.result()
            except Exception as e:                  # noqa: BLE001
                key, res = futures[fut], ("error", "检查异常：%s" % str(e)[:60])
            results[key] = res
            if on_done:
                with done_lock:
                    done_box["n"] += 1
                    n = done_box["n"]
                try:
                    on_done(key, res[0], res[1], n, total)
                except Exception:                    # noqa: BLE001
                    pass
    return results


# ---------------------------------------------------------------------------
# 用量预算（v7 创新）
# ---------------------------------------------------------------------------
BUDGET_WARN = 0.8          # 消耗 80% 预警
BUDGET_LEVELS = ("ok", "warn", "over")


def _budgets_path():
    return os.path.join(_data_dir(), "gateway_budgets.json")


def load_budgets():
    """读取每日 token 预算配置：{provider: daily_tokens}"""
    try:
        with open(_budgets_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): int(v or 0) for k, v in data.items() if int(v or 0) > 0}
    except Exception:                              # noqa: BLE001
        pass
    return {}


def save_budgets(budgets):
    try:
        os.makedirs(os.path.dirname(_budgets_path()), exist_ok=True)
        tmp = _budgets_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(budgets, f, ensure_ascii=False)
        os.replace(tmp, _budgets_path())
        return True
    except Exception:                              # noqa: BLE001
        return False


def budget_status(summary=None, budgets=None):
    """按服务商计算预算消耗。

    返回 {provider: {"used": 今日token, "budget": 预算, "ratio": 0-1+,
                     "level": "ok"/"warn"/"over"}}；未设预算的服务商不出现在结果里。
    """
    if summary is None:
        summary = GatewayStats.instance().summary()
    if budgets is None:
        budgets = load_budgets()
    out = {}
    if not budgets:
        return out
    day_ago = _now() - 86400
    recs = GatewayStats.instance().records()
    today_tokens = {}
    for r in recs:
        if float(r.get("ts", 0) or 0) >= day_ago:
            p = r.get("provider") or ""
            today_tokens[p] = today_tokens.get(p, 0) + int(r.get("tokens", 0) or 0)
    for p, b in budgets.items():
        if b <= 0:
            continue
        used = today_tokens.get(p, 0)
        ratio = (used / float(b)) if b else 0.0
        level = "ok"
        if ratio >= 1.0:
            level = "over"
        elif ratio >= BUDGET_WARN:
            level = "warn"
        out[p] = {"used": used, "budget": b,
                  "ratio": round(ratio, 4), "level": level}
    return out


# ---------------------------------------------------------------------------
# 路由策略
# ---------------------------------------------------------------------------
ROUTE_POLICIES = {
    "auto": "自动（默认服务商）",
    "fastest": "最低延迟（按网关统计自动选）",
    "manual": "手动指定",
}


def route_pick(policy, summary, manual_provider=None, current=None):
    """按路由策略挑选实际使用的服务商 key。

    summary: GatewayStats.summary() 结果
    返回 provider key 或 None（表示用当前默认）。
    """
    if policy == "fastest" and summary:
        cands = [p for p, d in summary.items()
                 if d.get("avg_latency", 0) > 0 and d.get("ok", 0) > 0]
        if cands:
            return min(cands, key=lambda p: summary[p]["avg_latency"])
        return None
    if policy == "manual" and manual_provider:
        return manual_provider
    return None
