# 一键打包 · Windows 命令行版（PowerShell）· V11.5
# 产物：dist\星语Starry-CLI\星语Starry-CLI.exe（单文件控制台程序，无窗口）
# 用法（在项目根目录执行）：
#     powershell -ExecutionPolicy Bypass -File scripts\build_windows_cli.ps1
#
# V11.5 改进：
#   1) venv 幂等（已存在则复用），重复执行不再报错
#   2) 打包后自动冒烟自检 --version / --platform，并校验退出码
#   3) 随包附带 README / 命令行使用指南 / Windows_EXE_构建指南
#   4) 中文控制台编码兜底已在源码层修复（见 starry_cli.py / core\cli.py）
$ErrorActionPreference = "Stop"

chcp 65001 | Out-Null
$env:PYTHONIOENCODING = "utf-8"

Write-Host "==> 1/5 准备虚拟环境 .venv-cli（幂等）"
if (-not (Test-Path ".venv-cli\Scripts\python.exe")) {
    python -m venv .venv-cli
}
$PY = ".venv-cli\Scripts\python.exe"
& $PY -m pip install --upgrade pip
& $PY -m pip install -r requirements.txt
& $PY -m pip install pyinstaller

Write-Host "==> 2/5 读取版本号"
$version = & $PY -c "from core.config import APP_VERSION; print(APP_VERSION)"
Write-Host "    APP_VERSION = $version"

Write-Host "==> 3/5 PyInstaller 打包（控制台模式，不收集 GUI 模块）"
& $PY -m PyInstaller starry_cli.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败，退出码 $LASTEXITCODE" }

Write-Host "==> 4/5 冒烟自检 + 整理产物"
$exe = "dist\星语Starry-CLI.exe"
if (-not (Test-Path $exe)) { throw "exe 未生成: $exe" }
& $exe --version
if ($LASTEXITCODE -ne 0) { throw "--version 自检失败，退出码 $LASTEXITCODE" }
& $exe --platform
if ($LASTEXITCODE -ne 0) { throw "--platform 自检失败，退出码 $LASTEXITCODE" }

New-Item -ItemType Directory -Force -Path "dist\星语Starry-CLI" | Out-Null
Copy-Item $exe "dist\星语Starry-CLI\"
Copy-Item "README.md" "dist\星语Starry-CLI\"
Copy-Item "命令行使用指南.md" "dist\星语Starry-CLI\" -ErrorAction SilentlyContinue
Copy-Item "docs\Windows_EXE_构建指南.md" "dist\星语Starry-CLI\" -ErrorAction SilentlyContinue

Write-Host "==> 5/5 完成：dist\星语Starry-CLI\星语Starry-CLI.exe（v$version）"
Write-Host "    在命令提示符 / PowerShell 中直接运行，例如："
Write-Host "    星语Starry-CLI.exe --version"
Write-Host "    星语Starry-CLI.exe --platform"
Write-Host "    星语Starry-CLI.exe `"你好`""
Write-Host "    EXE_SMOKE_OK"
