#!/usr/bin/env bash
# 星语 Starry · 一键 GitHub Release 发布（v13.6.5）
#
# 用法：
#   bash scripts/github_release.sh              # 用 core/config.py 的版本，仅本地准备+建 Release
#   bash scripts/github_release.sh 13.6.5       # 指定版本（必须与 APP_VERSION 一致）
#   bash scripts/github_release.sh --tag        # 额外创建并推送 vX.Y.Z tag（触发 CI 自动发布）
#   bash scripts/github_release.sh --dry-run    # 只打印将执行的命令
#
# 流程：版本一致性 → 三端门禁 → 打包 EXE → 校验 SHA-256 → 快照校验
#       → (可选) 打 tag → gh release create 上传资产。
# 前置：已安装 gh 并 gh auth login；或改走 docs 里的网页版流程。
set -euo pipefail

cd "$(dirname "$0")/.."

PY=python
command -v python >/dev/null 2>&1 || PY=python3
VERSION="${1:-}"
TAG=0
DRY=0
for arg in "$@"; do
  [[ "$arg" == "--tag" ]] && TAG=1
  [[ "$arg" == "--dry-run" ]] && DRY=1
done
[[ "$VERSION" == --* ]] && VERSION=""

SRC_VERSION=$("$PY" -c "import re;print(re.search(r'APP_VERSION\s*=\s*[\"\']([^\"\']+)',open('core/config.py',encoding='utf-8').read()).group(1))")
if [[ -z "$VERSION" ]]; then VERSION="$SRC_VERSION"; fi
if [[ "$VERSION" != "$SRC_VERSION" ]]; then
  echo "✗ 指定版本 $VERSION 与 core/config.py 的 $SRC_VERSION 不一致" >&2
  exit 1
fi
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "✗ 版本号不符合 SemVer：v$VERSION" >&2
  exit 1
fi

EXE="星语Starry-GUI-v${VERSION}.exe"
SUM="${EXE}.sha256"
echo "==> 发布版本 v$VERSION，产物 $EXE"

echo "==> 1/6 版本与三端同源门禁"
"$PY" scripts/check_core_parity.py --expect-version "$VERSION"

echo "==> 2/6 打包 GUI EXE"
if [[ $DRY -eq 0 ]]; then
  "$PY" scripts/build_root_exe.py
else
  echo "[dry-run] python scripts/build_root_exe.py"
fi

echo "==> 3/6 校验产物与 SHA-256"
if [[ $DRY -eq 0 ]]; then
  test -f "$EXE" || { echo "✗ 缺少 $EXE" >&2; exit 1; }
  test -f "$SUM" || { echo "✗ 缺少 $SUM" >&2; exit 1; }
  ACTUAL=$(sha256sum "$EXE" | cut -d' ' -f1)
  EXPECT=$(cut -d' ' -f1 < "$SUM")
  [[ "$ACTUAL" == "$EXPECT" ]] || { echo "✗ 校验和不匹配" >&2; exit 1; }
  echo "    SHA-256 OK: $ACTUAL"
fi

echo "==> 4/6 发布快照终验（若已生成快照）"
if [[ -d "releases/星语Starry-v${VERSION}" ]]; then
  "$PY" scripts/verify_release.py --version "$VERSION" --skip-history || true
else
  echo "    未找到本地快照，跳过（CI 的 snapshot job 会生成）"
fi

echo "==> 5/6 打 tag（可选）"
if [[ $TAG -eq 1 ]]; then
  if [[ $DRY -eq 1 ]]; then
    echo "[dry-run] git tag -a v$VERSION && git push origin v$VERSION"
  else
    git tag -a "v$VERSION" -m "v$VERSION"
    git push origin "v$VERSION"
    echo "    tag 已推送，CI 将自动创建 Release（gh run watch 查看）"
  fi
else
  echo "    未指定 --tag，跳过（CI 自动发布请加 --tag）"
fi

echo "==> 6/6 创建 GitHub Release 并上传资产"
if ! command -v gh >/dev/null 2>&1; then
  echo "⚠ 未安装 gh CLI，跳过自动创建。" >&2
  echo "  请按 docs/GitHub_提交与Release发布流程.md §3.3 用网页发布，" >&2
  echo "  或安装 gh 后重跑本脚本。" >&2
  exit 0
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "⚠ gh 未登录，请先执行 gh auth login" >&2
  exit 0
fi

ASSETS=("$EXE" "$SUM")
shopt -s nullglob
for z in releases/*.zip releases/SHA256SUMS-*.txt; do ASSETS+=("$z"); done
shopt -u nullglob

if [[ $DRY -eq 1 ]]; then
  echo "[dry-run] gh release create v$VERSION --notes-file RELEASE_NOTES.md ${ASSETS[*]}"
else
  gh release create "v$VERSION" \
    --title "星语 Starry v$VERSION" \
    --notes-file RELEASE_NOTES.md \
    "${ASSETS[@]}"
  gh release view "v$VERSION" --json tagName,assets,url
fi

echo "==> 完成 v$VERSION"
