[CmdletBinding()]
param(
    [string]$OutputRoot = "dist\windows",
    [switch]$Clean,
    [string]$CertificatePath,
    [string]$CertificateThumbprint,
    [string]$TimestampUrl = "https://timestamp.digicert.com",
    [switch]$RequireSignature,
    [switch]$SignRuntimeBinaries
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pyprojectPath = Join-Path $repositoryRoot "pyproject.toml"
if (-not (Test-Path -LiteralPath $pyprojectPath -PathType Leaf)) {
    throw "pyproject.toml을 찾지 못했습니다: $pyprojectPath"
}
$pyproject = Get-Content -LiteralPath $pyprojectPath -Raw
$versionMatch = [regex]::Match($pyproject, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "pyproject.toml에서 프로젝트 버전을 읽지 못했습니다."
}
$version = $versionMatch.Groups[1].Value
$hasSigner = $CertificatePath -or $CertificateThumbprint
if ($RequireSignature -and -not $hasSigner) {
    throw "릴리스 서명을 요구했지만 CertificatePath 또는 CertificateThumbprint가 없습니다."
}
if ($CertificatePath) {
    if (-not (Test-Path -LiteralPath $CertificatePath -PathType Leaf)) {
        throw "코드 서명 인증서 파일이 없습니다: $CertificatePath"
    }
    if ([IO.Path]::GetExtension($CertificatePath).ToLowerInvariant() -eq ".pfx" -and
        [string]::IsNullOrWhiteSpace($env:AIA_SIGNING_CERT_PASSWORD)) {
        throw "PFX 인증서에는 AIA_SIGNING_CERT_PASSWORD 환경 변수가 필요합니다."
    }
}
$defaultOutputPath = [IO.Path]::GetFullPath((Join-Path $repositoryRoot "dist\windows"))
$requestedOutputPath = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    [IO.Path]::GetFullPath($OutputRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputRoot))
}
if ($requestedOutputPath -ne $defaultOutputPath) {
    throw "Windows installer는 현재 dist\windows 산출물만 패키징합니다. OutputRoot를 기본값으로 사용하세요."
}

& (Join-Path $repositoryRoot "scripts\build-windows.ps1") -OutputRoot $OutputRoot -Clean:$Clean
if ($LASTEXITCODE -ne 0) {
    throw "Windows executable build failed"
}

$signScript = Join-Path $repositoryRoot "scripts\sign-windows.ps1"
$signParameters = @{
    OutputRoot = $OutputRoot
    TimestampUrl = $TimestampUrl
    RequireSignature = [bool]$RequireSignature
    SignRuntimeBinaries = [bool]$SignRuntimeBinaries
}
if ($CertificatePath) { $signParameters.CertificatePath = $CertificatePath }
if ($CertificateThumbprint) { $signParameters.CertificateThumbprint = $CertificateThumbprint }
& $signScript @signParameters
if ($LASTEXITCODE -ne 0) {
    throw "Windows executable signing failed"
}

function Find-InnoCompiler {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles} "Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:LOCALAPPDATA} "Programs\Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -First 1
}

$isccPath = Find-InnoCompiler
if ($null -eq $isccPath) {
    throw "Inno Setup Compiler (ISCC.exe) is required to create the installer."
}

Write-Host "[AIA] Inno Setup version: $version"
Write-Host "[AIA] Inno Setup compiler: $isccPath"
$innoArguments = @("/DMyAppVersion=$version")
$innoSignScript = Join-Path $repositoryRoot "scripts\inno-sign.ps1"
$previousInnoCertificatePath = $env:AIA_INNO_CERTIFICATE_PATH
$previousInnoCertificateThumbprint = $env:AIA_INNO_CERTIFICATE_THUMBPRINT
$previousInnoTimestampUrl = $env:AIA_INNO_TIMESTAMP_URL
try {
    if ($hasSigner) {
        if (-not (Test-Path -LiteralPath $innoSignScript -PathType Leaf)) {
            throw "Inno Setup 서명 도우미를 찾지 못했습니다: $innoSignScript"
        }
        $powerShellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
        $innoQuote = '$q'
        $innoFile = '$f'
        $signToolCommand = "$innoQuote$powerShellPath$innoQuote -NoProfile -ExecutionPolicy Bypass -File $innoQuote$innoSignScript$innoQuote $innoFile"
        $innoArguments += @("/DAIA_SIGNTOOL", "/SAIA=$signToolCommand")
        $env:AIA_INNO_CERTIFICATE_PATH = if ($CertificatePath) { [IO.Path]::GetFullPath($CertificatePath) } else { "" }
        $env:AIA_INNO_CERTIFICATE_THUMBPRINT = if ($CertificateThumbprint) { $CertificateThumbprint } else { "" }
        $env:AIA_INNO_TIMESTAMP_URL = $TimestampUrl
        Write-Host "[AIA] Inno Setup internal signing: enabled"
    }
    & $isccPath @innoArguments (Join-Path $repositoryRoot "packaging\windows\AIA.iss")
}
finally {
    $env:AIA_INNO_CERTIFICATE_PATH = $previousInnoCertificatePath
    $env:AIA_INNO_CERTIFICATE_THUMBPRINT = $previousInnoCertificateThumbprint
    $env:AIA_INNO_TIMESTAMP_URL = $previousInnoTimestampUrl
}
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup packaging failed with exit code $LASTEXITCODE"
}

$installer = Get-ChildItem -LiteralPath (Join-Path $repositoryRoot "dist\windows\installer") -Filter "AIA-*-Setup.exe" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $installer) {
    throw "Inno Setup installer 산출물을 찾지 못했습니다."
}

$installerSignParameters = @{
    OutputRoot = $OutputRoot
    AdditionalFile = @($installer.FullName)
    TimestampUrl = $TimestampUrl
    RequireSignature = [bool]$RequireSignature
}
if ($CertificatePath) { $installerSignParameters.CertificatePath = $CertificatePath }
if ($CertificateThumbprint) { $installerSignParameters.CertificateThumbprint = $CertificateThumbprint }
& $signScript @installerSignParameters
if ($LASTEXITCODE -ne 0) {
    throw "Windows installer signing failed"
}

$manifestPath = Join-Path $installer.DirectoryName "AIA-SHA256SUMS.txt"
$manifestFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $repositoryRoot "dist\windows\AIA") -Recurse -File
    Get-ChildItem -LiteralPath (Join-Path $repositoryRoot "dist\windows\aia-cli") -Recurse -File
    $installer
)
$manifestLines = $manifestFiles |
    Sort-Object FullName |
    ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $relative = $_.FullName.Substring($repositoryRoot.Length).TrimStart("\", "/").Replace("\", "/")
        "$hash  $relative"
    }
$manifestLines | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "[AIA] Windows installer packaging completed."
Write-Host "[AIA] SHA-256 manifest created: $manifestPath"
