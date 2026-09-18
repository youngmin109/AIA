[CmdletBinding()]
param(
    [string]$OutputRoot = "dist\windows",
    [string[]]$AdditionalFile = @(),
    [string]$CertificatePath,
    [string]$CertificateThumbprint,
    [string]$TimestampUrl = "https://timestamp.digicert.com",
    [switch]$RequireSignature,
    [switch]$SignRuntimeBinaries
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputPath = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    [IO.Path]::GetFullPath($OutputRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputRoot))
}

if ($CertificatePath -and $CertificateThumbprint) {
    throw "CertificatePath와 CertificateThumbprint를 동시에 지정할 수 없습니다."
}

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $sdkRoots = @(
        (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"),
        (Join-Path ${env:ProgramFiles} "Windows Kits\10\bin")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $candidate = $sdkRoots |
        ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter signtool.exe -Recurse -File -ErrorAction SilentlyContinue } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }
    return $null
}

function Resolve-SigningTargets {
    param([string]$Root, [switch]$IncludeRuntime)

    $targets = @(
        (Join-Path $Root "AIA\AIA.exe"),
        (Join-Path $Root "aia-cli\aia-cli.exe")
    )
    if ($IncludeRuntime) {
        $targets += Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction Stop |
            Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".dll", ".pyd") } |
            ForEach-Object { $_.FullName }
    }
    return @($targets + $AdditionalFile) |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        ForEach-Object { [IO.Path]::GetFullPath($_) } |
        Sort-Object -Unique
}

if (-not (Test-Path -LiteralPath $outputPath -PathType Container)) {
    throw "Windows 산출물 폴더가 없습니다: $outputPath"
}

$targets = Resolve-SigningTargets -Root $outputPath -IncludeRuntime:$SignRuntimeBinaries
$missing = @(
    (Join-Path $outputPath "AIA\AIA.exe"),
    (Join-Path $outputPath "aia-cli\aia-cli.exe")
) | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }
if ($missing.Count -gt 0) {
    throw "필수 Windows 실행 파일이 없습니다: $($missing -join ', ')"
}

$hasSigner = $CertificatePath -or $CertificateThumbprint
if (-not $hasSigner) {
    if ($RequireSignature) {
        throw "릴리스 서명에 CertificatePath 또는 CertificateThumbprint가 필요합니다."
    }
    Write-Warning "서명 인증서가 지정되지 않아 unsigned 개발 산출물을 유지합니다. 릴리스에는 -RequireSignature를 사용하세요."
    $targets | ForEach-Object { Write-Host "[AIA] Unsigned target: $_" }
    exit 0
}

$signTool = Find-SignTool
if (-not $signTool) {
    throw "signtool.exe를 찾지 못했습니다. Windows SDK를 설치하거나 signtool.exe를 PATH에 추가하세요."
}

$signArguments = @("sign", "/fd", "SHA256", "/tr", $TimestampUrl, "/td", "SHA256")
if ($CertificatePath) {
    if (-not (Test-Path -LiteralPath $CertificatePath -PathType Leaf)) {
        throw "코드 서명 인증서 파일이 없습니다: $CertificatePath"
    }
    if ([IO.Path]::GetExtension($CertificatePath).ToLowerInvariant() -eq ".pfx" -and -not $env:AIA_SIGNING_CERT_PASSWORD) {
        throw "PFX 인증서에는 AIA_SIGNING_CERT_PASSWORD 환경 변수가 필요합니다."
    }
    $signArguments += @("/f", [IO.Path]::GetFullPath($CertificatePath))
    $signArguments += @("/p", $env:AIA_SIGNING_CERT_PASSWORD)
}
else {
    $signArguments += @("/sha1", ($CertificateThumbprint -replace "\s", ""), "/s", "My")
}

foreach ($target in $targets) {
    if ($SignRuntimeBinaries -and (Get-AuthenticodeSignature -LiteralPath $target).Status -eq "Valid") {
        Write-Host "[AIA] Already signed: $target"
        continue
    }
    Write-Host "[AIA] Signing: $target"
    & $signTool @signArguments $target
    if ($LASTEXITCODE -ne 0) {
        throw "코드 서명 실패: $target (exit $LASTEXITCODE)"
    }
    & $signTool verify /pa /all $target
    if ($LASTEXITCODE -ne 0) {
        throw "코드 서명 검증 실패: $target (exit $LASTEXITCODE)"
    }
}

Write-Host "[AIA] Windows code-signing verification completed for $($targets.Count) file(s)."
