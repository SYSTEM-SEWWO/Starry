# -*- coding: utf-8 -*-
"""显存智能分层规划（LocModel「AUTO TIERING」公开规格复刻）。

功能来源：https://locmodel.com/#tiering
  - 注意力层 / 共享部分 / KV 缓存按顺序放进显卡（越靠左越快）
  - 放不下的部分往后排：MoE 专家层进内存（保留 4 GB 给系统）
  - 再放不下才按需读取硬盘，用容量换速度
  - 按显卡**实际剩余**显存安排，避免显存不足借内存导致极慢
  - 不需要用户调参数

这是规划器（不直接操作模型加载器）：给出每一层放哪里、占用多少、
预计速度与警告，UI 直接展示。真实加载由 core/local_llm.py 执行。
"""
from core import hwprobe

# 各部件占模型体积的经验比例（用于规划展示，非精确张量统计）
_PART_RATIOS = [
    ("attention", "注意力 / 共享部分", 0.45),
    ("embed", "词嵌入 / 输出头", 0.15),
    ("kv", "KV 缓存", 0.15),
    ("experts", "MoE 专家", 0.25),
]
_NON_MOE_RATIOS = [
    ("attention", "注意力 / 共享部分", 0.60),
    ("embed", "词嵌入 / 输出头", 0.20),
    ("kv", "KV 缓存", 0.20),
]


def _usable(hw):
    gpu = float((hw or {}).get("vram_gb") or 0.0)
    # 预留 8% 显存给驱动 / 显示，避免刚好塞满导致 OOM
    gpu_usable = round(gpu * 0.92, 2)
    mem = (hw or {}).get("memory") or {}
    ram_total = float(mem.get("total_gb") or 0.0)
    ram_avail = float(mem.get("available_gb") or ram_total * 0.6 or 0.0)
    ram_usable = max(0.0, round(ram_avail - 4.0, 2))   # 固定保留 4 GB 给系统
    disk = float(((hw or {}).get("disk") or {}).get("free_gb") or 0.0)
    disk_usable = max(0.0, round(disk - 1.0, 2))       # 预留 1 GB
    return gpu_usable, ram_usable, disk_usable


def plan(model_gb, hw=None, reserve_ram_gb=4.0, moe=False, ctx_tokens=8192):
    """生成分层方案。

    model_gb: 模型文件体积（GB）
    hw: hwprobe.probe() 结果；None 时现场探测
    reserve_ram_gb: 给系统保留的内存（LocModel 默认 4 GB）
    moe: 是否 MoE 专家模型
    ctx_tokens: 上下文长度，会按比例微调 KV 缓存
    """
    hw = hw or hwprobe.probe()
    try:
        size = max(0.0, float(model_gb))
    except (TypeError, ValueError):
        size = 0.0
    gpu_total, ram_avail, disk_free = _usable(hw)
    ram_usable = max(0.0, ram_avail - (reserve_ram_gb - 4.0))

    ratios = _PART_RATIOS if moe else _NON_MOE_RATIOS
    ctx_factor = 1.0 + max(0, int(ctx_tokens or 8192) / 65536.0)
    parts = []
    for key, label, ratio in ratios:
        gb = size * ratio * (ctx_factor if key == "kv" else 1.0)
        parts.append({"key": key, "label": label, "gb": round(gb, 2),
                      "device": "", "note": ""})

    gpu_left, ram_left, disk_left = gpu_total, ram_usable, disk_free
    warnings = []
    for p in parts:
        need = p["gb"]
        if need <= gpu_left + 0.01:
            p["device"] = "gpu"
            p["note"] = "显卡（最快）"
            gpu_left -= need
        elif need <= ram_left + 0.01:
            p["device"] = "ram"
            p["note"] = "内存（保留 %g GB 给系统）" % reserve_ram_gb
            ram_left -= need
            warnings.append("%s 放到内存，速度会下降" % p["label"])
        elif need <= disk_left + 0.01:
            p["device"] = "disk"
            p["note"] = "硬盘按需读取（容量换速度）"
            disk_left -= need
            warnings.append("%s 需要硬盘读取，首载与速度明显变慢" % p["label"])
        else:
            p["device"] = "none"
            p["note"] = "资源不足，无法放置"
            warnings.append("%s 无足够空间" % p["label"])

    def used(dev):
        return round(sum(p["gb"] for p in parts if p["device"] == dev), 2)

    gpu_used, ram_used, disk_used = used("gpu"), used("ram"), used("disk")
    backend = (hw.get("backends") or ["CPU"])[0]
    # 估算：显卡放得越多越快；一旦溢出到内存/磁盘按惩罚系数降速
    tps = hwprobe.estimate_speed(max(1.0, size / 2.0), gpu_total, backend, size)
    penalty = (1.0 - min(0.8, ram_used / max(size, 0.1) * 0.45)
               - min(0.5, disk_used / max(size, 0.1) * 0.85))
    tps = round(max(0.5, tps * max(0.05, penalty)), 1)

    return {
        "model_gb": size, "moe": bool(moe), "ctx_tokens": int(ctx_tokens or 8192),
        "gpu": {"total_gb": round(gpu_total, 2), "used_gb": gpu_used,
                "left_gb": round(gpu_left, 2)},
        "ram": {"usable_gb": round(ram_usable, 2), "used_gb": ram_used,
                "left_gb": round(ram_left, 2), "reserve_gb": reserve_ram_gb},
        "disk": {"usable_gb": round(disk_free, 2), "used_gb": disk_used,
                 "left_gb": round(disk_left, 2)},
        "parts": parts, "warnings": warnings, "tps_estimate": tps,
        "ok": all(p["device"] != "none" for p in parts),
        "estimate": True,
    }


def format_plan(result):
    """分层方案可读文本（UI 直接显示）。"""
    if not result:
        return "尚未生成分层方案"
    lines = [
        "模型 %.1f GB · %s · 上下文 %d" % (
            result["model_gb"], "MoE" if result["moe"] else "稠密",
            result["ctx_tokens"]),
        "显卡：%.1f / %.1f GB（剩余 %.1f）" % (
            result["gpu"]["used_gb"], result["gpu"]["total_gb"],
            result["gpu"]["left_gb"]),
        "内存：%.1f / %.1f GB（预留 %.0f GB 给系统）" % (
            result["ram"]["used_gb"], result["ram"]["usable_gb"],
            result["ram"]["reserve_gb"]),
        "硬盘：%.1f / %.1f GB（按需读取）" % (
            result["disk"]["used_gb"], result["disk"]["usable_gb"]),
        "预计速度：约 %s tok/s（估算，非实测）" % result["tps_estimate"],
        "",
        "分层明细：",
    ]
    for p in result["parts"]:
        lines.append("  · %-18s %6.2f GB → %s" % (
            p["label"], p["gb"], p["note"]))
    if result["warnings"]:
        lines.append("")
        lines.append("提示：")
        lines.extend("  ! " + w for w in result["warnings"])
    return "\n".join(lines)
