# -*- coding: utf-8 -*-
"""应用缓存清理（v13.4）· 安全优先的纯逻辑层。

设计红线（比「删得干净」更重要）：

1. **只清理应用自身产生的、可再生的内容**：Python 字节码、原子写残留、
   API 诊断日志、模型/插件列表缓存。用户数据一律不碰。
2. **硬保护名单**：config.json / sessions.json / library.json / memory.json /
   automation.json / stats.json / 网关统计 / GGUF 模型 / 浏览器登录态，
   即使出现在扫描结果里也会被拒绝删除。
3. **扫描与清理分离**：``scan()`` 只读；``clean()`` 才动手，且默认先备份、
   每批最多 10 个文件、任一失败立即停止。
4. **绝不递归删目录**：只 ``os.remove`` 明确的单个文件，不调用 rmtree，
   不删 __pycache__ 目录本身，不跟随符号链接。
5. **路径白名单**：任何待删文件必须位于「应用数据目录」或「项目根目录」内，
   且通过文件名 / 后缀 / 保护名单三重校验；拒绝路径穿越。
6. **可撤销**：备份放在 ``<数据目录>/cache_backup/<时间戳>/``，
   保留相对路径结构，``restore()`` 可把文件放回。
"""
import json
import os
import shutil
import time

from core.config import get_config_dir

# ---------------------------------------------------------------------------
# 保护名单：这些是用户数据 / 凭据 / 大模型，任何情况下都不允许清理
# ---------------------------------------------------------------------------
PROTECTED_BASENAMES = {
    "config.json", "sessions.json", "library.json", "memory.json",
    "automation.json", "stats.json", "gateway_stats.json",
    "gateway_budgets.json", "prompts.json", "hub.json", "skills.json",
    "config.example.json", "config.hub.example.json",
}
PROTECTED_EXTS = {".gguf", ".bin", ".safetensors", ".db", ".sqlite",
                  ".sqlite3", ".key", ".pem", ".crt"}
# 浏览器登录态、本地模型目录：整目录排除
PROTECTED_PATH_PARTS = {"cache_backup", "browser", "models", "bin",
                        "profile", "userdata"}

# 允许清理的文件后缀（其余一律不碰）
CLEANABLE_EXTS = {".pyc", ".tmp", ".log", ".jsonl"}

# config.json 内的「软缓存」键：清理就是把它们清空后写回（config.json 本身不动）
CONFIG_CACHE_KEYS = ("model_cache", "market_cache", "hub_cache",
                     "update_cache", "insights_cache")

# 扫描规则：(id, 分类, 根目录类型, 匹配后缀, 说明, 默认勾选)
SCAN_RULES = (
    ("pycache", "Python 字节码缓存", "project", {".pyc"},
     "项目内 __pycache__ 的 .pyc；Python 会自动重建，清理后不影响功能。", True),
    ("tmp", "原子写入残留", "data", {".tmp"},
     "保存配置时的临时文件残留（*.tmp）；正常流程会自动清理，异常退出时可能留下。", True),
    ("logs", "运行日志", "data", {".log"},
     "本地日志文本文件；不含 API Key 明文（诊断信息已脱敏）。", True),
    ("apilog", "API 审计日志", "data", {".jsonl"},
     "STARRY_API_LOG 开启后产生的 JSONL 诊断记录，可随时重新生成。", True),
)


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _within(path, root):
    """path 是否严格位于 root 之内（防路径穿越）。"""
    try:
        p, r = _norm(path), _norm(root)
        return os.path.commonpath([p, r]) == r and p != r
    except (ValueError, OSError):
        return False


def _is_protected(path, data_dir, project_dir):
    name = os.path.basename(path)
    if name.lower() in PROTECTED_BASENAMES:
        return True
    if os.path.splitext(name)[1].lower() in PROTECTED_EXTS:
        return True
    low = _norm(path).replace("\\", "/").lower()
    if any(("/%s/" % part) in low for part in PROTECTED_PATH_PARTS):
        return True
    if not (_within(path, data_dir) or _within(path, project_dir)):
        return True
    return False


