param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$SdkRoot = $env:ANDROID_HOME
)
$ErrorActionPreference = 'Stop'
if (-not $JavaHome -or -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin\java.exe'))) {
    throw '请将 JAVA_HOME 设置为 JDK 21，或传入 -JavaHome。可使用 Android Studio 自带的 jbr 目录。'
}
if (-not $SdkRoot -or -not (Test-Path -LiteralPath (Join-Path $SdkRoot 'platforms\android-34\android.jar'))) {
    throw '请将 ANDROID_HOME 设置为包含 Platform 34 的 SDK，或传入 -SdkRoot。'
}
$taskOldJava = $env:JAVA_HOME
$taskOldSdk = $env:ANDROID_HOME
try {
    $env:JAVA_HOME = $JavaHome
    $env:ANDROID_HOME = $SdkRoot
    Push-Location -LiteralPath $PSScriptRoot
    try {
        # 完整清理构建，避免增量打包残留旧的 classes.dex。
        & .\gradlew.bat clean testDebugUnitTest assembleDebug lintDebug --console plain
        if ($LASTEXITCODE -ne 0) { throw '安卓测试或构建失败，请检查上方输出。' }
        $taskOutput = Join-Path (Split-Path $PSScriptRoot -Parent) 'dist'
        New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
        $taskApk = Join-Path $taskOutput '三角洲口风琴_安卓_v0.5预览版.apk'
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app\build\outputs\apk\debug\app-debug.apk') -Destination $taskApk
        Write-Output "已生成：$taskApk"
        Get-FileHash -LiteralPath $taskApk -Algorithm SHA256
    } finally { Pop-Location }
} finally {
    $env:JAVA_HOME = $taskOldJava
    $env:ANDROID_HOME = $taskOldSdk
}
