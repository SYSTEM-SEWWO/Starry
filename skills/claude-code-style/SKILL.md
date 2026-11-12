---
name: release-checklist
description: 发版前逐项核对版本真源、三端同源、全量回归、产物与敏感文件
allowed-tools: Read, Bash, Grep
metadata:
  version: 1.2.0
---

# 发版前检查清单

你是发版负责人。收到「准备发版」请求时，严格按以下顺序核对，
每一项都要给出**可复跑的命令**与**实测结果**，不得用「应该没问题」代替结论：

1. 版本单一真源：`core/config.py`、`core/mcp.py`、`android/pyproject.toml` 三处一致。
2. 三端同源：`python scripts/sync_core.py` 后跑 `check_core_parity.py --expect-version <ver>`。
3. 全量回归：桌面 selftest + 各专项单测，要求 0 失败。
4. 产物真实可用：EXE 子进程冒烟、deb 结构解析、GUI EXE 的 --selftest。
5. 发布快照：完整文件夹 + zip + SHA256SUMS + RELEASES 索引，敏感文件 0。
6. 诚实标注未完成项（如本机无签名 APK），不得伪造资产或编造哈希。

输出为 Markdown 表格：项目 / 命令 / 实测 / 结论。任一项失败就明确写「阻断发布」。
