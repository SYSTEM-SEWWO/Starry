# -*- coding: utf-8 -*-
"""本地图片 / 视频生成任务（LocModel「IMAGE」「VIDEO」公开规格复刻）。

功能来源：https://locmodel.com/#image / #video 与 changelog v3.6.0
  图片：Z-Image Turbo / Z-Image Edit / FLUX.2 klein；
        1:1 / 3:4 / 4:3 / 9:16 / 16:9；步数 / 张数 / 种子可调可复现；
        支持参考图重绘、在原图继续改；中文提示词。
  视频：Wan2.2 视频 5B；文生视频 / 首帧续写；横竖屏 480P / 720P；
        时长 / 步数 / 种子 / 反向提示词；进度与耗时显示。
  v3.6：对口型新增高质量版 / 省内存版（约 12 GB，显存 8 GB 起，自动分块）。

重要：本模块是**任务编排层**，不内置生成模型。只有用户在设置里配置了
本地引擎命令（或安装了引擎）才会真实执行；未配置时明确返回错误，
绝不伪造生成结果。生成的图片/视频由 core/artworks.py 收进作品库。
"""
import os
import shlex
import subprocess
import time

from core.config import get_config_dir

IMAGE_MODELS = ["Z-Image Turbo", "Z-Image Edit", "FLUX.2 klein"]
VIDEO_MODELS = ["Wan2.2 视频 5B", "Wan2.2 省内存版"]
LIPSYNC_VERSIONS = ["高质量版", "省内存版（约 12 GB / 8 GB 显存）"]

# 官网明确给出的五种画幅（像素为常用基准，可复现）
ASPECTS = {
    "1:1": (1024, 1024),
    "3:4": (768, 1024),
    "4:3": (1024, 768),
    "9:16": (768, 1344),
    "16:9": (1344, 768),
}

VIDEO_SPECS = {
    "横屏 480P": (854, 480), "横屏 720P": (1280, 720),
    "竖屏 480P": (480, 854), "竖屏 720P": (720, 1280),
}


def works_dir():
    path = os.path.join(get_config_dir(), "artworks")
    os.makedirs(path, exist_ok=True)
    return path


def _cfg(cfg, key, default=None):
    try:
        data = getattr(cfg, "data", None) or {}
        return (data.get("local_studio") or {}).get(key, default)
    except Exception:
        return default


def new_image_task(prompt, model="Z-Image Turbo", aspect="1:1",
                   steps=20, count=4, seed=-1, reference="", negative="",
                   cfg=None):
    """构造图片任务（参数校验 + 可复现种子）。"""
    if aspect not in ASPECTS:
        aspect = "1:1"
    if model not in IMAGE_MODELS:
        model = IMAGE_MODELS[0]
    w, h = ASPECTS[aspect]
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = -1
    if seed < 0:
        import random
        seed = random.randint(1, 2 ** 31 - 1)
    return {
        "kind": "image", "prompt": (prompt or "").strip(), "model": model,
        "aspect": aspect, "width": w, "height": h,
        "steps": max(1, min(100, int(steps or 20))),
        "count": max(1, min(8, int(count or 4))), "seed": seed,
        "reference": reference or "", "negative": negative or "",
        "created": time.time(),
    }


def new_video_task(prompt, model="Wan2.2 视频 5B", spec="竖屏 480P",
                   first_frame="", duration=5, steps=25, seed=-1,
                   negative="", lipsync_version=None, cfg=None):
    """构造视频任务；lipsync_version 不为 None 时是对口型任务（v3.6）。"""
    if spec not in VIDEO_SPECS:
        spec = "竖屏 480P"
    if model not in VIDEO_MODELS:
        model = VIDEO_MODELS[0]
    w, h = VIDEO_SPECS[spec]
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = -1
    if seed < 0:
        import random
        seed = random.randint(1, 2 ** 31 - 1)
    task = {
        "kind": "video", "prompt": (prompt or "").strip(), "model": model,
        "spec": spec, "width": w, "height": h,
        "first_frame": first_frame or "",
        "duration": max(1, min(30, int(duration or 5))),
        "steps": max(1, min(100, int(steps or 25))), "seed": seed,
        "negative": negative or "", "created": time.time(),
    }
    if lipsync_version:
        task["kind"] = "lipsync"
        task["version"] = lipsync_version
    return task


def runner_for(task, cfg=None):
    """取本地引擎命令模板；未配置返回空串。"""
    generators = _cfg(cfg, "generators", {}) or {}
    kind = task.get("kind") or "image"
    return generators.get(kind) or ""


