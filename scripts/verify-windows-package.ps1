[CmdletBinding()]
param(
    [string]$PackageRoot = "dist\windows",
    [switch]$RequireSignature,
    [switch]$RequireNativeSignature,
    [switch]$SkipSelfTest
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packagePath = if ([IO.Path]::IsPathRooted($PackageRoot)) {
    [IO.Path]::GetFullPath($PackageRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $repositoryRoot $PackageRoot))
}

if (-not (Test-Path -LiteralPath $packagePath -PathType Container)) {
    throw "Windows package root가 없습니다: $packagePath"
}

$requiredFiles = @(
    (Join-Path $packagePath "AIA\AIA.exe"),
    (Join-Path $packagePath "aia-cli\aia-cli.exe"),
    (Join-Path $packagePath "installer\AIA-SHA256SUMS.txt")
)
foreach ($required in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "필수 Windows package 파일이 없습니다: $required"
    }
}

$manifestPath = Join-Path $packagePath "installer\AIA-SHA256SUMS.txt"
$manifestEntries = @{}
foreach ($line in Get-Content -LiteralPath $manifestPath) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    if ($line -notmatch '^(?<hash>[0-9a-fA-F]{64})\s{2}(?<relative>.+)$') {
        throw "SHA-256 manifest 형식이 잘못되었습니다: $line"
    }
    $relative = $Matches.relative.Replace("/", "\")
    if ($relative -notlike "dist\windows\*") {
        throw "SHA-256 manifest가 Windows package 밖의 경로를 가리킵니다: $relative"
    }
    $packageRelative = $relative.Substring("dist\windows\".Length)
    if ([string]::IsNullOrWhiteSpace($packageRelative) -or $packageRelative.Contains("..")) {
        throw "SHA-256 manifest 경로가 안전하지 않습니다: $relative"
    }
    if ($manifestEntries.ContainsKey($packageRelative)) {
        throw "SHA-256 manifest에 중복 경로가 있습니다: $packageRelative"
    }
    $manifestEntries[$packageRelative] = $Matches.hash.ToLowerInvariant()
}

$expectedFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $packagePath "AIA") -Recurse -File
    Get-ChildItem -LiteralPath (Join-Path $packagePath "aia-cli") -Recurse -File
    Get-ChildItem -LiteralPath (Join-Path $packagePath "installer") -Recurse -File |
        Where-Object { $_.FullName -ne $manifestPath }
) | ForEach-Object {
    $_.FullName.Substring($packagePath.Length).TrimStart("\", "/")
}

$expectedSet = @($expectedFiles | Sort-Object)
$manifestSet = @($manifestEntries.Keys | Sort-Object)
if ((ConvertTo-Json $expectedSet -Compress) -ne (ConvertTo-Json $manifestSet -Compress)) {
    $missing = @($expectedSet | Where-Object { $_ -notin $manifestSet })
    $extra = @($manifestSet | Where-Object { $_ -notin $expectedSet })
    throw "SHA-256 manifest 범위가 package 파일과 다릅니다. missing=$($missing -join ', '); extra=$($extra -join ', ')"
}

foreach ($relative in $expectedSet) {
    $filePath = Join-Path $packagePath $relative
    $actual = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $manifestEntries[$relative]) {
        throw "SHA-256 mismatch: $relative"
    }
}

$entrypointTargets = @(
    (Join-Path $packagePath "AIA\AIA.exe"),
    (Join-Path $packagePath "aia-cli\aia-cli.exe"),
    (Get-ChildItem -LiteralPath (Join-Path $packagePath "installer") -Filter "AIA-*-Setup.exe" -File)
) | Where-Object { $_ } | ForEach-Object {
    if ($_ -is [System.IO.FileInfo]) { $_.FullName } else { $_ }
}
if ($entrypointTargets.Count -lt 3) {
    throw "AIA installer 실행 파일을 찾지 못했습니다."
}

$signatureTargets = @($entrypointTargets)
if ($RequireNativeSignature) {
    $signatureTargets += Get-ChildItem -LiteralPath (Join-Path $packagePath "AIA") -Recurse -File |
        Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".dll", ".pyd") } |
        ForEach-Object { $_.FullName }
    $signatureTargets += Get-ChildItem -LiteralPath (Join-Path $packagePath "aia-cli") -Recurse -File |
        Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".dll", ".pyd") } |
        ForEach-Object { $_.FullName }
}
$signatureTargets = @($signatureTargets | Sort-Object -Unique)

$signatureSummary = foreach ($target in $signatureTargets) {
    $signature = Get-AuthenticodeSignature -LiteralPath $target
    [pscustomobject]@{
        Path = $target
        Status = [string]$signature.Status
        Subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { "" }
    }
}
if ($RequireSignature -or $RequireNativeSignature) {
    $invalid = @($signatureSummary | Where-Object { $_.Status -ne "Valid" })
    if ($invalid.Count -gt 0) {
        throw "공개 릴리스에는 유효한 Authenticode 서명이 필요합니다: $($invalid.Path -join ', ')"
    }
}

if (-not $SkipSelfTest) {
    $cliPath = Join-Path $packagePath "aia-cli\aia-cli.exe"
    & $cliPath self-test --json
    if ($LASTEXITCODE -ne 0) {
        throw "aia-cli packaged self-test failed with exit code $LASTEXITCODE"
    }
}

Write-Host "[AIA] Windows package verification: PASS"
Write-Host "[AIA] Package: $packagePath"
Write-Host "[AIA] Manifest entries: $($expectedSet.Count)"
Write-Host "[AIA] Signatures: $((($signatureSummary | Where-Object { $_.Status -eq 'Valid' }).Count))/$($signatureSummary.Count) valid"
