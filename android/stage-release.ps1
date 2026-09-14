param([string]$Version = '0.6.0')
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw '版本号需为三段数字。' }
$taskRepo = Split-Path $PSScriptRoot -Parent
$taskBase = "delta-melodica-android-v$Version"
$taskApk = Join-Path $taskRepo "dist\$taskBase.apk"
$taskMetadata = Get-Content -LiteralPath (Join-Path $taskRepo "dist\$taskBase.json") -Raw | ConvertFrom-Json
if ($taskMetadata.configuration -ne 'Release' -or $taskMetadata.version -ne $Version -or $taskMetadata.sourceDirty) {
    throw '需要由干净源码构建的对应 Release 包。'
}
if ((Get-FileHash -LiteralPath $taskApk -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskMetadata.sha256) { throw 'APK 与构建记录不一致。' }
$taskSite = Join-Path $taskRepo "releases\android-v$Version\site"
New-Item -ItemType Directory -Path (Join-Path $taskSite 'downloads'), (Join-Path $taskSite 'assets') -Force | Out-Null
$taskPolicy = [xml](Get-Content -LiteralPath (Join-Path $PSScriptRoot 'app\src\main\res\values\data_information.xml') -Raw)
$taskPolicyText = $taskPolicy.resources.string.InnerText.Replace('\n', "`n")
$taskValues = @{
    '@@VERSION@@' = $Version; '@@APK@@' = "$taskBase.apk"; '@@SHA256@@' = $taskMetadata.sha256
    '@@CERT@@' = $taskMetadata.certificateSha256; '@@SIZE@@' = ('{0:N1} KB' -f ($taskMetadata.size / 1024))
    '@@POLICY@@' = [System.Net.WebUtility]::HtmlEncode($taskPolicyText)
}
foreach ($taskFile in @('android.html', 'android-data.html', 'android.css')) {
    $taskText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "release-site\$taskFile") -Raw
    foreach ($taskToken in $taskValues.Keys) { $taskText = $taskText.Replace($taskToken, $taskValues[$taskToken]) }
    if ($taskText -match '@@[A-Z]+@@') { throw "网页仍有未替换字段：$taskFile" }
    Set-Content -LiteralPath (Join-Path $taskSite $taskFile) -Value $taskText -Encoding utf8
}
Copy-Item -LiteralPath $taskApk -Destination (Join-Path $taskSite "downloads\$taskBase.apk")
Copy-Item -LiteralPath (Join-Path $taskRepo "dist\$taskBase.sha256") -Destination (Join-Path $taskSite "downloads\$taskBase.apk.sha256")
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'docs\release-main-v0.6.0.png') -Destination (Join-Path $taskSite 'assets\android-main-v0.6.0.png')
# 教程媒体与播放器一同暂存，避免后续发行页面出现缺失资源。
foreach ($taskAsset in @('assets/android-install-20260914.jpg', 'video-player.js', 'vendor/hls.light-1.7.2.min.js', 'vendor/hls-LICENSE.txt', 'vendor/Apache-2.0.txt', 'videos/android-install-20260914.mp4', 'videos/android-install-20260914/index.m3u8')) {
    $taskTarget = Join-Path $taskSite $taskAsset
    New-Item -ItemType Directory -Path (Split-Path $taskTarget -Parent) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $taskRepo "website/$taskAsset") -Destination $taskTarget
}
Get-ChildItem -LiteralPath (Join-Path $taskRepo 'website/videos/android-install-20260914') -Filter 'segment-*.ts' | Copy-Item -Destination (Join-Path $taskSite 'videos/android-install-20260914')
[ordered]@{
    platform = 'android'; version = $Version; versionCode = $taskMetadata.versionCode
    minSdk = $taskMetadata.minSdk; file = "downloads/$taskBase.apk"; size = $taskMetadata.size
    sha256 = $taskMetadata.sha256; certificateSha256 = $taskMetadata.certificateSha256
    notes = @('支持官网 MIDI 和 JSON 曲谱', '正式签名及安装包校验', '离线权限与数据说明')
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskSite 'android-version.json') -Encoding utf8
Write-Output "官网文件已暂存，尚未上传：$taskSite"
