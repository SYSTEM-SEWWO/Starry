# -*- coding: utf-8 -*-
"""本地推理引擎管理（LocModel「ENGINE」公开规格复刻）。

功能来源：https://locmodel.com/#engine 与 changelog v3.6.0
  - 自动匹配 llama.cpp 官方构建（NVIDIA CUDA / AMD Vulkan / Intel / CPU）
  - 下载进度、速度、剩余时间可见；可暂停、失败可重试
  - 支持手动导入本地 ZIP，离线安装
  - v3.6：对口型引擎按剩余显存安排，提供高质量版 / 省内存版

重要：只有 llama.cpp 的下载地址是公开可验证的官方 Release；
画图 / 视频 / 对口型引擎属于 LocModel 自带组件，没有公开直链，
本模块通过配置项 engine_urls 让用户自行填写来源，绝不编造下载 URL。
"""
import os
import re
import shutil
import sys
import threading
import time
import zipfile

try:
    import requests
except Exception:                                  # pragma: no cover
    requests = None

from core.config import get_config_dir

ENGINES = {
    "llm": {
        "name": "llama.cpp · 大语言模型",
        "desc": "OpenAI 兼容 llama-server，支持 GGUF 与 8K-64K 上下文",
        "backends": ["CUDA", "Vulkan", "Intel", "CPU"],
        "executables": ("llama-server.exe", "llama-server"),
        "official": True,
    },
    "image": {
        "name": "画图引擎 · Z-Image / FLUX",
        "desc": "Z-Image Turbo / Z-Image Edit / FLUX.2 klein 本地推理",
        "backends": ["CUDA", "Vulkan", "CPU"],
        "executables": ("run_image.exe", "run_image.py", "run_image"),
        "official": False,
    },
    "video": {
        "name": "视频引擎 · Wan2.2",
        "desc": "Wan2.2 视频 5B，文生视频 / 首帧续写，480P / 720P",
        "backends": ["CUDA", "Vulkan", "CPU"],
        "executables": ("run_video.exe", "run_video.py", "run_video"),
        "official": False,
    },
    "lipsync": {
        "name": "对口型引擎 · v3.6 省内存版",
        "desc": "按剩余显存自动安排；高质量版 / 省内存版（约 12 GB）",
        "backends": ["CUDA", "Vulkan", "CPU"],
        "executables": ("run_lipsync.exe", "run_lipsync.py", "run_lipsync"),
        "official": False,
    },
}

_LLAMA_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=12"


