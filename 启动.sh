#!/usr/bin/env bash
# AI 桌面助手启动脚本（macOS / Linux）
cd "$(dirname "$0")"

PY=python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "首次运行，正在创建虚拟环境并安装依赖..."
    $PY -m venv .venv || exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt -q || exit 1

exec python main.py
