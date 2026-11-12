# -*- coding: utf-8 -*-
"""星语 Starry · 整体项目层（v13.0 大版本新增，纯逻辑）。

「多线并行」前面要先有一个**整体项目**：项目持有目标、任务、依赖与产物，
并行执行器（core.parallel）只是它的调度方式之一。这样用户面对的是
「一个项目跑完了没有」，而不是一堆散落的对话与临时结果。

设计约束（与 v12.0 core/stardust.py 一致）：
    - 只用标准库；零 GUI / 零网络 / 零第三方依赖。
    - 不读写文件、不访问全局状态；时间戳由调用方传入。
    - **不修改入参**：所有变更函数返回新的 project 字典。
    - 可序列化为 .starryproj（magic / version / payload / SHA-256 checksum），
      损坏、版本不符、结构错误一律拒绝。

任务状态机： pending → running → done / failed / skipped
依赖：task["depends"] 是 task_id 列表；只有依赖全部 done 的任务才会
      出现在 ready_tasks() 中，天然形成「分波并行」。
"""
import hashlib
import json
import re

PROJECT_MAGIC = "STARRY-PROJECT"
PROJECT_VERSION = 1

TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_DONE = "done"
TASK_FAILED = "failed"
TASK_SKIPPED = "skipped"
TASK_STATES = (TASK_PENDING, TASK_RUNNING, TASK_DONE, TASK_FAILED, TASK_SKIPPED)

VALID_KINDS = ("text", "check", "report", "chat")

__all__ = [
    "PROJECT_MAGIC", "PROJECT_VERSION",
    "TASK_PENDING", "TASK_RUNNING", "TASK_DONE", "TASK_FAILED", "TASK_SKIPPED",
    "TASK_STATES", "VALID_KINDS",
    "clone", "new_task", "create_project", "add_task", "update_task",
    "find_task", "ready_tasks", "project_progress", "plan_from_goal",
    "project_digest", "pack_project", "unpack_project",
    "render_project_markdown",
]


def clone(obj):
    """深拷贝（仅 JSON 可序列化数据），保证纯函数不修改入参。"""
    return json.loads(json.dumps(obj, ensure_ascii=False))


def _slug(text, limit=40):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", str(text or "").strip())
    return (s.strip("-")[:limit] or "task").lower()


def new_task(title, kind="text", payload=None, depends=None, task_id=None):
    """构造一个任务字典。

    :param kind: "text" 本地文本分析 / "check" 本地校验 /
                 "report" 生成报告片段 / "chat" 调用模型（需 API Key）
    :param depends: 依赖的 task_id 列表
    """
    if kind not in VALID_KINDS:
        kind = "text"
    return {
        "id": str(task_id or _slug(title)),
        "title": str(title or "未命名任务"),
        "kind": kind,
        "status": TASK_PENDING,
        "depends": [str(d) for d in (depends or [])],
        "payload": clone(payload if isinstance(payload, dict)
                         else ({"text": str(payload)} if payload else {})),
        "result": None,
        "error": "",
        "ts": None,
    }


def create_project(title, goal="", tasks=None, meta=None):
    """创建整体项目。tasks 可为 list[str] 或 list[dict] / list[new_task(...)]。"""
    out = []
    seen = set()
    for i, item in enumerate(tasks or []):
        if isinstance(item, str):
            t = new_task(item, task_id="t%d" % (i + 1))
        elif isinstance(item, dict):
            t = new_task(
                item.get("title") or ("任务 %d" % (i + 1)),
                kind=item.get("kind", "text"),
                payload=item.get("payload"),
                depends=item.get("depends"),
                task_id=item.get("id") or "t%d" % (i + 1))
            # 允许直接传入完整任务字典（保留状态 / 结果）
            for k in ("status", "result", "error", "ts"):
                if k in item:
                    t[k] = item[k]
        else:
            continue
        base, n = t["id"], 2
        while t["id"] in seen:
            t["id"] = "%s-%d" % (base, n)
            n += 1
        seen.add(t["id"])
        out.append(t)
    return {
        "title": str(title or "未命名项目"),
        "goal": str(goal or ""),
        "created": None,
        "meta": clone(meta or {}),
        "tasks": out,
    }


def add_task(project, title, kind="text", payload=None, depends=None,
             task_id=None):
    """返回**新**项目；原 project 不被修改。"""
    p = clone(project or {})
    p.setdefault("tasks", [])
    used = {t.get("id") for t in p["tasks"]}
    t = new_task(title, kind=kind, payload=payload, depends=depends,
                 task_id=task_id)
    base, n = t["id"], 2
    while t["id"] in used:
        t["id"] = "%s-%d" % (base, n)
        n += 1
    p["tasks"].append(t)
    return p


def update_task(project, task_id, *, status=None, result=None, error=None,
                ts=None):
    """更新单个任务状态；找不到任务时原样返回新拷贝，不抛异常。"""
    p = clone(project or {})
    for t in p.get("tasks", []):
        if t.get("id") == str(task_id):
            if status is not None:
                if status not in TASK_STATES:
                    status = TASK_FAILED
                t["status"] = status
            if result is not None:
                t["result"] = result
            if error is not None:
                t["error"] = str(error)
            if ts is not None:
                t["ts"] = ts
            break
    return p


def find_task(project, task_id):
    for t in (project or {}).get("tasks", []):
        if t.get("id") == str(task_id):
            return t
    return None


def ready_tasks(project):
    """依赖已全部 done、且自身仍 pending 的任务（可分波并行）。"""
    tasks = (project or {}).get("tasks", [])
    done = {t.get("id") for t in tasks if t.get("status") == TASK_DONE}
    out = []
    for t in tasks:
        if t.get("status") != TASK_PENDING:
            continue
        deps = t.get("depends") or []
        if all(d in done for d in deps):
            out.append(t)
    return out


