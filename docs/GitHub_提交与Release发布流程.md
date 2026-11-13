# GitHub 提交与 Release 发布流程（星语 Starry）

> 适用：Windows / Git Bash、Linux、macOS。仓库根目录 = 含 `core/`、`ui/`、`.github/` 的目录。
> 本文所有命令都是**真实可执行**的标准 git / GitHub CLI 命令，不涉及任何虚构平台。
> v13.6.5 补充：详细提交流程 + 完整 Release 发布流程 + 一键脚本 + 排错清单。

---

## 0. 前置准备（只做一次）

### 0.1 安装工具

| 工具 | 用途 | 安装 |
| --- | --- | --- |
| Git | 本地版本库 / 推送 | <https://git-scm.com/download/win> |
| GitHub CLI `gh` | 建仓库 / 建 Release / 上传资产（可选但推荐） | `winget install --id GitHub.cli` 或 <https://cli.github.com/> |

检查：

```bash
git --version
gh --version          # 没有也能用网页版，见 §3.3
```

### 0.2 配置身份与换行符

```bash
git config user.name  "你的 GitHub 用户名"
git config user.email "你的 GitHub 绑定邮箱"
git config core.autocrlf input      # Windows 建议，避免整库 CRLF 警告
```

> 提交作者只对**新提交**生效。要改历史那一条：
> `git commit --amend --reset-author --no-edit`

### 0.3 登录 GitHub

```bash
gh auth login          # 选 GitHub.com → HTTPS → Login with a web browser
gh auth status         # 确认 Logged in to github.com
```

不用 `gh` 的话，HTTPS 推送需要在 GitHub → Settings → Developer settings →
Personal access tokens (classic) 生成 **repo** 权限的 token，推送时代替密码。
或用 SSH：

```bash
ssh-keygen -t ed25519 -C "你的邮箱"
# 把 ~/.ssh/id_ed25519.pub 的内容贴到 GitHub → Settings → SSH and GPG keys
ssh -T git@github.com
```

### 0.4 创建远程仓库并关联

网页版：<https://github.com/new> → 建**空**仓库（**不要**勾选 README / .gitignore / License，
否则本地首次 push 会因历史不一致被拒）。

或用 `gh`：

```bash
gh repo create 星语Starry --public --source=. --remote=origin
```

手动关联：

```bash
cd /c/Users/HP/WorkBuddy/hxw/星语Starry     # 换成你的实际路径
git remote -v                               # 应为空
git remote add origin https://github.com/<用户名>/<仓库名>.git
git branch -M main
git push -u origin main
```

> 当前本机仓库状态：已 `git init`（分支 `main`）、已提交 `8249d78`，
> **尚未配置 remote、尚未推送**。上面的 `git remote add` + `git push` 就是你要补的两步。

---

## 1. 日常提交流程（详细版）

### 1.1 提交前自检（本项目强制门禁）

```bash
python scripts/check_core_parity.py --expect-version 13.6.5
# 期望输出：
#   OK: core/ 与 android/core/ 完全一致（56 个文件…）
#   OK: 版本声明一致 = 13.6.5（3 处）
#   OK: 全量 Python 源码语法通过
#   PASS: 发布门禁全部通过
```

其他可选检查：

```bash
python -m py_compile main.py core/*.py ui/*.py app/*.py
python starry_cli.py --ui-layout          # 栏目布局诊断
python starry_cli.py --version            # 版本号单一真源
```

### 1.2 查看改了什么

```bash
git status                    # 概览
git status --porcelain        # 精简列表
git diff --stat               # 变更行数
git diff -- ui/chat_window.py # 逐行审阅某个文件
```

### 1.3 暂存

```bash
git add -A                                  # 全部（.gitignore 已排除 EXE / releases / 密钥）
git add core/uilayout.py ui/chat_window.py  # 或只暂存指定文件
```

**不会入库的内容**（`.gitignore` 已配置）：`星语Starry-GUI-*.exe`、
`*.exe.sha256`、`releases/`、`dist/`、`build/`、`config.json`、
`*.key`、`.env*`、`__pycache__/`。

> 单文件 >100 MB 会被 GitHub 拒绝。82 MB 的 EXE 不走 git，走 §3 的 Release 资产。

### 1.4 提交（约定式提交信息）

格式：`<type>(<scope>): <简述>`，正文用 `-` 列要点。

