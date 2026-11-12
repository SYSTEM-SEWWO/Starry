---
name: offline-workbench
description: 在完全离线的环境里演示「整体项目 → 多线并行 → 汇总」流程
allowed-tools: Read
---

# 离线工作台演示

不联网、不调用模型、不消耗 token。用星语 CLI 依次执行：

1. `--project "<目标>"` 生成整体项目；
2. `--project "<目标>" --parallel --workers 4` 分波并行；
3. `--workbench` 打印环境 / 项目 / 并行 / 更新 / 命令速查五段总览。

说明「整体项目」是实体、并行只是它的调度方式；项目可存成 `.starryproj` 断点续跑。