def _collect(root, exts, max_files=5000):
    """只读遍历：只收单个文件，不递归删除、不跟随符号链接。"""
    out = []
    if not root or not os.path.isdir(root):
        return out
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in PROTECTED_PATH_PARTS
                   and not d.startswith(".")]
        for f in files:
            if os.path.splitext(f)[1].lower() not in exts:
                continue
            p = os.path.join(cur, f)
            if os.path.islink(p):
                continue
            out.append(p)
            if len(out) >= max_files:
                return out
    return out


def scan(data_dir=None, project_dir=None, cfg=None):
    """只读扫描，返回分类聚合清单。

    每项：{id, category, desc, files[], count, size, default_selected}
    调用方必须先展示给用户确认，再调用 clean()。绝不在此函数里删任何东西。
    """
    data_dir = os.path.abspath(data_dir or get_config_dir())
    project_dir = os.path.abspath(project_dir or os.getcwd())
    items = []
    for cid, category, root_kind, exts, desc, default in SCAN_RULES:
        root = project_dir if root_kind == "project" else data_dir
        files = [p for p in _collect(root, exts)
                 if not _is_protected(p, data_dir, project_dir)]
        size = 0
        for p in files:
            try:
                size += os.path.getsize(p)
            except OSError:
                pass
        if not files:
            continue
        items.append({
            "id": cid, "category": category, "desc": desc,
            "files": files, "count": len(files), "size": size,
            "default_selected": default,
        })

    # config.json 内的软缓存（模型列表 / 插件市场索引等）
    if cfg is not None:
        try:
            present = [k for k in CONFIG_CACHE_KEYS if cfg.data.get(k)]
        except Exception:                               # noqa: BLE001
            present = []
        if present:
            items.append({
                "id": "config_cache", "category": "配置内缓存键",
                "desc": "config.json 里的 %s（模型列表 / 插件索引会在下次刷新时重建；"
                        "config.json 本身与 API Key 不会被删除）。" % "、".join(present),
                "files": [], "count": len(present), "size": 0,
                "default_selected": True, "config_keys": present,
            })
    return items


def format_scan(items, limit_paths=5):
    """纯文本报告（CLI / 复制到剪贴板）。"""
    if not items:
        return "没有发现可清理的应用缓存。"
    lines = ["共 %d 类可清理缓存：" % len(items)]
    for it in items:
        lines.append("  [%s] %s · %d 项 · %s" % (
            "✓" if it["default_selected"] else " ",
            it["category"], it["count"], _fmt_size(it["size"])))
        lines.append("      %s" % it["desc"])
        for p in it["files"][:max(0, int(limit_paths))]:
            lines.append("      · %s" % p)
        if it["count"] > limit_paths:
            lines.append("      · … 其余 %d 个文件" % (it["count"] - limit_paths))
    lines.append("  合计可释放：%s" % _fmt_size(sum(i["size"] for i in items)))
    lines.append("  保护名单：config.json / 会话 / 资料库 / 记忆 / 统计 / GGUF 模型不会被清理。")
    return "\n".join(lines)


