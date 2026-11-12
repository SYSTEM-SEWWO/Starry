# -*- coding: utf-8 -*-
"""星语 Starry · 多线并行执行器（v13.0 大版本新增，纯逻辑）。

整体项目（core.project）负责「做什么」，本模块负责「怎么同时做」：
    - 每条线独立 try，单线异常 / 超时绝不扩散到其它线；
    - 结果按**输入顺序**回填，不因完成先后打乱；
    - 支持并发度、整体超时、失败重试；
    - 默认 worker 是纯本地确定性执行器（不联网、不需要 API Key），
      因此 Windows EXE / Linux deb 开箱即可跑通完整并行流程。

只用标准库；不读写文件（check 任务只读路径是否存在）、不访问全局状态。
"""
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout

from core import project as _project

DEFAULT_WORKERS = 4

__all__ = [
    "DEFAULT_WORKERS", "split_work", "local_worker", "run_parallel",
    "run_project", "merge_results",
]


def split_work(items, lanes):
    """把任务轮转分配到 N 条线，返回 lanes 个列表（不足则空列表）。"""
    items = list(items or [])
    n = max(1, int(lanes or 1))
    out = [[] for _ in range(n)]
    for i, item in enumerate(items):
        out[i % n].append(item)
    return out


def local_worker(job):
    """默认离线执行器：按 kind 产出确定性结果，零联网、零模型调用。

    text   文本统计（字符 / 行 / 词 / 高频词）
    check  校验（文本非空、可选路径存在）
    report 生成一段 Markdown 报告片段
    chat   需要模型，明确报错（由 CLI 在配置好 Key 时换用真实 worker）
    """
    job = job or {}
    kind = job.get("kind", "text")
    payload = job.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"text": str(payload)}
    text = str(payload.get("text", "") or "")

    if kind == "check":
        checks = ["目标文本%s（%d 字）" % ("非空" if text.strip() else "为空",
                                       len(text))]
        path = payload.get("path")
        if path:
            checks.append("路径 `%s`：%s" % (
                path, "存在" if os.path.exists(str(path)) else "不存在"))
        return {"type": "check", "passed": bool(text.strip()),
                "checks": checks}

    if kind == "report":
        sources = payload.get("sources") or []
        body = text[:400] or "（无内容）"
        return {"type": "report",
                "markdown": "### %s\n\n%s\n\n> 汇总来源：%s\n" % (
                    job.get("title") or "任务", body,
                    ", ".join(str(s) for s in sources) or "无")}

    if kind == "chat":
        raise RuntimeError(
            "chat 任务需要模型与 API Key；请用 --execute 或在桌面端配置服务商")

    # 默认 text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", text)
    return {
        "type": "text",
        "chars": len(text),
        "lines": len(lines),
        "words": len(re.findall(r"\S+", text)),
        "keywords": [w for w, _ in Counter(words).most_common(5)],
    }


