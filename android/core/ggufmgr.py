# -*- coding: utf-8 -*-
"""GGUF 模型管理（LocModel「MODELS」公开规格复刻）。

功能来源：https://locmodel.com/#models
  - 在线下载：按硬件与用途筛选 HuggingFace 模型
  - 导入 GGUF：本地文件直接导入，不转换格式、不上传
  - 已安装管理：版本、大小、量化方式与运行状态一页看完

GGUF 元数据解析为纯 Python（读文件头 KV），不依赖 llama.cpp。
网络功能全部可选：失败返回明确错误，不伪造下载成功。
"""
import os
import shutil
import struct

try:
    import requests
except Exception:                                  # pragma: no cover
    requests = None

from core import local_llm

HF_API = "https://huggingface.co/api/models"
HF_RESOLVE = "https://huggingface.co/%s/resolve/main/%s"

# GGMLQuantizationType（官方枚举，用于展示量化方式）
_QUANT_NAMES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 4: "Q5_0", 5: "Q5_1",
    6: "Q8_0", 7: "Q8_1", 8: "Q2_K", 9: "Q3_K_S", 10: "Q3_K_M",
    11: "Q3_K_L", 12: "Q4_K_S", 13: "Q4_K_M", 14: "Q5_K_S", 15: "Q5_K_M",
    16: "Q6_K", 17: "Q8_K", 18: "IQ2_XXS", 19: "IQ2_XS", 20: "IQ3_XXS",
    21: "IQ1_S", 22: "IQ4_NL", 23: "IQ3_S", 24: "IQ2_S", 25: "IQ4_XS",
    26: "IQ1_M", 27: "BF16", 28: "TQ1_0", 29: "TQ2_0",
}


# ---------------------------------------------------------------------------
# GGUF 头解析
# ---------------------------------------------------------------------------
def _fmt(buf, off, pattern):
    size = struct.calcsize(pattern)
    if off + size > len(buf):
        raise EOFError("GGUF 数据截断")
    return struct.unpack_from(pattern, buf, off)[0], off + size


def _string(buf, off):
    n, off = _fmt(buf, off, "<Q")
    if n > 10 * 1024 * 1024 or off + n > len(buf):
        raise EOFError("GGUF 字符串异常")
    return buf[off:off + n].decode("utf-8", "ignore"), off + n


_SCALARS = {
    0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
    6: "<f", 10: "<Q", 11: "<q", 12: "<d",
}


def _value(buf, off, vtype):
    """读取一个 GGUF 值；超大数组只保留前 6 个样本但正确推进偏移。"""
    if vtype in _SCALARS:
        return _fmt(buf, off, _SCALARS[vtype])
    if vtype == 7:                       # bool
        v, off = _fmt(buf, off, "<B")
        return bool(v), off
    if vtype == 8:                       # string
        return _string(buf, off)
    if vtype == 9:                       # array
        n, off = _fmt(buf, off, "<Q")
        et, off = _fmt(buf, off, "<I")
        if n > 2000000:
            raise EOFError("GGUF 数组过大")
        sample, i = [], 0
        while i < n:
            if et in _SCALARS:
                v, off = _fmt(buf, off, _SCALARS[et])
            elif et == 7:
                v, off = _fmt(buf, off, "<B")
                v = bool(v)
            elif et == 8:
                v, off = _string(buf, off)
            else:
                raise EOFError("GGUF 数组元素类型 %s 不支持" % et)
            if i < 6:
                sample.append(v)
            i += 1
        return {"count": n, "type": et, "sample": sample}, off
    raise EOFError("GGUF 值类型 %s 不支持" % vtype)


def parse_gguf(path, max_bytes=12 * 1024 * 1024):
    """解析 GGUF 头元数据。失败返回 {error, name, size_gb, quant} 基础信息。"""
    info = {"path": path, "name": os.path.basename(path),
            "size_gb": 0.0, "quant": _UNKNOWN_QUANT(), "error": ""}
    try:
        info["size_gb"] = round(os.path.getsize(path) / 1024 ** 3, 2)
        with open(path, "rb") as f:
            buf = f.read(max_bytes)
        if buf[:4] != b"GGUF":
            info["error"] = "不是 GGUF 文件"
            return info
        off = 4
        ver, off = _fmt(buf, off, "<I")
        _tensor_count, off = _fmt(buf, off, "<Q")
        kv_count, off = _fmt(buf, off, "<Q")
        if ver not in (2, 3):
            info["error"] = "GGUF 版本 %s 未支持" % ver
            return info
        meta = {}
        for _ in range(min(kv_count, 5000)):
            key, off = _string(buf, off)
            vt, off = _fmt(buf, off, "<I")
            val, off = _value(buf, off, vt)
            meta[key] = val
        info["version"] = ver
        info["arch"] = str(meta.get("general.architecture", ""))
        if meta.get("general.name"):
            info["display_name"] = str(meta["general.name"])
        ft = meta.get("general.file_type")
        if isinstance(ft, int):
            info["quant"] = _QUANT_NAMES.get(ft, "type_%d" % ft)
        pc = meta.get("general.parameter_count")
        if isinstance(pc, int) and pc > 0:
            info["params_b"] = round(pc / 1e9, 2)
        ctx = meta.get("%s.context_length" % info["arch"])
        if isinstance(ctx, int) and ctx > 0:
            info["ctx"] = ctx
        info["meta_count"] = len(meta)
        return info
    except Exception as e:
        info["error"] = "解析失败：%s" % str(e)[:120]
        return info


def _UNKNOWN_QUANT():
    return "未知量化"


