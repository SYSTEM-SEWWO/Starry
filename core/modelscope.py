# -*- coding: utf-8 -*-
"""阿里魔塔（ModelScope）本地模型下载集成。

免登录公开接口（无需 API Key）：
    搜索  PUT https://modelscope.cn/api/v1/dolphin/models
    文件  GET https://modelscope.cn/api/v1/models/{ns}/{name}/repo/files?Revision=master
    下载  GET https://modelscope.cn/models/{ns}/{name}/resolve/master/{file}

能力：
- search_models       全站搜索（按下载量排序过滤官方 GGUF 仓库）
- list_gguf_files     列出模型的 GGUF 量化文件
- pick_quant          按「速度/质量平衡」挑选量化档位（Q4_K_M 优先）
- download            流式下载 + 断点续传 + 进度回调
"""
import os
import time

import requests

API_BASE = "https://modelscope.cn"
RESOLVE_BASE = "https://modelscope.cn/models"

# 量化优先级：Q4_K_M 为速度/质量平衡点，小内存优先更低比特
_QUANT_ORDER = ["q4_k_m", "q5_k_m", "q4_k_s", "q5_k_s", "q4_0", "q5_0",
                "q6_k", "q8_0", "q3_k_m", "q3_k_l", "q2_k"]

# 精选 GGUF 推荐（官方/社区高质量量化，已验证可下载）
RECOMMENDED = [
    {"id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF", "name": "Qwen2.5 1.5B",
     "desc": "轻量全能 · 2GB 内存可跑", "tags": "对话 · 1.1GB"},
    {"id": "Qwen/Qwen2.5-3B-Instruct-GGUF", "name": "Qwen2.5 3B",
     "desc": "小钢炮 · 4GB 内存流畅", "tags": "对话 · 2.0GB"},
    {"id": "unsloth/Llama-3.2-3B-Instruct-GGUF", "name": "Llama 3.2 3B",
     "desc": "Meta 官方小模型 · 中英文均衡", "tags": "对话 · 1.9GB"},
    {"id": "Qwen/Qwen3-4B-GGUF", "name": "Qwen3 4B",
     "desc": "新一代架构 · 支持思考模式切换", "tags": "对话 · 2.4GB"},
    {"id": "Qwen/Qwen2.5-7B-Instruct-GGUF", "name": "Qwen2.5 7B",
     "desc": "主力级中文对话 · 8GB 内存", "tags": "对话 · 3.8GB×2"},
    {"id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF", "name": "Qwen2.5 Coder 7B",
     "desc": "代码专精 · 编程问答首选", "tags": "代码 · 3.8GB×2"},
    {"id": "Qwen/Qwen3-8B-GGUF", "name": "Qwen3 8B",
     "desc": "旗舰小模型 · 综合能力最强", "tags": "对话 · 4.8GB"},
    {"id": "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF",
     "name": "DeepSeek-R1 7B 蒸馏", "desc": "带思考过程 · 数理推理强",
     "tags": "思考 · 4.5GB"},
    {"id": "unsloth/DeepSeek-R1-Distill-Qwen-14B-GGUF",
     "name": "DeepSeek-R1 14B 蒸馏", "desc": "深度思考 · 需 16GB 内存",
     "tags": "思考 · 8.6GB"},
]


class ModelScopeError(Exception):
    """魔塔接口错误（携带可读信息）"""
    pass


def format_size(n):
    """字节数 → 人类可读"""
    n = float(n or 0)
    if n >= 1024 ** 3:
        return "%.1f GB" % (n / 1024 ** 3)
    if n >= 1024 ** 2:
        return "%.0f MB" % (n / 1024 ** 2)
    return "%.0f KB" % (n / 1024)


# ---------------------------------------------------------------------------
# 搜索 / 文件列表
# ---------------------------------------------------------------------------
def search_models(query, page_size=20, timeout=15):
    """全站搜索模型，返回 [{id, name, chinese_name, downloads}]（按下载量降序）"""
    body = {"Name": query or "", "PageSize": min(30, max(1, page_size)),
            "PageNumber": 1, "SortBy": "Default"}
    try:
        r = requests.put(API_BASE + "/api/v1/dolphin/models",
                         json=body, timeout=timeout)
    except requests.RequestException as e:
        raise ModelScopeError("网络失败：%s" % e)
    if r.status_code != 200:
        raise ModelScopeError("HTTP %d" % r.status_code)
    try:
        data = r.json()
    except ValueError:
        raise ModelScopeError("返回的不是合法 JSON")
    models = ((data.get("Data") or {}).get("Model") or {}).get("Models") or []
    out = []
    for m in models:
        path, name = m.get("Path") or "", m.get("Name") or ""
        if not path or not name:
            continue
        out.append({
            "id": "%s/%s" % (path, name),
            "name": name,
            "chinese_name": m.get("ChineseName") or "",
            "downloads": int(m.get("Downloads") or 0),
        })
    # 官方量化仓库优先，其次下载量
    out.sort(key=lambda x: ("gguf" not in x["name"].lower(), -x["downloads"]))
    return out