| type | 含义 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 修复 |
| `docs` | 文档 |
| `refactor` | 重构 |
| `test` | 测试 |
| `chore` | 构建 / CI / 版本 |

示例：

```bash
git commit -m "feat(ui): 栏目密度四档与即时切换

- core/uilayout.py: 紧凑/标准/宽松/超宽松，旧窗口尺寸一次性迁移
- ui/chat_window.py: 标题栏收纳菜单、状态栏显示版本、Ctrl+Alt+D 循环
- ui/settings_dialog.py: 外观页加密度下拉与恢复推荐布局
- docs: 补充 GitHub 提交与 Release 发布流程"
```

### 1.5 推送

```bash
git push origin main              # 首次后可简写 git push
git log --oneline -5              # 确认
```

### 1.6 推送被拒 / 冲突

```bash
git pull --rebase origin main     # 先变基到远端最新
# 若有冲突：编辑冲突文件 → git add <file> → git rebase --continue
git push origin main
```

> 不要 `git push --force` 覆盖共享分支；确实需要时用 `--force-with-lease`。

### 1.7 一键脚本

```bash
bash scripts/git_push.sh "feat(ui): 栏目密度四档与即时切换"
```

脚本会：检查在 git 仓库内 → 跑版本门禁 → `git add -A` → 有变更才提交 → 推送 → 打印结果。
无提交信息时自动生成 `chore: 更新 <日期时间>`。

---

## 2. 版本发布前的准备清单

发布 = **一次普通提交 + 一个 tag + 一个 GitHub Release**。顺序不能乱。

1. 升级版本号（**4 处必须一致**，`check_core_parity.py` 会校验前 3 处）：
   - `core/config.py` → `APP_VERSION`
   - `core/mcp.py` → `CLIENT_INFO["version"]`
   - `android/pyproject.toml` → `version`（2 处）
   - 同步 `android/core/config.py`、`android/core/mcp.py`（三端同源）
   - `.github/workflows/release.yml` 的 `workflow_dispatch.default`
   - `scripts/build_root_exe.py` 文档字符串示例
2. 更新文档：`CHANGELOG.md`、`RELEASE_NOTES.md`、`README.md`、`RELEASES.md`。
3. 跑门禁：`python scripts/check_core_parity.py --expect-version <版本>`。
4. 打包 GUI EXE：

```bash
python scripts/build_root_exe.py
# 产出（版本号自动从 core/config.py 读取）：
#   星语Starry-GUI-v<版本>.exe
#   星语Starry-GUI-v<版本>.exe.sha256
```

5. 校验哈希：

```bash
sha256sum -c 星语Starry-GUI-v13.6.5.exe.sha256
```

6. 提交并推送（§1）。
7. 打 tag 并推送（§3.1）。

---

## 3. Release 发布流程（详细版）

### 3.1 打 tag 触发自动发布（推荐）

`.github/workflows/release.yml` 监听 `push tags: v*.*.*`，会依次执行：

| Job | 内容 |
| --- | --- |
| `verify` | 版本一致性 + 三端同源 + 全量自测 + 历史回归 |
| `snapshot` | 生成完整版本文件夹 + zip + 校验和 + RELEASES 索引 |
| `root-exe` | Windows 运行器真实打包 `星语Starry-GUI-v<版本>.exe` + `.sha256` |
| `publish` | 用 `softprops/action-gh-release@v2` 创建 Release，正文取 `RELEASE_NOTES.md`，上传 zip / 校验和 / EXE |

命令：

```bash
V=13.6.5
git tag -a "v$V" -m "v$V 栏目密度四档 / GitHub 提交与 Release 流程"
git push origin "v$V"
```

随后：

```bash
gh run list --workflow=release.yml --limit 3     # 看运行状态
gh run watch                                     # 实时跟随
gh release view "v13.6.5"                        # 看发布结果
```

> `workflow_dispatch` 也能手动触发（填版本号），但 `publish` job 带
> `if: startsWith(github.ref, 'refs/tags/')`，**只有真正的 tag 推送才创建 Release**；
> 手动触发只跑校验与打包。

### 3.2 手动发布（无 CI 或想自己传 EXE）

