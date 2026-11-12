# 一键打包 · Windows（PowerShell）
# 用法：在项目根目录执行  powershell -File scripts\build_windows.ps1
$ErrorActionPreference = "Stop"

Write-Host "==> 1/5 创建虚拟环境 .venv-build"
python -m venv .venv-build
& ".venv-build\Scripts\python.exe" -m pip install --upgrade pip
& ".venv-build\Scripts\python.exe" -m pip install -r requirements.txt
& ".venv-build\Scripts\python.exe" -m pip install -r requirements-optional.txt
& ".venv-build\Scripts\python.exe" -m pip install pyinstaller pillow

Write-Host "==> 2/5 生成应用图标"
& ".venv-build\Scripts\python.exe" scripts\make_icon.py

Write-Host "==> 3/5 PyInstaller 打包（单文件）"
& ".venv-build\Scripts\python.exe" -m PyInstaller starrystar.spec --noconfirm --clean

Write-Host "==> 4/5 整理产物"
New-Item -ItemType Directory -Force -Path dist\星语Starry-Windows | Out-Null
Copy-Item dist\星语Starry.exe dist\星语Starry-Windows\星语Starry.exe
Copy-Item README.md dist\星语Starry-Windows\
Copy-Item requirements-optional.txt dist\星语Starry-Windows\

Write-Host "==> 5/5 完成：dist\星语Starry-Windows\星语Starry.exe"
Write-Host "    双击即可运行（首次启动约 10-30 秒解压，属正常现象）"
