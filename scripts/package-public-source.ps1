[CmdletBinding()]
param(
    [string]$OutputRoot = "dist\public-source-release",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$output = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputRoot))
}

$versionText = (& uv run aia --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^AIA (\d+\.\d+\.\d+)$') {
    throw "Could not determine the AIA version."
}
$version = $Matches[1]

if (Test-Path -LiteralPath $output) {
    if (-not $Force) {
        throw "Output path already exists. Use -Force to replace it: $output"
    }
    Remove-Item -LiteralPath $output -Recurse -Force
}
New-Item -ItemType Directory -Path $output -Force | Out-Null

$sourceRoot = Join-Path $output "source"
$archiveName = "aia-$version-source.zip"
$archivePath = Join-Path $output $archiveName

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "export-public-tree.ps1") `
    -OutputPath $sourceRoot -Force
if ($LASTEXITCODE -ne 0) {
    throw "Public source export failed."
}

Compress-Archive -Path (Join-Path $sourceRoot "*") -DestinationPath $archivePath -CompressionLevel Optimal -Force
$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $archiveName" | Set-Content -LiteralPath (Join-Path $output "SHA256SUMS.txt") -Encoding ascii

Write-Host "Public source package: $archivePath"
Write-Host "SHA-256: $hash"