# ---------------------------------------------------------------------------
# 已安装模型
# ---------------------------------------------------------------------------
def scan_models(include_meta=True):
    """扫描已安装 GGUF（版本 / 大小 / 量化 / 运行状态）。"""
    rows, running = [], False
    try:
        running = bool(local_llm.is_running(timeout=1))
    except Exception:
        pass
    for item in local_llm.list_local_gguf():
        row = dict(item)
        row["quant"] = _UNKNOWN_QUANT()
        row["params_b"] = 0.0
        row["ctx"] = 0
        if include_meta:
            meta = parse_gguf(item["path"])
            row["quant"] = meta.get("quant", row["quant"])
            row["params_b"] = meta.get("params_b", 0.0)
            row["ctx"] = meta.get("ctx", 0)
            row["display_name"] = meta.get("display_name", row["name"])
            row["error"] = meta.get("error", "")
        row["running"] = running
        rows.append(row)
    return rows


def import_file(src, dest_dir=None, move=False):
    """导入本地 GGUF：不转换、不上传，只复制到模型目录。"""
    src = os.path.abspath(src)
    if not os.path.isfile(src) or not src.lower().endswith(".gguf"):
        return {"ok": False, "error": "请选择 .gguf 文件"}
    dest_dir = os.path.abspath(dest_dir or local_llm.models_dir())
    os.makedirs(dest_dir, exist_ok=True)
    dst = os.path.join(dest_dir, os.path.basename(src))
    if os.path.commonpath([dst, dest_dir]) != dest_dir:
        return {"ok": False, "error": "目标路径越界"}
    try:
        if os.path.abspath(src) == os.path.abspath(dst):
            return {"ok": True, "path": dst}
        if move:
            shutil.move(src, dst)
        else:
            shutil.copy2(src, dst)
        return {"ok": True, "path": dst}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def delete_model(path):
    """只允许删除模型目录内的文件。"""
    try:
        root = os.path.abspath(local_llm.models_dir())
        target = os.path.abspath(path)
        if os.path.commonpath([target, root]) != root:
            return False
        if not os.path.isfile(target):
            return False
        os.remove(target)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 在线（HuggingFace）
# ---------------------------------------------------------------------------
def hf_search(query, limit=8):
    """搜索 HuggingFace GGUF 模型；离线返回 {error}。"""
    if requests is None:
        return {"items": [], "error": "requests 未安装"}
    try:
        r = requests.get(HF_API, params={
            "search": query, "filter": "gguf", "limit": limit,
            "sort": "downloads", "direction": -1,
        }, timeout=15)
        r.raise_for_status()
        items = []
        for m in r.json():
            sid = m.get("id") or m.get("modelId")
            if not sid:
                continue
            items.append({
                "id": sid, "downloads": m.get("downloads", 0),
                "likes": m.get("likes", 0),
                "tags": (m.get("tags") or [])[:6],
                "files": [s.get("rfilename") for s in (m.get("siblings") or [])
                          if str(s.get("rfilename", "")).lower().endswith(".gguf")][:8],
            })
        return {"items": items, "error": ""}
    except Exception as e:
        return {"items": [], "error": "搜索失败：%s" % str(e)[:160]}


def hf_download(repo_id, filename, dest_dir=None, progress=None, chunk=1 << 20):
    """流式下载 HuggingFace GGUF；progress(downloaded, total, pct)。"""
    if requests is None:
        return {"ok": False, "error": "requests 未安装"}
    dest_dir = os.path.abspath(dest_dir or local_llm.models_dir())
    os.makedirs(dest_dir, exist_ok=True)
    dst = os.path.join(dest_dir, os.path.basename(filename))
    part = dst + ".part"
    try:
        url = HF_RESOLVE % (repo_id, filename)
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as f:
                for block in r.iter_content(chunk):
                    if not block:
                        continue
                    f.write(block)
                    done += len(block)
                    if progress:
                        progress(done, total,
                                 round(done * 100.0 / total, 1) if total else 0)
        os.replace(part, dst)
        return {"ok": True, "path": dst}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# 内置参考目录（来源：官网公开模型名称 + 常见 GGUF 规格；非实时数据）
# ---------------------------------------------------------------------------
def builtin_catalog():
    """内置推荐目录；size/params 为常见量化档参考值，实际以模型页为准。"""
    return [
        {"name": "Qwen3.6 35B-A3B（官网示例）", "params_b": 35.0,
         "size_gb": 21.0, "quant": "Q4_K_M", "use": "对话 / 代码"},
        {"name": "Qwen2.5 7B Instruct", "params_b": 7.0,
         "size_gb": 4.7, "quant": "Q4_K_M", "use": "通用对话"},
        {"name": "Qwen2.5 14B Instruct", "params_b": 14.0,
         "size_gb": 9.0, "quant": "Q4_K_M", "use": "写作 / 推理"},
        {"name": "Gemma 3 4B", "params_b": 4.0,
         "size_gb": 3.2, "quant": "Q4_K_M", "use": "轻量 / 低显存"},
        {"name": "Llama 3.3 8B", "params_b": 8.0,
         "size_gb": 5.4, "quant": "Q4_K_M", "use": "通用"},
        {"name": "DeepSeek-R1-Distill-Qwen 7B", "params_b": 7.0,
         "size_gb": 4.7, "quant": "Q4_K_M", "use": "深度思考"},
        {"name": "Muse Glimmer 30B（官网示例）", "params_b": 30.0,
         "size_gb": 17.0, "quant": "Q4_K_M", "use": "Agent / 长任务"},
    ]


def format_rows(rows):
    lines = []
    for r in rows:
        lines.append("%s | %s GB | %s | %s B | %s | %s" % (
            r.get("name", ""), r.get("size_gb", 0), r.get("quant", ""),
            r.get("params_b", 0), r.get("use", ""),
            "运行中" if r.get("running") else "已安装"))
    return "\n".join(lines) or "暂无已安装模型"