def list_repo_files(model_id, revision="master", timeout=15):
    """列出模型仓库全部文件 [{name, size}]"""
    ns, _, name = (model_id or "").partition("/")
    if not ns or not name:
        raise ModelScopeError("模型 ID 格式应为「命名空间/名称」，如 Qwen/Qwen2.5-1.5B-Instruct-GGUF")
    url = "%s/api/v1/models/%s/%s/repo/files?Revision=%s" % (
        API_BASE, ns, name, revision)
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        raise ModelScopeError("网络失败：%s" % e)
    if r.status_code != 200:
        raise ModelScopeError("HTTP %d（模型不存在或为私有）" % r.status_code)
    try:
        data = r.json()
    except ValueError:
        raise ModelScopeError("返回的不是合法 JSON")
    files = (data.get("Data") or {}).get("Files") or []
    return [{"name": f.get("Name") or "", "size": int(f.get("Size") or 0)}
            for f in files if f.get("Name")]


def list_gguf_files(model_id, revision="master", timeout=15):
    """仅筛选 .gguf 文件（按体积升序）"""
    files = list_repo_files(model_id, revision, timeout)
    gg = [f for f in files if f["name"].lower().endswith(".gguf")]
    gg.sort(key=lambda f: f["size"])
    return gg


def pick_quant(gguf_files):
    """按量化优先级挑选文件（Q4_K_M 优先；分卷文件返回第一卷）"""
    if not gguf_files:
        return None
    low = [dict(f, _low=f["name"].lower()) for f in gguf_files]
    for tag in _QUANT_ORDER:
        matches = [f for f in low if tag in f["_low"]]
        if matches:
            chosen = matches[0]
            # 分卷文件：定位第一卷（llama.cpp 按序号加载）
            import re
            m = re.search(r"-\d{5}-of-\d{5}\.", chosen["_low"])
            if m:
                prefix = chosen["name"][:m.start()]
                first = [f for f in low
                         if f["name"].startswith(prefix + "-")
                         and "-00001-of-" in f["name"]]
                if first:
                    chosen = first[0]
            return {k: v for k, v in chosen.items() if k != "_low"}
    best = low[0]
    return {k: v for k, v in best.items() if k != "_low"}


def quant_parts(gguf_files, chosen_name):
    """分卷文件的全部分片（llama.cpp 需全部下载，按序号排序）"""
    if "-of-" not in chosen_name:
        return [chosen_name]
    import re
    m = re.search(r"-\d{5}-of-\d{5}\.", chosen_name)
    if not m:
        return [chosen_name]
    prefix = chosen_name[:m.start()]
    parts = [f["name"] for f in gguf_files
             if f["name"].startswith(prefix + "-")
             and f["name"].endswith(".gguf")]
    return sorted(parts)


def resolve_url(model_id, file_name, revision="master"):
    ns, _, name = (model_id or "").partition("/")
    return "%s/%s/%s/resolve/%s/%s" % (RESOLVE_BASE, ns, name, revision, file_name)


# ---------------------------------------------------------------------------
# 下载（流式 + 断点续传）
# ---------------------------------------------------------------------------
def download(model_id, file_name, dest_path, on_progress=None,
             should_stop=None, timeout=(10, 300)):
    """下载单个文件到 dest_path。

    on_progress(done_bytes, total_bytes) 每 0.3 秒左右回调一次。
    支持断点续传：已存在部分文件时发送 Range 请求。
    """
    url = resolve_url(model_id, file_name)
    headers = {}
    pos = 0
    if os.path.exists(dest_path):
        pos = os.path.getsize(dest_path)
        headers["Range"] = "bytes=%d-" % pos
    try:
        r = requests.get(url, headers=headers, stream=True, timeout=timeout)
    except requests.RequestException as e:
        raise ModelScopeError("下载失败：%s" % e)
    if r.status_code == 416:            # 文件已完整
        if on_progress:
            on_progress(pos, pos)
        return
    if r.status_code not in (200, 206):
        raise ModelScopeError("HTTP %d" % r.status_code)

    # 已完整的另一种表现：越界 Range 返回 200 + 空 body（部分 CDN 行为）
    if headers.get("Range") and not r.headers.get("Content-Range") \
            and int(r.headers.get("Content-Length") or -1) == 0:
        if on_progress:
            on_progress(pos, pos)
        return

    # 续传判定：部分 CDN 对 Range 返回 200 + Content-Range（非标准 206），
    # 因此以「带了 Range 头且响应带 Content-Range」为准
    resuming = bool(headers.get("Range") and r.headers.get("Content-Range"))
    total = pos + int(r.headers.get("Content-Length") or 0)
    cr = r.headers.get("Content-Range") or ""
    if cr and "/" in cr:
        try:
            total = int(cr.rsplit("/", 1)[1])
        except ValueError:
            pass
    done = pos
    last_cb = 0.0
    # 全新下载走 .part 临时文件 + 原子改名，避免中断留下坏文件
    write_path = dest_path if resuming else dest_path + ".part"
    mode = "ab" if resuming else "wb"
    if should_stop and should_stop():
        if write_path != dest_path and os.path.exists(write_path):
            os.remove(write_path)
        raise ModelScopeError("下载已取消")
    try:
        with open(write_path, mode) as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                if should_stop and should_stop():
                    raise ModelScopeError("下载已取消")
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                if on_progress and now - last_cb >= 0.3:
                    last_cb = now
                    on_progress(done, total)
        if on_progress:
            on_progress(done, total)
        if write_path != dest_path:
            os.replace(write_path, dest_path)
    except ModelScopeError:
        if write_path != dest_path and os.path.exists(write_path):
            os.remove(write_path)      # 清理半成品临时文件
        raise
    except OSError as e:
        if write_path != dest_path and os.path.exists(write_path):
            os.remove(write_path)
        raise ModelScopeError("写入失败：%s" % e)


def model_page_url(model_id):
    return "%s/models/%s" % (API_BASE, model_id)
