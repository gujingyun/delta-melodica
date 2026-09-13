$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$audioPython = Join-Path $PSScriptRoot 'work\transcription-runtime\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $audioPython)) {
    uv venv --python 3.10 work\transcription-runtime
    if ($LASTEXITCODE -ne 0) { throw '创建独立扒谱环境失败。' }
}
uv pip install --python $audioPython -r requirements-audio.txt 'pyinstaller==6.11.1' --index-strategy unsafe-best-match
if ($LASTEXITCODE -ne 0) { throw '安装扒谱依赖失败。' }
& $audioPython prepare_audio_engine.py --models work\audio-models
if ($LASTEXITCODE -ne 0) { throw '下载或校验模型失败。' }
& .\.venv\Scripts\python.exe -m unittest test_audio_transcription test_audio_transcription_ui test_music
if ($LASTEXITCODE -ne 0) { throw '扒谱回归测试失败。' }
& $audioPython -m PyInstaller --noconfirm --onedir --console --name audio_worker --distpath work\audio-engine-build --workpath work\audio-engine-pyi --specpath work --collect-all basic_pitch --collect-all librosa --collect-data demucs --collect-data resampy --collect-data lazy_loader --copy-metadata basic-pitch --copy-metadata demucs --hidden-import demucs.htdemucs --hidden-import backports.tarfile --exclude-module tkinter --exclude-module matplotlib --exclude-module tensorboard audio_worker.py
if ($LASTEXITCODE -ne 0) { throw '扒谱引擎打包失败。' }
$audioDestination = Join-Path $PSScriptRoot 'dist\audio-engine'
New-Item -ItemType Directory -Force -Path $audioDestination | Out-Null
Copy-Item -Path 'work\audio-engine-build\audio_worker\*' -Destination $audioDestination -Recurse -Force
$modelDestination = Join-Path $audioDestination 'models'
New-Item -ItemType Directory -Force -Path $modelDestination | Out-Null
Copy-Item -Path 'work\audio-models\*' -Destination $modelDestination -Force
& $audioPython prepare_audio_engine.py --licenses (Join-Path $audioDestination 'licenses')
if ($LASTEXITCODE -ne 0) { throw '导出依赖许可证失败。' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --uac-admin --name '三角洲口风琴_音频扒谱版' --hidden-import mido --hidden-import pystray._win32 app.py
if ($LASTEXITCODE -ne 0) { throw '主程序打包失败。' }
Push-Location -LiteralPath 'dist'
try {
    & ..\.venv\Scripts\python.exe -m zipfile -c '三角洲口风琴_音频扒谱完整包.zip' '三角洲口风琴_音频扒谱版.exe' audio-engine
    if ($LASTEXITCODE -ne 0) { throw '生成完整压缩包失败。' }
} finally {
    Pop-Location
}
Write-Output '构建完成：dist\三角洲口风琴_音频扒谱版.exe。分发时须附带相邻 audio-engine 文件夹。'