```bash
V=13.6.5
EXE="星语Starry-GUI-v$V.exe"
SUM="$EXE.sha256"

# 1) 确保本地已打包并校验
python scripts/build_root_exe.py
sha256sum -c "$SUM"

# 2) 建 Release 并上传资产（正文用 RELEASE_NOTES.md）
gh release create "v$V" \
  --title "星语 Starry v$V" \
  --notes-file RELEASE_NOTES.md \
  "$EXE" "$SUM" \
  releases/*.zip releases/SHA256SUMS-*.txt

# 3) 核对
gh release view "v$V" --json tagName,assets,url
```

一键脚本（含门禁 + 打包 + 校验 + 建 Release）：

```bash
bash scripts/github_release.sh 13.6.5
```

脚本只做本地准备与 `gh release create`；**tag 推送由你确认后执行**，
避免误发。加 `--tag` 参数才会创建并推送 tag。

### 3.3 网页版发布（不装 gh）

1. <https://github.com/<用户名>/<仓库名>/releases/new>
2. 「Choose a tag」输入 `v13.6.5` → 「Create new tag on publish」
3. Target 选 `main`；标题 `星语 Starry v13.6.5`
4. 正文粘贴 `RELEASE_NOTES.md` 内容
5. 「Attach binaries」拖入：
   - `星语Starry-GUI-v13.6.5.exe`
   - `星语Starry-GUI-v13.6.5.exe.sha256`
   - `releases/星语Starry-v13.6.5.zip`（若有）
6. 勾「Set as the latest release」→ **Publish release**

### 3.4 发布后校验清单

- [ ] `gh release view v13.6.5` 显示资产数与预期一致
- [ ] 下载 EXE 后本地 `sha256sum -c` 通过
- [ ] `星语Starry-GUI-v13.6.5.exe` 双击可启动，状态栏显示 `v13.6.5`
- [ ] `RELEASES.md` 索引已追加该版本（CI 的 `publish` job 会回写）
- [ ] `update-manifest.yml` 生成的 `update.json` 指向新版本

---

## 4. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `remote origin already exists` | 已关联过 | `git remote set-url origin <新地址>` |
| `rejected – non-fast-forward` | 远端有本地没有的提交 / 建仓库时勾了 README | `git pull --rebase origin main` 后重推；空仓库别勾初始化文件 |
| `Authentication failed` | token 过期 / 权限不足 | 重新 `gh auth login`，或换新 PAT（需 `repo` 权限） |
| `LF will be replaced by CRLF` 刷屏 | Windows 换行符 | 无害；`git config core.autocrlf input` 可减少 |
| `File exceeds 100 MB` | 把 EXE 加进了 git | 从 git 移除并靠 Release 分发：`git rm --cached <exe>`，确认 `.gitignore` 有 `星语Starry-GUI-*.exe` |
| tag 推送后 CI 没触发 | tag 名不符合 `v*.*.*` | 必须是 `v13.6.5`，不能是 `13.6.5` |
| CI `verify` 失败：版本不一致 | tag 与 `APP_VERSION` 不同 | 改 `core/config.py` 后重新提交、重新打 tag |
| Release 只有正文没有 EXE | `root-exe` job 失败 | 看 Actions 日志；本地 `python scripts/build_root_exe.py` 复现 |
| 中文目录启动报 `no Qt platform plugin` | Qt 5 无法加载含中文的插件路径 | v13.6.5 起 `main.py::_fix_qt_plugin_path()` 已自动兜底；或直接双击 EXE |

---

## 5. 相关文件

| 文件 | 作用 |
| --- | --- |
| `scripts/git_push.sh` | 一键：门禁 → 提交 → 推送 |
| `scripts/github_release.sh` | 一键：门禁 → 打包 → 校验 → 建 Release（可选推 tag） |
| `scripts/check_core_parity.py` | 版本单一真源 + 三端同源 + 语法门禁 |
| `scripts/build_root_exe.py` | 打包带版本后缀的 GUI EXE + SHA-256 |
| `scripts/verify_release.py` | 快照 / 校验和 / 索引终验 |
| `.github/workflows/release.yml` | tag → 校验 → 快照 → EXE → 发布 Release |
| `.github/workflows/ci.yml` | push / PR 常规持续集成 |
| `RELEASE_NOTES.md` | 当前版发布说明（Release 正文来源） |
| `RELEASES.md` | 历史版本索引（CI 自动回写） |
| `CHANGELOG.md` | 逐版本变更记录 |
