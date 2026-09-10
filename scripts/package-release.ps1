[CmdletBinding()]
param(
    [string]$OutputRoot = (Join-Path $PSScriptRoot "..\dist\release"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pyprojectPath = Join-Path $repositoryRoot "pyproject.toml"
if (-not (Test-Path -LiteralPath $pyprojectPath)) {
    throw "pyproject.toml was not found: $repositoryRoot"
}

$pyproject = Get-Content -LiteralPath $pyprojectPath -Raw
$versionMatch = [regex]::Match($pyproject, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "The project version could not be read from pyproject.toml"
}
$version = $versionMatch.Groups[1].Value

$resolvedOutputRoot = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    [IO.Path]::GetFullPath($OutputRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputRoot))
}
$releaseName = "aia-$version"
$releaseDirectory = Join-Path $resolvedOutputRoot $releaseName
if (Test-Path -LiteralPath $releaseDirectory) {
    if (-not $Force) {
        throw "Release directory already exists: $releaseDirectory (use -Force to replace it)"
    }
    Remove-Item -LiteralPath $releaseDirectory -Recurse -Force
}

New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null
$packagesDirectory = Join-Path $releaseDirectory "packages"
New-Item -ItemType Directory -Path $packagesDirectory -Force | Out-Null

Push-Location $repositoryRoot
try {
    Write-Host "[AIA] Building locked release packages..."
    & uv build --out-dir $packagesDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "uv build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

# uv may leave build metadata in the output directory. A public release bundle
# contains only the two installable Python artifacts.
Get-ChildItem -LiteralPath $packagesDirectory -File |
    Where-Object { $_.Name -notlike "*.whl" -and $_.Name -notlike "*.tar.gz" } |
    Remove-Item -Force

$supportFiles = @(
    "README.md",
    "INSTALL.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "PROJECT.md",
    "ARCHITECTURE.md",
    "AGENTS.md",
    "pyproject.toml",
    "uv.lock",
    "install.ps1"
)
foreach ($relativePath in $supportFiles) {
    $source = Join-Path $repositoryRoot $relativePath
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Required release file is missing: $relativePath"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $releaseDirectory $relativePath)
}

Copy-Item -LiteralPath (Join-Path $repositoryRoot "docs") -Destination (Join-Path $releaseDirectory "docs") -Recurse
New-Item -ItemType Directory -Path (Join-Path $releaseDirectory "scripts") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repositoryRoot "scripts\verify-release.ps1") -Destination (Join-Path $releaseDirectory "scripts\verify-release.ps1")

$installGuide = @"
# AIA $version wheel installation

This bundle targets Windows 11, Python 3.13, uv, and Codex CLI.

1. Create an isolated environment:

   uv venv

2. Install the wheel from the `packages` directory:

   uv pip install .\packages\aia_mvp-$version-py3-none-any.whl

3. Install and review the Codex Hook:

   aia setup
   # Open Codex /hooks and review/trust the AIA Hook.
   aia hook verify
   aia doctor

4. Start the local console or a protected run:

   aia console
   aia protect C:\workspace\my-project

The product scope is Windows 11 + Codex CLI + AIA Protected Run + supported
PreToolUse matchers. Read docs\PRODUCT-SUPPORT.md and docs\LIMITATIONS.md
before making a security claim.
"@
Set-Content -LiteralPath (Join-Path $releaseDirectory "INSTALL-FROM-WHEEL.md") -Value $installGuide -Encoding UTF8

$hashes = Get-ChildItem -LiteralPath $packagesDirectory -File | Sort-Object Name | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  packages/$($_.Name)"
}
Set-Content -LiteralPath (Join-Path $releaseDirectory "SHA256SUMS.txt") -Value $hashes -Encoding ASCII

$manifest = [ordered]@{
    schema_version = "aia-release-v1"
    product = "AIA"
    version = $version
    generated_at = [DateTime]::UtcNow.ToString("o")
    target = "Windows 11 / Python 3.13 / uv / Codex CLI"
    packages = @($hashes)
    limitations_document = "docs/LIMITATIONS.md"
    support_document = "docs/PRODUCT-SUPPORT.md"
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $releaseDirectory "release-manifest.json") -Encoding UTF8

$archivePath = Join-Path $resolvedOutputRoot "$releaseName.zip"
if (Test-Path -LiteralPath $archivePath) {
    if (-not $Force) {
        throw "Release archive already exists: $archivePath (use -Force to replace it)"
    }
    Remove-Item -LiteralPath $archivePath -Force
}
Compress-Archive -LiteralPath $releaseDirectory -DestinationPath $archivePath -CompressionLevel Optimal

Write-Host "[AIA] Release package created: $releaseDirectory"
Write-Host "[AIA] Release archive created: $archivePath"
Write-Host "[AIA] Verify package hashes with: Get-Content '$releaseDirectory\SHA256SUMS.txt'"
