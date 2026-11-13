#!/usr/bin/env bash
# 星语 Starry · 一键提交并推送到 GitHub（v13.6.5）
#
# 用法：
#   bash scripts/git_push.sh "feat(ui): 栏目密度四档与即时切换"
#   bash scripts/git_push.sh                      # 自动生成提交信息
#   bash scripts/git_push.sh --dry-run "msg"     # 只预览，不提交不推送
#
# 流程：仓库检查 → 版本门禁 → git add -A → 有变更才 commit → push。
set -euo pipefail

cd "$(dirname "$0")/.."

MSG="${1:-}"
DRY=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY=1
  MSG="${2:-}"
fi
if [[ -z "$MSG" ]]; then
  MSG="chore: 更新 $(date '+%Y-%m-%d %H:%M:%S')"
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "✗ 当前目录不是 git 仓库" >&2
  exit 1
fi

echo "==> 1/4 版本与三端同源门禁"
PY=python
command -v python >/dev/null 2>&1 || PY=python3
VERSION=$("$PY" -c "import re;print(re.search(r'APP_VERSION\s*=\s*[\"\']([^\"\']+)',open('core/config.py',encoding='utf-8').read()).group(1))")
"$PY" scripts/check_core_parity.py --expect-version "$VERSION" || {
  echo "✗ 门禁未通过，已中止提交" >&2
  exit 1
}

echo "==> 2/4 待提交变更"
git status --porcelain | head -30
if [[ -z "$(git status --porcelain)" ]]; then
  echo "没有待提交的变更，跳过 commit。"
else
  if [[ $DRY -eq 1 ]]; then
    echo "[dry-run] 将执行: git add -A && git commit -m '$MSG'"
  else
    git add -A
    git commit -m "$MSG"
  fi
fi

echo "==> 3/4 远端配置"
REMOTE=$(git remote get-url origin 2>/dev/null || true)
if [[ -z "$REMOTE" ]]; then
  echo "✗ 尚未配置 origin。" >&2
  echo "  先执行： git remote add origin https://github.com/<用户名>/<仓库名>.git" >&2
  echo "  详见 docs/GitHub_提交与Release发布流程.md §0.4" >&2
  exit 2
fi
echo "origin = $REMOTE"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

echo "==> 4/4 推送"
if [[ $DRY -eq 1 ]]; then
  echo "[dry-run] 将执行: git push origin $BRANCH"
else
  git push -u origin "$BRANCH"
fi

echo "==> 完成：v$VERSION · $BRANCH"
git log --oneline -3
