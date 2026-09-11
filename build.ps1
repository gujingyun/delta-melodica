$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败。' }
}
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $pythonPath -m pip install -r requirements.txt 'pyinstaller==6.11.1'
if ($LASTEXITCODE -ne 0) { throw '安装构建依赖失败。' }
& $pythonPath -m unittest -v test_music
if ($LASTEXITCODE -ne 0) { throw '自动化测试失败，停止打包。' }
& $pythonPath -m PyInstaller --noconfirm --clean --onefile --windowed --name '口风琴助手' --hidden-import mido app.py
if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
Write-Output '构建完成：dist\口风琴助手.exe'