def llama_latest_url(backend="CPU", cfg=None, timeout=15):
    """从 GitHub 官方 API 读取 llama.cpp 最新 Release 的真实资产直链。

    绝不硬编码某个 build 编号（会失效且属于臆造）。网络失败时返回空串，
    UI 会提示手动导入 ZIP，而不是给出假链接。
    """
    if requests is None:
        return ""
    custom = _cfg(cfg, "engine_urls", {}) or {}
    url = custom.get("llm_%s" % backend) or custom.get("llm")
    if url:
        return url
    key = str(backend).lower()
    win = sys.platform.startswith("win")
    mac = sys.platform == "darwin"
    try:
        r = requests.get(_LLAMA_API, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        releases = data if isinstance(data, list) else [data]
        for rel in releases:                 # 最新的 release 可能只有源码资产
            candidates = []
            for a in (rel.get("assets") or []):
                name = str(a.get("name") or "").lower()
                if not name.endswith(".zip"):
                    continue
                if mac:
                    platform_ok = "mac" in name or "arm64" in name
                elif win:
                    platform_ok = "win" in name and "arm" not in name
                else:
                    platform_ok = "ubuntu" in name or "linux" in name
                if not platform_ok:
                    continue
                if "cuda" in key:
                    score = 3 if "cuda" in name else -1
                elif "vulkan" in key:
                    score = 3 if "vulkan" in name else -1
                elif "intel" in key:
                    score = 3 if ("intel" in name or "synclas" in name) else -1
                else:
                    score = 3 if "cpu" in name else 0
                if score >= 0:
                    # 优先主程序包 llama-bXXXX-*.zip，而不是 cudart 依赖包
                    is_main = 0 if re.search(r"llama-b\d+", name) else 1
                    candidates.append((score, is_main, str(a.get("name") or ""),
                                       a.get("browser_download_url", "")))
            if candidates:
                candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
                return candidates[0][3]
    except Exception:
        pass
    return ""


def engines_dir():
    path = os.path.join(get_config_dir(), "engines")
    os.makedirs(path, exist_ok=True)
    return path


def engine_dir(kind):
    return os.path.join(engines_dir(), kind)


def _cfg(cfg, key, default=""):
    try:
        data = getattr(cfg, "data", None) or {}
        studio = data.get("local_studio") or {}
        return studio.get(key, default)
    except Exception:
        return default


def engine_url(kind, backend="CPU", cfg=None):
    """取得引擎下载地址：优先用户配置 → llama.cpp 官方 → 明确报错。"""
    custom = _cfg(cfg, "engine_urls", {}) or {}
    url = custom.get("%s_%s" % (kind, backend)) or custom.get(kind)
    if url:
        return url, "用户配置"
    if kind == "llm":
        url = llama_latest_url(backend, cfg)
        if url:
            return url, "llama.cpp 官方最新 Release（GitHub API 实时查询）"
        return "", ("llama.cpp 官方直链查询失败（离线或 API 限流）；"
                    "请检查网络、在设置中填写来源，或使用「导入本地 ZIP」离线安装")
    return "", ("未配置：该引擎非公开直链，请在设置中填写来源，"
                "或使用「导入本地 ZIP」离线安装")


def find_engine_exe(kind, folder=None):
    folder = folder or engine_dir(kind)
    spec = ENGINES.get(kind) or {}
    for name in spec.get("executables", ()):
        cand = os.path.join(folder, name)
        if os.path.isfile(cand):
            return cand
    # 递归一层（ZIP 常带 bin/ 子目录）
    for sub in ("bin", "build/bin", "llama.cpp/bin"):
        for name in spec.get("executables", ()):
            cand = os.path.join(folder, sub, name)
            if os.path.isfile(cand):
                return cand
    return None


def status(kind=None):
    """引擎安装状态（版本 / 路径 / 文件数）。"""
    kinds = [kind] if kind else list(ENGINES)
    out = []
    for k in kinds:
        if k not in ENGINES:
            continue
        folder = engine_dir(k)
        exists = os.path.isdir(folder)
        files = 0
        if exists:
            for _root, _dirs, names in os.walk(folder):
                files += len(names)
        exe = find_engine_exe(k, folder)
        out.append({
            "kind": k, "name": ENGINES[k]["name"], "desc": ENGINES[k]["desc"],
            "installed": bool(exe), "path": folder if exists else "",
            "executable": exe or "", "files": files,
            "backends": ENGINES[k]["backends"],
            "official": ENGINES[k]["official"],
        })
    return out[0] if kind else out


class DownloadController:
    """下载控制器：支持暂停 / 取消 / 进度 / 速度 / 剩余时间。"""

    def __init__(self):
        self.pause_event = threading.Event()
        self.cancel_event = threading.Event()

    def pause(self):
        self.pause_event.set()

    def resume(self):
        self.pause_event.clear()

    def cancel(self):
        self.cancel_event.set()


def download(kind, backend="CPU", cfg=None, dest=None, progress=None,
             controller=None, retries=2):
    """下载引擎 ZIP。progress(done, total, pct, speed, eta) 回调。"""
    if kind not in ENGINES:
        return {"ok": False, "error": "未知引擎：%s" % kind}
    url, source = engine_url(kind, backend, cfg)
    if not url:
        return {"ok": False, "error": source}
    if requests is None:
        return {"ok": False, "error": "requests 未安装，无法下载"}
    dest = os.path.abspath(dest or engines_dir())
    os.makedirs(dest, exist_ok=True)
    filename = "%s_%s.zip" % (kind, backend)
    part = os.path.join(dest, filename + ".part")
    final = os.path.join(dest, filename)
    ctrl = controller or DownloadController()
    last_err = ""

    for attempt in range(retries + 1):
        try:
            with requests.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                t0 = time.time()
                with open(part, "wb") as f:
                    for block in r.iter_content(1 << 20):
                        if ctrl.cancel_event.is_set():
                            return {"ok": False, "error": "已取消"}
                        while ctrl.pause_event.is_set():
                            if ctrl.cancel_event.is_set():
                                return {"ok": False, "error": "已取消"}
                            time.sleep(0.15)
                        if not block:
                            continue
                        f.write(block)
                        done += len(block)
                        if progress:
                            elapsed = max(0.1, time.time() - t0)
                            speed = done / elapsed
                            eta = (total - done) / speed if speed and total else 0
                            progress(done, total,
                                     round(done * 100.0 / total, 1) if total else 0,
                                     round(speed / 1024 / 1024, 2), int(eta))
            os.replace(part, final)
            return {"ok": True, "path": final, "source": source,
                    "attempt": attempt + 1}
        except Exception as e:
            last_err = str(e)[:200]
            if attempt < retries:
                time.sleep(1 + attempt)
    return {"ok": False, "error": "下载失败（已重试 %d 次）：%s" % (
        retries, last_err)}


def import_zip(kind, zip_path, dest=None):
    """手动导入本地引擎 ZIP（离线安装）：校验后解压到 engines/<kind>。"""
    if kind not in ENGINES:
        return {"ok": False, "error": "未知引擎"}
    zip_path = os.path.abspath(zip_path)
    if not zip_path.lower().endswith(".zip") or not os.path.isfile(zip_path):
        return {"ok": False, "error": "请选择 .zip 安装包"}
    target = os.path.abspath(dest or engine_dir(kind))
    root = os.path.abspath(engines_dir())
    if os.path.commonpath([target, root]) != root:
        return {"ok": False, "error": "目标路径越界"}
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            if not names:
                return {"ok": False, "error": "ZIP 为空"}
            # 防目录穿越
            for n in names:
                p = os.path.abspath(os.path.join(target, n))
                if os.path.commonpath([p, target]) != target:
                    return {"ok": False, "error": "ZIP 含越界路径：%s" % n}
            os.makedirs(target, exist_ok=True)
            z.extractall(target)
        exe = find_engine_exe(kind, target)
        return {"ok": True, "path": target, "executable": exe or "",
                "warning": "" if exe else "已解压，但未找到预期可执行文件"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def remove_engine(kind):
    """移除引擎目录（严格限制在 engines/ 下）。"""
    folder = os.path.abspath(engine_dir(kind))
    root = os.path.abspath(engines_dir())
    if os.path.commonpath([folder, root]) != root or folder == root:
        return False
    try:
        shutil.rmtree(folder)
        return True
    except Exception:
        return False


def format_status(rows=None):
    rows = rows if rows is not None else status()
    lines = []
    for r in rows:
        lines.append("%s | %s | 后端 %s | %s" % (
            r["name"], "已安装" if r["installed"] else "未安装",
            "/".join(r["backends"]), r["desc"]))
    return "\n".join(lines)
