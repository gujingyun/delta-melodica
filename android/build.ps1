param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$SdkRoot = $env:ANDROID_HOME,
    [ValidateSet('Debug', 'Release')][string]$Configuration = 'Debug',
    [string]$SigningDirectory = (Join-Path $env:LOCALAPPDATA 'DeltaMelodicaSigning\android'),
    [switch]$WithDeviceTests
)
$ErrorActionPreference = 'Stop'
if (-not $JavaHome -or -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin\java.exe'))) {
    throw '请将 JAVA_HOME 设置为 JDK 17 或更高版本，或传入 -JavaHome。可使用 Android Studio 自带的 jbr 目录。'
}
if (-not $SdkRoot -or -not (Test-Path -LiteralPath (Join-Path $SdkRoot 'platforms\android-34\android.jar'))) {
    throw '请将 ANDROID_HOME 设置为包含 Platform 34 的 SDK，或传入 -SdkRoot。'
}
$taskTools = Join-Path $SdkRoot 'build-tools\36.0.0'
foreach ($taskTool in @('apksigner.bat', 'aapt.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $taskTools $taskTool))) { throw '缺少 Build Tools 36.0.0。' }
}
$taskOldEnvironment = @{}
foreach ($taskName in @('JAVA_HOME', 'ANDROID_HOME', 'MELODICA_KEYSTORE', 'MELODICA_STORE_PASSWORD')) {
    $taskOldEnvironment[$taskName] = [Environment]::GetEnvironmentVariable($taskName, 'Process')
}
try {
    $env:JAVA_HOME = $JavaHome
    $env:ANDROID_HOME = $SdkRoot
    if ($Configuration -eq 'Release') {
        $taskKey = Join-Path $SigningDirectory 'release.jks'
        $taskSecret = Join-Path $SigningDirectory 'password.clixml'
        if (-not (Test-Path -LiteralPath $taskKey) -or -not (Test-Path -LiteralPath $taskSecret)) {
            throw '缺少正式签名资料。首次运行 init-signing.ps1；已有版本必须复用原密钥。'
        }
        $taskSecure = Import-Clixml -LiteralPath $taskSecret
        $taskCredential = [System.Net.NetworkCredential]::new('', $taskSecure)
        $env:MELODICA_KEYSTORE = (Resolve-Path -LiteralPath $taskKey).Path
        $env:MELODICA_STORE_PASSWORD = $taskCredential.Password
    }
    Push-Location -LiteralPath $PSScriptRoot
    try {
        $taskVariant = $Configuration.ToLowerInvariant()
        # 当前 AGP 仅提供 Debug 单元测试任务；Release 复用同一套源码测试，再执行 Release Lint 和 APK 构建。
        $taskArguments = @('clean', 'testDebugUnitTest', "lint${Configuration}", "assemble${Configuration}")
        if ($WithDeviceTests) { $taskArguments += @("-PtestBuildType=$taskVariant", "assemble${Configuration}AndroidTest") }
        & .\gradlew.bat @taskArguments --no-daemon --console plain
        if ($LASTEXITCODE -ne 0) { throw '安卓测试或构建失败，停止交付。' }
        $taskSource = Join-Path $PSScriptRoot "app\build\outputs\apk\$taskVariant\app-$taskVariant.apk"
        $taskMetadata = Get-Content -LiteralPath (Join-Path (Split-Path $taskSource) 'output-metadata.json') -Raw | ConvertFrom-Json
        $taskVersion = $taskMetadata.elements[0].versionName
        # 中文目录下使用当前目录和 ASCII 文件名调用 Android 工具。
        Push-Location -LiteralPath (Split-Path $taskSource)
        try {
            $taskSignature = & (Join-Path $taskTools 'apksigner.bat') verify --verbose --print-certs "app-$taskVariant.apk"
            if ($LASTEXITCODE -ne 0) { throw 'APK 签名验证失败。' }
            $taskBadging = & (Join-Path $taskTools 'aapt.exe') dump badging "app-$taskVariant.apk"
            if ($LASTEXITCODE -ne 0) { throw '无法检查 APK 清单。' }
        } finally { Pop-Location }
        if ($Configuration -eq 'Release' -and (($taskBadging -match 'application-debuggable') -or ($taskSignature -match 'CN=Android Debug'))) {
            throw '正式包含调试标记或调试证书，停止交付。'
        }
        $taskFingerprintLine = $taskSignature | Where-Object { $_ -match '^Signer #1 certificate SHA-256 digest:' } | Select-Object -First 1
        if (-not $taskFingerprintLine) { throw '未获得签名证书 SHA-256，停止交付。' }
        $taskOutput = Join-Path (Split-Path $PSScriptRoot -Parent) 'dist'
        New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
        $taskBase = "delta-melodica-android-v$taskVersion"
        $taskApk = Join-Path $taskOutput "$taskBase.apk"
        Copy-Item -LiteralPath $taskSource -Destination $taskApk
        $taskHash = (Get-FileHash -LiteralPath $taskApk -Algorithm SHA256).Hash.ToLowerInvariant()
        $taskCommit = & git rev-parse HEAD
        if ($LASTEXITCODE -ne 0) { throw '无法记录源代码提交。' }
        $taskDirty = [bool](& git status --porcelain -- .)
        [ordered]@{
            platform = 'android'; version = $taskVersion; versionCode = $taskMetadata.elements[0].versionCode
            applicationId = $taskMetadata.applicationId; minSdk = 26; targetSdk = 34; configuration = $Configuration
            file = "$taskBase.apk"; size = (Get-Item -LiteralPath $taskApk).Length; sha256 = $taskHash
            certificateSha256 = ($taskFingerprintLine -split ': ', 2)[1].Trim()
            sourceCommit = $taskCommit; sourceDirty = $taskDirty; builtAt = [DateTime]::UtcNow.ToString('o')
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskOutput "$taskBase.json") -Encoding utf8
        "$taskHash  $taskBase.apk" | Set-Content -LiteralPath (Join-Path $taskOutput "$taskBase.sha256") -Encoding ascii
        Write-Output "已生成并校验：$taskApk"
        Write-Output "SHA-256：$taskHash"
        Write-Output $taskFingerprintLine
    } finally { Pop-Location }
} finally {
    foreach ($taskName in $taskOldEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($taskName, $taskOldEnvironment[$taskName], 'Process')
    }
    $taskCredential = $null; $taskSecure = $null
}