def render_command(template, task, out_dir):
    """安全渲染命令模板：用 shlex.quote 防止参数注入。"""
    ctx = {
        "prompt": task.get("prompt", ""), "negative": task.get("negative", ""),
        "model": task.get("model", ""), "width": task.get("width", 0),
        "height": task.get("height", 0), "steps": task.get("steps", 0),
        "count": task.get("count", 1), "seed": task.get("seed", -1),
        "reference": task.get("reference", ""),
        "first_frame": task.get("first_frame", ""),
        "duration": task.get("duration", 5),
        "out": out_dir, "spec": task.get("spec", ""),
        "version": task.get("version", ""),
    }
    safe = {k: shlex.quote(str(v)) for k, v in ctx.items()}
    try:
        return template.format(**safe)
    except (KeyError, IndexError) as e:
        raise ValueError("命令模板占位符无效：%s" % e)


def run_task(task, cfg=None, progress=None, timeout=3600):
    """执行生成任务。返回 {ok, outputs, elapsed, error}。

    没有配置本地引擎时返回明确错误（不假装成功、不生成假文件）。
    """
    t0 = time.time()
    template = runner_for(task, cfg)
    if not template:
        kind = task.get("kind")
        name = {"image": "画图", "video": "视频", "lipsync": "对口型"}.get(kind, kind)
        return {"ok": False, "outputs": [], "elapsed": 0,
                "error": ("未配置%s引擎：请在「本地 AI 工作室 → 引擎」安装/导入引擎，"
                          "或在设置中填写本地生成命令后重试。" % name)}
    out_dir = os.path.join(works_dir(), task.get("kind", "image"),
                           str(int(t0)))
    os.makedirs(out_dir, exist_ok=True)
    try:
        cmd = render_command(template, task, out_dir)
    except ValueError as e:
        return {"ok": False, "outputs": [], "elapsed": 0, "error": str(e)}
    try:
        if progress:
            progress(5, "正在启动本地引擎…")
        proc = subprocess.Popen(
            cmd, shell=True, cwd=works_dir(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True, errors="ignore")
        lines = []
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line.rstrip())
            if progress and len(lines) % 12 == 0:
                progress(50, line.strip()[:120])
        code = proc.wait(timeout=timeout)
        outputs = []
        for root, _dirs, names in os.walk(out_dir):
            for n in names:
                if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp",
                                       ".mp4", ".mov", ".webm")):
                    outputs.append(os.path.join(root, n))
        elapsed = round(time.time() - t0, 1)
        if code != 0:
            return {"ok": False, "outputs": outputs, "elapsed": elapsed,
                    "error": "引擎退出码 %s：%s" % (
                        code, " | ".join(lines[-4:])[:400])}
        if progress:
            progress(100, "完成")
        return {"ok": True, "outputs": sorted(outputs), "elapsed": elapsed,
                "error": ""}
    except Exception as e:
        return {"ok": False, "outputs": [], "elapsed": round(time.time() - t0, 1),
                "error": str(e)[:300]}


class TaskQueue:
    """简单任务队列（顺序执行、可取消、进度可查）。"""

    def __init__(self):
        self.items = []

    def add(self, task):
        task["status"] = "queued"
        task["id"] = len(self.items) + 1
        self.items.append(task)
        return task["id"]

    def cancel(self, task_id):
        for t in self.items:
            if t.get("id") == task_id and t.get("status") == "queued":
                t["status"] = "cancelled"
                return True
        return False

    def run_next(self, cfg=None):
        for t in self.items:
            if t.get("status") != "queued":
                continue
            t["status"] = "running"
            result = run_task(t, cfg)
            t["status"] = "done" if result["ok"] else "failed"
            t["result"] = result
            return result
        return {"ok": False, "outputs": [], "elapsed": 0, "error": "队列为空"}

    def pending(self):
        return [t for t in self.items if t.get("status") == "queued"]


def format_task(task):
    kind = task.get("kind")
    if kind == "image":
        return ("%s · %s · %s · %dx%d · %d 步 · %d 张 · 种子 %d%s" % (
            task.get("model"), task.get("aspect"), task.get("prompt", "")[:30],
            task.get("width"), task.get("height"), task.get("steps"),
            task.get("count"), task.get("seed"),
            " · 参考图" if task.get("reference") else ""))
    if kind == "video":
        return ("%s · %s · %ds · %dx%d · %d 步 · 种子 %d%s" % (
            task.get("model"), task.get("spec"), task.get("duration"),
            task.get("width"), task.get("height"), task.get("steps"),
            task.get("seed"), " · 首帧续写" if task.get("first_frame") else ""))
    return "%s · %s" % (task.get("model"), task.get("version", ""))