def _fmt_size(n):
    n = int(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "%d B" % n


def _backup_path(backup_dir, path, data_dir, project_dir):
    for root, tag in ((data_dir, "data"), (project_dir, "project")):
        if _within(path, root):
            rel = os.path.relpath(path, root)
            return os.path.join(backup_dir, tag, rel)
    return os.path.join(backup_dir, "misc", os.path.basename(path))


def clean(items, data_dir=None, project_dir=None, cfg=None,
          backup=True, dry_run=False, batch_size=10, now=None):
    """执行清理（必须先 scan + 用户确认后再调用）。

    返回 {cleaned, failed, freed_bytes, backup_dir, dry_run, batches, config_keys}。
    dry_run=True 时只做全部校验与统计，**不删除、不写回**。
    """
    data_dir = os.path.abspath(data_dir or get_config_dir())
    project_dir = os.path.abspath(project_dir or os.getcwd())
    ts = now or time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(data_dir, "cache_backup", ts)
    report = {"cleaned": [], "failed": [], "freed_bytes": 0,
              "backup_dir": "", "dry_run": bool(dry_run),
              "batches": 0, "config_keys": []}

    # 1) 先把所有待处理文件摊平 + 逐项安全校验
    pending = []
    for it in items or []:
        if not it.get("selected", it.get("default_selected", False)):
            continue
        for p in it.get("files") or []:
            if not _is_protected(p, data_dir, project_dir) \
                    and os.path.splitext(p)[1].lower() in CLEANABLE_EXTS:
                pending.append(p)
            else:
                report["failed"].append((p, "被安全规则拒绝"))
        for k in it.get("config_keys") or []:
            if k in CONFIG_CACHE_KEYS:
                report["config_keys"].append(k)

    # 2) 小批量：每批最多 batch_size 个，任一失败立即停
    n = max(1, int(batch_size or 10))
    for start in range(0, len(pending), n):
        batch = pending[start:start + n]
        report["batches"] += 1
        for p in batch:
            try:
                size = os.path.getsize(p)
                if dry_run:
                    report["cleaned"].append(p)
                    report["freed_bytes"] += size
                    continue
                if backup:
                    dst = _backup_path(backup_dir, p, data_dir, project_dir)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(p, dst)
                os.remove(p)                 # 只删单个文件，绝不 rmtree
                report["cleaned"].append(p)
                report["freed_bytes"] += size
            except Exception as e:           # noqa: BLE001
                report["failed"].append((p, str(e)[:120]))
                if not dry_run:
                    report["backup_dir"] = backup_dir if backup else ""
                    return report            # 失败即停，避免扩大影响

    # 3) config.json 内软缓存：先备份整个 config.json，再清空缓存键写回
    keys = report["config_keys"]
    if keys and cfg is not None and not dry_run:
        try:
            cfg_path = os.path.join(data_dir, "config.json")
            if backup and os.path.isfile(cfg_path):
                os.makedirs(backup_dir, exist_ok=True)
                shutil.copy2(cfg_path, os.path.join(backup_dir, "config.json"))
            for k in keys:
                cfg.data[k] = {}
            cfg.save()
        except Exception as e:               # noqa: BLE001
            report["failed"].append(("config.json 缓存键", str(e)[:120]))
    report["backup_dir"] = backup_dir if (backup and not dry_run
                                          and (report["cleaned"] or keys)) else ""
    return report


def restore(backup_dir, data_dir=None, project_dir=None, batch_size=10):
    """从备份目录恢复被清理的文件（撤销）。返回 (恢复数, 错误列表)。"""
    data_dir = os.path.abspath(data_dir or get_config_dir())
    project_dir = os.path.abspath(project_dir or os.getcwd())
    restored, errors = 0, []
    if not backup_dir or not os.path.isdir(backup_dir):
        return 0, ["备份目录不存在"]
    for cur, _dirs, files in os.walk(backup_dir):
        for f in files:
            src = os.path.join(cur, f)
            rel = os.path.relpath(src, backup_dir).replace("\\", "/")
            if rel.startswith("data/"):
                dst = os.path.join(data_dir, rel[5:])
            elif rel.startswith("project/"):
                dst = os.path.join(project_dir, rel[8:])
            elif f == "config.json":
                dst = os.path.join(data_dir, "config.json")
            else:
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                restored += 1
            except Exception as e:           # noqa: BLE001
                errors.append((src, str(e)[:120]))
            if restored + len(errors) >= int(batch_size or 10) * 20:
                break
    return restored, errors


def format_report(report):
    """清理结果纯文本摘要。"""
    r = report or {}
    prefix = "[试运行] " if r.get("dry_run") else ""
    lines = ["%s清理 %d 个文件，释放 %s，分 %d 批执行。" % (
        prefix, len(r.get("cleaned") or []),
        _fmt_size(r.get("freed_bytes", 0)), r.get("batches", 0))]
    if r.get("config_keys"):
        lines.append("清空配置内缓存键：%s" % "、".join(r["config_keys"]))
    if r.get("backup_dir"):
        lines.append("备份（可撤销）：%s" % r["backup_dir"])
    if r.get("failed"):
        lines.append("失败 %d 项：" % len(r["failed"]))
        for p, why in r["failed"][:5]:
            lines.append("  · %s → %s" % (p, why))
    return "\n".join(lines)