def project_progress(project):
    """项目进度概览；空项目返回全 0 且 percent=0，不抛异常。"""
    tasks = (project or {}).get("tasks", [])
    counts = {s: 0 for s in TASK_STATES}
    for t in tasks:
        counts[t.get("status", TASK_PENDING)] = counts.get(
            t.get("status", TASK_PENDING), 0) + 1
    total = len(tasks)
    finished = counts[TASK_DONE] + counts[TASK_FAILED] + counts[TASK_SKIPPED]
    return {
        "total": total,
        "done": counts[TASK_DONE],
        "failed": counts[TASK_FAILED],
        "running": counts[TASK_RUNNING],
        "pending": counts[TASK_PENDING],
        "skipped": counts[TASK_SKIPPED],
        "finished": finished,
        "percent": (100 * counts[TASK_DONE] // total) if total else 0,
        "complete": bool(total) and counts[TASK_PENDING] == 0
                    and counts[TASK_RUNNING] == 0,
    }


def plan_from_goal(goal, steps=None, title=None):
    """把一个目标拆成默认「三条并行 + 一条汇总」的项目（本地确定性，不调模型）。

    这是 WorkBuddy 式「整体项目 → 多线并行」的最小可运行模板：
    前三条互不依赖可并行，最后一条依赖前三条，自动形成第二波。
    """
    default_steps = [
        ("资料盘点", "check", {"text": goal}),
        ("要点提炼", "text", {"text": goal}),
        ("方案草拟", "report", {"text": goal}),
    ]
    chosen = steps if steps is not None else default_steps
    tasks = []
    for i, item in enumerate(chosen):
        if isinstance(item, str):
            tasks.append(new_task(item, kind="text",
                                  payload={"text": goal},
                                  task_id="t%d" % (i + 1)))
        else:
            seq = list(item)
            name = seq[0] if seq else "任务 %d" % (i + 1)
            kind = seq[1] if len(seq) > 1 else "text"
            payload = seq[2] if len(seq) > 2 else {"text": goal}
            tasks.append(new_task(name, kind=kind,
                                  payload=payload or {"text": goal},
                                  task_id="t%d" % (i + 1)))
    deps = [t["id"] for t in tasks]
    tasks.append(new_task("结果复核与汇总", kind="report",
                          payload={"text": goal, "sources": deps},
                          depends=deps, task_id="t%d" % (len(tasks) + 1)))
    return create_project(title or (str(goal)[:24] or "新项目"),
                          goal=goal, tasks=tasks,
                          meta={"planner": "local-template", "lanes": len(tasks) - 1})


# ---------------------------------------------------------------------------
# .starryproj 存档
# ---------------------------------------------------------------------------
def project_digest(project):
    canonical = json.dumps(project, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def pack_project(project):
    """序列化为 .starryproj 文本（UTF-8 JSON）。"""
    env = {
        "magic": PROJECT_MAGIC,
        "version": PROJECT_VERSION,
        "payload": clone(project or {}),
    }
    env["checksum"] = project_digest(env["payload"])
    return json.dumps(env, ensure_ascii=False, indent=2)


def unpack_project(text):
    """解析 .starryproj；结构 / 版本 / 校验失败一律 ValueError。"""
    try:
        env = json.loads(text) if isinstance(text, (str, bytes)) else dict(text)
    except Exception as exc:                             # noqa: BLE001
        raise ValueError("项目文件不是合法 JSON：%s" % exc)
    if not isinstance(env, dict):
        raise ValueError("项目文件根节点必须是对象")
    if env.get("magic") != PROJECT_MAGIC:
        raise ValueError("不是 .starryproj 项目（magic 不匹配）")
    version = env.get("version")
    if not isinstance(version, int) or version <= 0 or version > PROJECT_VERSION:
        raise ValueError("不支持的项目版本：%r" % (version,))
    payload = env.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        raise ValueError("项目结构损坏（缺 tasks 列表）")
    if env.get("checksum") != project_digest(payload):
        raise ValueError("项目校验失败（内容被修改或传输损坏）")
    return clone(payload)


def render_project_markdown(project, report=None):
    """渲染项目报告（Markdown），可附带并行执行汇总。"""
    p = project or {}
    prog = project_progress(p)
    icon = {
        TASK_DONE: "✓", TASK_FAILED: "✗", TASK_RUNNING: "…",
        TASK_PENDING: "·", TASK_SKIPPED: "-",
    }
    lines = [
        "# 项目 · %s" % p.get("title", "未命名项目"), "",
        "> 目标：%s" % (p.get("goal") or "（未填写）"),
        "> 进度：%d%% · 完成 %d / %d · 失败 %d · 待办 %d"
        % (prog["percent"], prog["done"], prog["total"],
           prog["failed"], prog["pending"]),
        "", "| 状态 | 任务 | 类型 | 依赖 |", "| --- | --- | --- | --- |",
    ]
    for t in p.get("tasks", []):
        lines.append("| %s | %s | `%s` | %s |" % (
            icon.get(t.get("status"), "?"), t.get("title", ""),
            t.get("kind", ""), ", ".join(t.get("depends") or []) or "—"))
    if report:
        lines += ["", "## 多线并行执行", "",
                  "并行度 %s · 成功 %s · 失败 %s · 耗时 %s ms" % (
                      report.get("workers"), report.get("ok"),
                      report.get("failed"), report.get("elapsed_ms")), ""]
        for r in report.get("results", []):
            lines.append("- **%s** %s：%s" % (
                "✓" if r.get("ok") else "✗", r.get("title", ""),
                str(r.get("error") or r.get("value") or "")[:160]))
    return "\n".join(lines) + "\n"
