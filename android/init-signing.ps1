param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$SigningDirectory = (Join-Path $env:LOCALAPPDATA 'DeltaMelodicaSigning\android')
)
$ErrorActionPreference = 'Stop'
$taskKeytool = Join-Path $JavaHome 'bin\keytool.exe'
if (-not (Test-Path -LiteralPath $taskKeytool)) { throw '请通过 -JavaHome 指定 JDK 21。' }
$taskKey = Join-Path $SigningDirectory 'release.jks'
$taskSecret = Join-Path $SigningDirectory 'password.clixml'
if ((Test-Path -LiteralPath $taskKey) -or (Test-Path -LiteralPath $taskSecret)) {
    throw '签名资料已存在，禁止覆盖。后续构建请复用原签名，勿重新生成。'
}
New-Item -ItemType Directory -Path $SigningDirectory -Force | Out-Null
# 仅当前用户和 SYSTEM 可读取密钥；密码使用当前 Windows 用户的 DPAPI 保护。
$taskSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $SigningDirectory /inheritance:r /grant:r "*${taskSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw '无法限制签名目录权限，已停止。' }
$taskOldPassword = $env:MELODICA_STORE_PASSWORD
try {
    $taskRandom = New-Object byte[] 32
    $taskRng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $taskRng.GetBytes($taskRandom) } finally { $taskRng.Dispose() }
    $env:MELODICA_STORE_PASSWORD = [Convert]::ToBase64String($taskRandom)
    ConvertTo-SecureString $env:MELODICA_STORE_PASSWORD -AsPlainText -Force | Export-Clixml -LiteralPath $taskSecret
    & $taskKeytool -genkeypair -keystore $taskKey -storetype JKS -alias delta-melodica -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=Delta Melodica, OU=Android' -storepass:env MELODICA_STORE_PASSWORD -keypass:env MELODICA_STORE_PASSWORD -noprompt
    if ($LASTEXITCODE -ne 0) { throw '签名密钥生成失败，请检查本机目录；不会自动重建或覆盖。' }
    Write-Output "签名资料已建立：$SigningDirectory"
    Write-Output '密码仅由当前 Windows 用户解密。正式上线前请在可信环境中制作独立加密备份；勿上传 Git、官网或公开网盘。'
} finally {
    $env:MELODICA_STORE_PASSWORD = $taskOldPassword
    $taskRandom = $null
}
