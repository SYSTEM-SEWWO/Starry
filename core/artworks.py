# -*- coding: utf-8 -*-
"""作品库（LocModel 生成的图片 / 视频集中管理）。

来源：官网图像与视频章节 —— 生成结果进入作品库，可在软件内查看与管理。
本模块只索引 works/ 下真实存在的文件；标签存在同名 .tags.json 旁车文件，
不修改原图/视频本身。删除仅限作品目录内，优先送回收站。
"""
import json
import os
import shutil
import time

from core.genstudio import works_dir

_MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp",
              ".mp4", ".mov", ".webm", ".gif")
_KINDS = {"image": (".png", ".jpg", ".jpeg", ".webp", ".bmp"),
          "video": (".mp4", ".mov", ".webm", ".gif")}


def _tags_file(path):
    return path + ".tags.json"


def load_tags(path):
    try:
        with open(_tags_file(path), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("tags", []), d.get("prompt", ""), d.get("meta", {})
    except Exception:
        return [], "", {}


def save_tags(path, tags=None, prompt="", meta=None):
    if tags is None:
        tags, prompt, meta = load_tags(path)
    try:
        with open(_tags_file(path), "w", encoding="utf-8") as f:
            json.dump({"tags": list(tags or []), "prompt": prompt or "",
                       "meta": meta or {}, "updated": time.time()},
                      f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def add_tags(path, tags):
    old, prompt, meta = load_tags(path)
    merged = list(dict.fromkeys(old + [t for t in (tags or []) if t]))
    return save_tags(path, merged, prompt, meta)


def scan(kind=None, query=""):
    """扫描作品库。kind=image/video；query 匹配文件名、标签、提示词。"""
    root = os.path.abspath(works_dir())
    rows = []
    for base, _dirs, names in os.walk(root):
        for n in names:
            if ".tags.json" in n:
                continue
            ext = os.path.splitext(n)[1].lower()
            if ext not in _MEDIA_EXT:
                continue
            file_kind = "video" if ext in _KINDS["video"] else "image"
            if kind and file_kind != kind:
                continue
            path = os.path.join(base, n)
            tags, prompt, meta = load_tags(path)
            try:
                st = os.stat(path)
            except OSError:
                continue
            row = {"path": path, "name": n, "kind": file_kind,
                   "size": st.st_size, "mtime": st.st_mtime,
                   "tags": tags, "prompt": prompt, "meta": meta}
            if query:
                hay = " ".join([n, prompt, " ".join(tags)]).lower()
                if query.lower() not in hay:
                    continue
            rows.append(row)
    rows.sort(key=lambda r: -r["mtime"])
    return rows


def search(query):
    return scan(query=query)


def _is_inside(path, root=None):
    root = os.path.abspath(root or works_dir())
    try:
        return os.path.commonpath([os.path.abspath(path), root]) == root
    except Exception:
        return False


def delete(path, prefer_trash=True):
    """删除作品（仅限库内）。优先回收站，失败才直接删除。"""
    path = os.path.abspath(path)
    if not _is_inside(path) or not os.path.isfile(path):
        return {"ok": False, "error": "文件不在作品库内"}
    if prefer_trash:
        try:
            from send2trash import send2trash
            send2trash(path)
            try:
                os.remove(_tags_file(path))
            except OSError:
                pass
            return {"ok": True, "trashed": True}
        except Exception:
            pass
    try:
        os.remove(path)
        try:
            os.remove(_tags_file(path))
        except OSError:
            pass
        return {"ok": True, "trashed": False}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def export(paths, dest_dir):
    """导出所选作品到指定目录（复制，不移动）。"""
    dest_dir = os.path.abspath(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    ok, fail = 0, []
    for p in paths:
        if not _is_inside(p) or not os.path.isfile(p):
            fail.append((p, "不在作品库内"))
            continue
        try:
            shutil.copy2(p, os.path.join(dest_dir, os.path.basename(p)))
            ok += 1
        except Exception as e:
            fail.append((p, str(e)[:100]))
    return {"ok": ok, "failed": fail, "dir": dest_dir}


def format_rows(rows):
    if not rows:
        return "作品库为空（生成图片 / 视频后会自动收录）"
    lines = []
    for r in rows:
        lines.append("%s | %s | %.1f KB | %s" % (
            "🖼" if r["kind"] == "image" else "🎬", r["name"],
            r["size"] / 1024.0, ",".join(r["tags"]) or "-"))
        if r["prompt"]:
            lines.append("    %s" % r["prompt"][:80])
    return "\n".join(lines)
