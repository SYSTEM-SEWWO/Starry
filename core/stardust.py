# -*- coding: utf-8 -*-
"""星语 Starry · 星尘模块（v12.0 大版本新增，纯逻辑层）。

三个跨三端复用的能力，**零 GUI 框架依赖、零网络、零第三方依赖**，
全部是确定性纯函数，可在 PC / CLI / Android 上字节一致地运行并单测：

    1. build_echo_card   星尘卡：把一次问答（思考 + 回答 + 分支锚点 + token
                         量级）收成一张可复制的 Markdown 小卡。不调用模型、
                         零 token、零联网，把「深度思考可视化」从看的过程
                         变成能带走的产物。
    2. plan_trim          上下文预算：长对话超预算前，给出确定性的「保留哪些
                         消息」计划，只返回下标，不修改入参、不发请求。
    3. pack_archive /    可移植 .starry 存档：会话 + 记忆 + 收藏 + 分支装进
       unpack_archive    带版本与 SHA-256 校验的信封，三端互导，损坏即拒绝。

设计约束（评审要求）：
    - 不 import 任何 PyQt / Toga / requests；只用标准库。
    - 不读写文件、不访问全局状态；时间戳等外部信息一律由调用方传入。
    - 不修改入参；返回新对象。
    - 与 core/insights.py 的 estimate_tokens 口径一致（此处独立实现一份，
      避免 import sessions 造成循环依赖）。
"""
import hashlib
import json
import re

ARCHIVE_MAGIC = "STARRY-ARCHIVE"
ARCHIVE_VERSION = 1

__all__ = [
    "ARCHIVE_MAGIC", "ARCHIVE_VERSION",
    "estimate_tokens", "build_echo_card", "plan_trim",
    "pack_archive", "unpack_archive", "archive_digest",
]


