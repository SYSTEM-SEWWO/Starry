@echo off
rem AI 桌面助手启动脚本（Windows）
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python，请先安装 Python 3.9+ （https://www.python.org/downloads/）
    pause
    exit /b 1
)

if not exist ".venv" (
    echo 首次运行，正在创建虚拟环境并安装依赖...
    python -m venv .venv || pause && exit /b 1
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q || pause && exit /b 1

python main.py
if errorlevel 1 pause
