# GitHub 开源复审 · v8.0

> 视角：开源维护者 / 社区。评估 V8.0 的开源就绪度、文档完整性、版本化分发清晰度。
> 评级：**B+**。

---

## 1. 开源基建（沿用 v7.6，六项齐备）

- ✅ `LICENSE`（商业 + MIT 源码）/ `SECURITY.md` / `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md`
- ✅ `.github/workflows/ci.yml` + Issue / PR 模板
- ✅ `.gitignore` 已忽略 `config.json` / `memory.json` / `*.key` / `dist/` / `build/`
- ✅ 自测可离线跑（`QT_QPA_PLATFORM=offscreen python selftest.py`，727 项）

## 2. 本轮新增的开源友好项

| 项 | 说明 | 证据 |
| --- | --- | --- |
| 模块零依赖 | `core/memory.py` / `core/reasoning.py` 纯标准库，降低贡献门槛 | — |
| API 开放文档 | 新增 `docs/API开放文档_v8_0.md`：记忆 / 推理对外接口契约 | 见同目录 |
| 版本化文件夹 | 每个版本独立完整目录 + zip，分发 / 回溯清晰（用户新要求） | `星语Starry-v8.0/` / `星语Starry-v7.6/` |
| 评审文档齐全 | 安全 / HR / 美术 / 资深 / GitHub / 创造力 / API 七份 + 本指南 | `docs/*_v8_0.md` |

## 3. 待补强（临门一脚）

| 项 | 等级 | 建议 |
| --- | --- | --- |
| Release 自动签名 | 中 | GitHub Actions 增加 Windows .exe 代码签名 job（v7.6 已列，v8.0 仍未上） |
| 依赖 SCAR | 低 | CI 增加 `pip-audit` 步骤（v7.6 GitHub 复审已建议，沿用） |
| 版本文件夹 CI 自动产出 | 低 | 在 Release workflow 中自动 `cp -r` + `zip` 生成 `星语Starry-vX.Y.Z/` |

## 4. 提交规范

```bash
git add -A
git commit -m "feat: v8.0.0 —— 长期记忆系统 · 深度思考引擎 · 版本化分发"
git tag v8.0.0
git push origin main --tags
```

## 5. GitHub 结论

开源基建完整、文档随版本同步、分发结构因「版本化文件夹」而显著清晰。距离满分仅差 **Release 自动签名** 与 **SCA** 两项工程化收尾（历史遗留，非 V8.0 引入）。

**评级：B+**（与 v7.6 持平；版本化分发为净加分项）。