# ---------------------------------------------------------------------------
# 1) 轻量 token 估算（离线相对估算，不代表任何模型的精确计费）
# ---------------------------------------------------------------------------
def estimate_tokens(text):
    """粗略估算 token 数：CJK 按 1 字 1 token，其余按 4 字符 1 token。"""
    if not text:
        return 0
    s = str(text)
    cjk = len(re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", s))
    other = len(s) - cjk
    return int(cjk + (other + 3) // 4)


def _first_sentence(text, limit=120):
    """取首句；没有句读时按长度截断，结果不含换行。"""
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return ""
    m = re.split(r"(?<=[。.!?！？；;])", s, maxsplit=1)
    out = m[0].strip()
    if len(out) > limit:
        out = out[:limit].rstrip() + "…"
    return out


# ---------------------------------------------------------------------------
# 2) 星尘卡
# ---------------------------------------------------------------------------
def build_echo_card(title="本轮问答", reasoning="", answer="", prompt="",
                    branched_from=None, ts=None, max_answer_chars=400):
    """生成一张 Markdown 星尘卡，纯字符串操作，确定性输出。

    :param title: 卡片标题
    :param reasoning: 本轮思考过程全文（可为分片拼接结果）
    :param answer: 本轮最终回答
    :param prompt: 用户提问（只取首句，避免卡片过长）
    :param branched_from: 分支来源会话 id（没有则 None）
    :param ts: 时间戳字符串，**由调用方传入**以保证纯函数确定性；
               不传则省略时间行。
    :param max_answer_chars: 回答摘录长度上限
    :return: Markdown 字符串；同输入必得同输出
    """
    reasoning = reasoning or ""
    answer = answer or ""
    prompt = prompt or ""
    chunks = [c for c in re.split(r"\n+", reasoning) if c.strip()]
    think_bits = [_first_sentence(c, 80) for c in chunks if _first_sentence(c, 80)]
    if not think_bits and reasoning.strip():
        think_bits = [_first_sentence(reasoning, 80)]

    lines = ["✦ 星尘卡", "", "**%s**" % (title or "本轮问答")]
    if ts:
        lines.append("`%s`" % ts)
    lines.append("")
    if prompt.strip():
        lines.append("- **问**：%s" % _first_sentence(prompt, 120))
    if think_bits:
        lines.append("- **思考起点**：%s" % think_bits[0])
        if len(think_bits) > 1:
            lines.append("- **思考落点**：%s" % think_bits[-1])
    answer_excerpt = (answer.strip()[:max_answer_chars].rstrip()
                      + ("…" if len(answer.strip()) > max_answer_chars else ""))
    lines.append("- **答**：%s" % (answer_excerpt or "（无正文）"))
    lines.append("")
    lines.append("> 思考分片 %d · 约 %d tokens · 分支锚点 %s" % (
        len(chunks), estimate_tokens(answer), branched_from or "无"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3) 上下文预算裁剪计划
# ---------------------------------------------------------------------------
def plan_trim(messages, max_tokens, policy="keep_recent", keep_system=True):
    """给出「保留哪些消息」的确定性计划，不修改入参、不发任何请求。

    :param messages: [{"role": ..., "content": ...}, ...]
    :param max_tokens: 预算上限（token 估算值）
    :param policy: "keep_recent" 从最新往前保 / "keep_first" 从最旧往后保
                   / "keep_ends" 保头尾（系统提示 + 最近若干轮）
    :param keep_system: 是否永远保留 role=="system" 的消息
    :return: dict{keep_indices, drop_indices, kept_tokens, total_tokens,
                  trimmed, policy, max_tokens}
    """
    msgs = list(messages or [])
    costs = []
    for m in msgs:
        content = m.get("content", "") if isinstance(m, dict) else str(m)
        costs.append(estimate_tokens(content) + 4)   # 4 = 角色/分隔开销
    total = sum(costs)
    budget = max(0, int(max_tokens or 0))
    keep = set()
    used = 0

    # 系统消息优先保留（计入预算）
    if keep_system:
        for i, m in enumerate(msgs):
            if isinstance(m, dict) and m.get("role") == "system":
                if used + costs[i] <= budget or budget == 0:
                    keep.add(i)
                    used += costs[i]

    others = [i for i in range(len(msgs)) if i not in keep]
    if policy == "keep_first":
        order = others
    elif policy == "keep_ends":
        # 保住最早一轮与最近若干轮：先取尾部 3/4 预算，再补头部
        order = list(reversed(others))
    else:                                              # keep_recent（默认）
        order = list(reversed(others))

    for i in order:
        if used + costs[i] <= budget:
            keep.add(i)
            used += costs[i]

    if policy == "keep_ends" and len(others) > 2:
        for i in others[:2]:
            if i not in keep and used + costs[i] <= budget:
                keep.add(i)
                used += costs[i]

    keep_indices = [i for i in range(len(msgs)) if i in keep]
    drop_indices = [i for i in range(len(msgs)) if i not in keep]
    return {
        "keep_indices": keep_indices,
        "drop_indices": drop_indices,
        "kept_tokens": sum(costs[i] for i in keep_indices),
        "total_tokens": total,
        "trimmed": bool(drop_indices),
        "policy": policy,
        "max_tokens": budget,
    }


# ---------------------------------------------------------------------------
# 4) 可移植 .starry 存档
# ---------------------------------------------------------------------------
def archive_digest(payload):
    """对规范化 JSON 计算 SHA-256，作为存档完整性校验值。"""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def pack_archive(sessions=None, memory=None, meta=None):
    """把会话/记忆/元信息打成 .starry 信封文本（JSON，UTF-8 可直接写文件）。

    sessions/memory 支持 dict 或 list；原样深拷贝进信封，不修改入参。
    """
    payload = {
        "sessions": json.loads(json.dumps(sessions or {}, ensure_ascii=False)),
        "memory": json.loads(json.dumps(memory or {}, ensure_ascii=False)),
        "meta": json.loads(json.dumps(meta or {}, ensure_ascii=False)),
    }
    envelope = {
        "magic": ARCHIVE_MAGIC,
        "version": ARCHIVE_VERSION,
        "payload": payload,
    }
    envelope["checksum"] = archive_digest(payload)
    return json.dumps(envelope, ensure_ascii=False, indent=2)


def unpack_archive(text):
    """解析 .starry 信封；版本不符 / 校验失败 / 结构损坏一律抛 ValueError。

    成功返回 {"version", "meta", "sessions", "memory"}（新字典，不共享引用）。
    """
    try:
        env = json.loads(text) if isinstance(text, (str, bytes)) else dict(text)
    except Exception as exc:                             # noqa: BLE001
        raise ValueError("存档不是合法 JSON：%s" % exc)
    if not isinstance(env, dict):
        raise ValueError("存档根节点必须是对象")
    if env.get("magic") != ARCHIVE_MAGIC:
        raise ValueError("不是 .starry 存档（magic 不匹配）")
    version = env.get("version")
    if not isinstance(version, int) or version <= 0 or version > ARCHIVE_VERSION:
        raise ValueError("不支持的存档版本：%r" % (version,))
    payload = env.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("存档 payload 缺失或结构损坏")
    expected = archive_digest(payload)
    if env.get("checksum") != expected:
        raise ValueError("存档校验失败（内容被修改或传输损坏）")
    for key in ("sessions", "memory", "meta"):
        if key not in payload:
            raise ValueError("存档缺少字段：%s" % key)
    return {
        "version": version,
        "sessions": json.loads(json.dumps(payload["sessions"], ensure_ascii=False)),
        "memory": json.loads(json.dumps(payload["memory"], ensure_ascii=False)),
        "meta": json.loads(json.dumps(payload["meta"], ensure_ascii=False)),
    }
