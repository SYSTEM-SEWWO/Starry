# -*- coding: utf-8 -*-
"""硬件体检与模型推荐（LocModel「HARDWARE」公开规格复刻）。

功能来源：https://locmodel.com/#hardware
  - 显卡型号与显存、CPU 核心、可用内存、模型盘空间一次看清
  - 自动识别 NVIDIA CUDA / AMD / Intel / CPU 四种后端
  - 按显存和内存推荐能流畅运行的模型，启动前看到速度与首次加载时间

实现为纯 Python：psutil / nvidia-smi 可选，缺失时走平台命令降级，
任何探测失败都返回明确错误信息，不臆造硬件参数。
所有 tok/s 均为**启发式估算**（界面必须标注"估算"），不是实测值。
"""
import ctypes
import os
import platform
import re
import subprocess
import sys

try:
    import psutil
except Exception:                                  # pragma: no cover - 可选依赖
    psutil = None

try:
    import winreg
except Exception:                                  # 非 Windows
    winreg = None

from core.config import get_config_dir

_UNKNOWN = "未知"


def _run(cmd, timeout=4):
    """安全执行只读探测命令，失败返回空串（绝不抛错给 UI）。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, shell=False)
        return (p.stdout or "").strip()
    except Exception:
        return ""


def _to_gb(value, unit="MB"):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    u = unit.upper()
    if u.startswith("MB"):
        return round(v / 1024.0, 1)
    if u.startswith("KB"):
        return round(v / 1024.0 / 1024.0, 1)
    if u.startswith("B"):
        return round(v / 1024.0 / 1024.0 / 1024.0, 1)
    return round(v, 1)


def platform_key():
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


# ---------------------------------------------------------------------------
# 显卡
# ---------------------------------------------------------------------------
def detect_gpus():
    """返回显卡列表 [{name, vram_gb, vendor, backend, source}]。"""
    out = []
    key = platform_key()

    if key == "win":
        # 注册表读取显卡（不依赖 wmic —— 本机安全策略可能拦截该命令）
        if winreg is not None:
            base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            try:
                root_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
                idx = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(root_key, idx)
                    except OSError:
                        break
                    idx += 1
                    if not sub_name.isdigit():
                        continue
                    try:
                        sk = winreg.OpenKey(root_key, sub_name)
                        name = str(winreg.QueryValueEx(sk, "DriverDesc")[0])
                        vram = 0.0
                        try:
                            raw = winreg.QueryValueEx(
                                sk, "HardwareInformation.qwMemorySize")[0]
                            vram = _to_gb(raw, "B")
                        except OSError:
                            try:
                                raw = winreg.QueryValueEx(
                                    sk, "HardwareInformation.MemorySize")[0]
                                vram = _to_gb(raw, "B")
                            except OSError:
                                pass
                        vendor = ("NVIDIA" if re.search(r"NVIDIA", name, re.I) else
                                  "AMD" if re.search(r"AMD|Radeon", name, re.I) else
                                  "Intel" if re.search(r"Intel|Iris|Arc", name, re.I)
                                  else _UNKNOWN)
                        backend = {"NVIDIA": "CUDA", "AMD": "Vulkan/ROCm",
                                   "Intel": "Intel"}.get(vendor, "CPU")
                        out.append({"name": name, "vram_gb": vram,
                                    "vendor": vendor, "backend": backend,
                                    "source": "注册表"})
                    except OSError:
                        continue
                winreg.CloseKey(root_key)
            except OSError:
                pass
        # nvidia-smi 提供精确显存（可选，失败静默降级；黑名单拦截也不影响）
        smi = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits"])
        for i, line in enumerate(smi.splitlines()):
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 2:
                continue
            name, vram = parts[0], _to_gb(parts[1])
            match = next((g for g in out if g["name"] == name), None)
            if match:
                match["vram_gb"] = vram
                match["source"] += "+nvidia-smi"
            else:
                out.append({"name": name, "vram_gb": vram, "vendor": "NVIDIA",
                            "backend": "CUDA", "source": "nvidia-smi"})

    elif key == "linux":
        lspci = _run(["lspci", "-nn"])
        for line in lspci.splitlines():
            if not re.search(r"VGA|3D controller|Display controller", line, re.I):
                continue
            name = line.split(": ", 1)[-1].split(" (")[0]
            vendor = ("NVIDIA" if re.search(r"NVIDIA", line, re.I) else
                      "AMD" if re.search(r"AMD|ATI", line, re.I) else
                      "Intel" if re.search(r"Intel", line, re.I) else _UNKNOWN)
            backend = {"NVIDIA": "CUDA", "AMD": "Vulkan/ROCm",
                       "Intel": "Intel"}.get(vendor, "CPU")
            out.append({"name": name, "vram_gb": 0.0, "vendor": vendor,
                        "backend": backend, "source": "lspci"})
        smi = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits"])
        for i, line in enumerate(smi.splitlines()):
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 2 and i < len(out):
                out[i]["vram_gb"] = _to_gb(parts[1])

    else:  # macOS
        sp = _run(["system_profiler", "SPDisplaysDataType"])
        for block in re.split(r"\n\s*\n", sp):
            if "Chipset Model:" not in block and "Vendor:" not in block:
                continue
            m = re.search(r"Chipset Model:\s*(.+)", block)
            name = m.group(1).strip() if m else _UNKNOWN
            vendor = ("Apple" if re.search(r"Apple", name, re.I) else
                      "NVIDIA" if re.search(r"NVIDIA", name, re.I) else
                      "AMD" if re.search(r"AMD|Radeon", name, re.I) else _UNKNOWN)
            out.append({"name": name, "vram_gb": 0.0, "vendor": vendor,
                        "backend": "Metal" if vendor == "Apple" else
                        {"NVIDIA": "CUDA", "AMD": "Vulkan"}.get(vendor, "CPU"),
                        "source": "system_profiler"})

    if not out:
        out.append({"name": _UNKNOWN + "（按 CPU 运行）", "vram_gb": 0.0,
                    "vendor": "CPU", "backend": "CPU", "source": "fallback"})
    return out


def detect_backends(gpus=None):
    """可用推理后端列表（LocModel 四种：CUDA / Vulkan / Intel / CPU）。"""
    gpus = gpus or detect_gpus()
    names = " ".join(g.get("backend", "") for g in gpus).lower()
    out = ["CPU"]
    if "cuda" in names:
        out.insert(0, "CUDA")
    if "vulkan" in names or "rocm" in names:
        out.insert(0, "Vulkan")
    if "intel" in names:
        out.insert(0, "Intel")
    if "metal" in names:
        out.insert(0, "Metal")
    # 去重保持顺序
    seen, uniq = set(), []
    for b in out:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    return uniq


# ---------------------------------------------------------------------------
# CPU / 内存 / 磁盘
# ---------------------------------------------------------------------------
def detect_cpu():
    """{name, cores, threads, source}"""
    name, cores = platform.processor() or _UNKNOWN, (os.cpu_count() or 1)
    if platform_key() == "win" and winreg is not None:
        try:
            k = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            name = str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
            winreg.CloseKey(k)
        except OSError:
            pass
    elif platform_key() == "linux":
        raw = ""
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
        except Exception:
            pass
        m = re.search(r"model name\s*:\s*(.+)", raw)
        if m:
            name = m.group(1).strip()
    else:
        raw = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if raw:
            name = raw
    return {"name": name, "cores": cores, "threads": cores,
            "source": "platform"}


def detect_memory():
    """{total_gb, available_gb, source}"""
    if psutil is not None:
        vm = psutil.virtual_memory()
        return {"total_gb": round(vm.total / 1024 ** 3, 1),
                "available_gb": round(vm.available / 1024 ** 3, 1),
                "source": "psutil"}
    key = platform_key()
    if key == "linux":
        total = avail = 0.0
        try:
            for line in open("/proc/meminfo", encoding="utf-8", errors="ignore"):
                if line.startswith("MemTotal:"):
                    total = _to_gb(line.split()[1], "KB")
                elif line.startswith("MemAvailable:"):
                    avail = _to_gb(line.split()[1], "KB")
        except Exception:
            pass
        if total:
            return {"total_gb": total, "available_gb": avail, "source": "/proc"}
    if key == "win":
        # GlobalMemoryStatusEx（纯 ctypes，不依赖被拦截的 wmic）
        class MEMORYSTATUS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        try:
            st = MEMORYSTATUS()
            st.dwLength = ctypes.sizeof(MEMORYSTATUS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            if st.ullTotalPhys:
                return {"total_gb": _to_gb(st.ullTotalPhys, "B"),
                        "available_gb": _to_gb(st.ullAvailPhys, "B"),
                        "source": "GlobalMemoryStatusEx"}
        except Exception:
            pass
    return {"total_gb": 0.0, "available_gb": 0.0, "source": _UNKNOWN}


def detect_disk(path=None):
    """{total_gb, free_gb, path, source}"""
    path = path or os.path.join(get_config_dir(), "models")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    if psutil is not None:
        d = psutil.disk_usage(path)
        return {"total_gb": round(d.total / 1024 ** 3, 1),
                "free_gb": round(d.free / 1024 ** 3, 1),
                "path": path, "source": "psutil"}
    try:
        st = os.statvfs(path)
        return {"total_gb": round(st.f_blocks * st.f_frsize / 1024 ** 3, 1),
                "free_gb": round(st.f_bavail * st.f_frsize / 1024 ** 3, 1),
                "path": path, "source": "statvfs"}
    except Exception:
        if platform_key() == "win":
            # GetDiskFreeSpaceExW（纯 ctypes）
            try:
                free = ctypes.c_ulonglong(0)
                total = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(path), None,
                    ctypes.byref(total), ctypes.byref(free))
                if total.value:
                    return {"total_gb": _to_gb(total.value, "B"),
                            "free_gb": _to_gb(free.value, "B"),
                            "path": path, "source": "GetDiskFreeSpaceExW"}
            except Exception:
                pass
        return {"total_gb": 0.0, "free_gb": 0.0, "path": path,
                "source": _UNKNOWN}


def probe(path=None):
    """完整硬件体检报告（UI 概览页数据）。"""
    gpus = detect_gpus()
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "gpus": gpus,
        "backends": detect_backends(gpus),
        "cpu": detect_cpu(),
        "memory": detect_memory(),
        "disk": detect_disk(path),
        "vram_gb": round(sum(g.get("vram_gb", 0) for g in gpus), 1),
    }


# ---------------------------------------------------------------------------
# 推荐（启发式估算，界面必须标注"估算"）
# ---------------------------------------------------------------------------
def estimate_speed(params_b, vram_gb=0.0, backend="CPU", quant_gb=None):
    """粗略 tok/s 估算（非实测）。

    基准来自常见消费级硬件的经验区间：
      CUDA + 全放进显存 ≈ 30-100 tok/s；Vulkan/Intel ≈ 15-45；CPU ≈ 3-12。
    参数越大、需要分层到内存/磁盘越多，速度按系数下降。
    """
    try:
        b = float(params_b)
    except (TypeError, ValueError):
        return 0.0
    if b <= 0:
        return 0.0
    base = {"CUDA": 95.0, "Vulkan": 45.0, "ROCm": 45.0, "Intel": 32.0,
            "Metal": 60.0, "CPU": 9.0}.get(str(backend).split("/")[0], 9.0)
    speed = base / max(0.35, (b / 7.0) ** 0.72)
    if quant_gb and vram_gb and quant_gb > vram_gb:
        spill = min(0.85, (quant_gb - vram_gb) / max(quant_gb, 0.1))
        speed *= (1.0 - spill * 0.75)
    return round(max(0.5, speed), 1)


def recommend(hw=None, catalog=None):
    """按硬件给出可运行模型清单（LocModel HARDWARE 推荐规格）。

    catalog 条目：{name, params_b, size_gb, quant, use}
    返回条目附加 tps（估算）、fit（全部放进显卡 / 分层到内存 / 需要硬盘）、
    first_load（估算首次加载秒数）。
    """
    hw = hw or probe()
    catalog = catalog or []
    vram = float(hw.get("vram_gb") or 0.0)
    ram = float((hw.get("memory") or {}).get("available_gb") or 0.0)
    backends = hw.get("backends") or ["CPU"]
    backend = backends[0] if backends else "CPU"
    out = []
    for m in catalog:
        size = float(m.get("size_gb") or 0.0)
        if size <= 0:
            continue
        if size <= vram:
            fit = "全部放进显卡"
        elif size <= vram + max(0.0, ram - 4.0):
            fit = "分层到内存"
        elif size <= vram + max(0.0, ram - 4.0) + float(
                (hw.get("disk") or {}).get("free_gb") or 0.0):
            fit = "按需读取硬盘"
        else:
            fit = "空间不足"
        item = dict(m)
        item["tps"] = estimate_speed(m.get("params_b"), vram, backend, size)
        item["fit"] = fit
        item["first_load"] = int(max(2, size * (3 if fit == "全部放进显卡" else 8)))
        item["backend"] = backend
        item["estimate"] = True           # 明确标注为估算，不冒充实测
        out.append(item)
    # 能跑的排前面，同档按速度降序
    rank = {"全部放进显卡": 0, "分层到内存": 1, "按需读取硬盘": 2, "空间不足": 3}
    out.sort(key=lambda x: (rank.get(x["fit"], 4), -x["tps"]))
    return out


def format_hw(hw):
    """硬件报告可读文本（UI 直接显示）。"""
    if not hw:
        return "尚未检测"
    lines = ["系统：%s" % hw.get("platform", _UNKNOWN)]
    for g in hw.get("gpus", []):
        lines.append("显卡：%s · 显存 %s GB · 后端 %s（%s）" % (
            g.get("name"), g.get("vram_gb"), g.get("backend"), g.get("source")))
    cpu = hw.get("cpu") or {}
    mem = hw.get("memory") or {}
    disk = hw.get("disk") or {}
    lines.append("CPU：%s · %s 核" % (cpu.get("name"), cpu.get("cores")))
    lines.append("内存：总 %s GB / 可用 %s GB" % (
        mem.get("total_gb"), mem.get("available_gb")))
    lines.append("模型盘：%s · 剩余 %s / %s GB" % (
        disk.get("path"), disk.get("free_gb"), disk.get("total_gb")))
    lines.append("后端：%s" % " / ".join(hw.get("backends") or []))
    return "\n".join(lines)