def run_parallel(jobs, worker=None, max_workers=DEFAULT_WORKERS,
                 timeout=None, retries=0):
    """并行执行 jobs，返回结构化汇总（结果按输入顺序）。

    :param jobs: list[dict]，至少含 id / title，可含 kind / payload
    :param worker: callable(job) -> 任意 JSON 可序列化结果；默认 local_worker
    :param max_workers: 并发度（线数）
    :param timeout: 整体超时秒数，None 表示不限
    :param retries: 每条线失败后的额外重试次数
    """
    worker = worker or local_worker
    jobs = [dict(j or {}) for j in (jobs or [])]
    lanes = max(1, int(max_workers or 1))
    t0 = time.time()
    results = [None] * len(jobs)
    if not jobs:
        return {"results": [], "ok": 0, "failed": 0, "total": 0,
                "workers": lanes, "elapsed_ms": 0, "timed_out": False,
                "order": []}

    attempts = max(0, int(retries or 0)) + 1

    def _call(job):
        last = None
        for _ in range(attempts):
            try:
                return {"ok": True, "value": worker(job)}
            except Exception as exc:                # noqa: BLE001
                last = exc
        return {"ok": False,
                "error": "%s: %s" % (type(last).__name__, last)}

    timed_out = False
    ex = ThreadPoolExecutor(max_workers=lanes)
    futs = {}
    try:
        for i, job in enumerate(jobs):
            futs[ex.submit(_call, job)] = i
        try:
            for fut in as_completed(futs, timeout=timeout):
                i = futs[fut]
                try:
                    r = fut.result()
                except Exception as exc:            # noqa: BLE001
                    r = {"ok": False,
                         "error": "%s: %s" % (type(exc).__name__, exc)}
                job = jobs[i]
                results[i] = {
                    "id": job.get("id") or ("job-%d" % (i + 1)),
                    "title": job.get("title") or ("任务 %d" % (i + 1)),
                    "ok": bool(r.get("ok")),
                    "value": r.get("value"),
                    "error": str(r.get("error") or ""),
                }
        except FuturesTimeout:
            timed_out = True
    finally:
        # 超时后不等待剩余线程，避免 CLI 卡死
        ex.shutdown(wait=False, cancel_futures=True)

    for i, job in enumerate(jobs):
        if results[i] is None:
            results[i] = {
                "id": job.get("id") or ("job-%d" % (i + 1)),
                "title": job.get("title") or ("任务 %d" % (i + 1)),
                "ok": False, "value": None,
                "error": "整体超时未返回" if timed_out else "未执行",
            }
    ok = sum(1 for r in results if r["ok"])
    return {
        "results": results,
        "ok": ok,
        "failed": len(results) - ok,
        "total": len(results),
        "workers": lanes,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "timed_out": timed_out,
        "order": [r["id"] for r in results],
    }


def run_project(project, worker=None, max_workers=DEFAULT_WORKERS,
                timeout=None, retries=0):
    """按依赖**分波并行**执行整个项目，返回 (新项目, 每波报告列表)。

    第一波：所有无依赖任务并行；后续波：依赖全部 done 的任务并行。
    依赖失败的任务最终标记为 skipped，避免循环依赖导致死循环。
    """
    p = _project.clone(project or {})
    waves = []
    guard = 0
    while guard < 100:                       # 防御性上限，杜绝死循环
        guard += 1
        ready = _project.ready_tasks(p)
        if not ready:
            break
        for t in ready:
            p = _project.update_task(p, t["id"],
                                     status=_project.TASK_RUNNING)
        job_dicts = [_project.clone(t) for t in ready]
        report = run_parallel(job_dicts, worker=worker,
                              max_workers=max_workers,
                              timeout=timeout, retries=retries)
        waves.append(report)
        by_id = {r["id"]: r for r in report["results"]}
        for t in ready:
            r = by_id.get(t["id"], {})
            p = _project.update_task(
                p, t["id"],
                status=(_project.TASK_DONE if r.get("ok")
                        else _project.TASK_FAILED),
                result=r.get("value"),
                error=r.get("error", ""))
    # 剩余 pending：依赖失败 / 循环依赖 → skipped
    for t in p.get("tasks", []):
        if t.get("status") == _project.TASK_PENDING:
            p = _project.update_task(p, t["id"],
                                     status=_project.TASK_SKIPPED,
                                     error="依赖未完成或存在循环依赖")
    return p, waves


def merge_results(report, title="多线并行汇总"):
    """把并行报告汇总成一份 Markdown（各线结果按输入顺序）。"""
    r = report or {}
    lines = [
        "## %s" % title, "",
        "> 并行度 %s · 成功 %s · 失败 %s · 总耗时 %s ms%s"
        % (r.get("workers", 0), r.get("ok", 0), r.get("failed", 0),
           r.get("elapsed_ms", 0), "（超时）" if r.get("timed_out") else ""),
        "", "| # | 线 | 状态 | 结果 / 错误 |", "| --- | --- | --- | --- |",
    ]
    for i, item in enumerate(r.get("results", []), 1):
        detail = item.get("error") or str(item.get("value") or "")
        detail = detail.replace("\n", " ").replace("|", "\\|")[:140]
        lines.append("| %d | %s | %s | %s |" % (
            i, item.get("title", ""), "✓" if item.get("ok") else "✗", detail))
    return "\n".join(lines) + "\n"
