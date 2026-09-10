[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BundlePath
)

$ErrorActionPreference = "Stop"

$bundle = (Resolve-Path -LiteralPath $BundlePath -ErrorAction Stop).Path
$manifestPath = Join-Path $bundle "release-manifest.json"
$sumsPath = Join-Path $bundle "SHA256SUMS.txt"
$packagesPath = Join-Path $bundle "packages"

foreach ($required in @($manifestPath, $sumsPath, $packagesPath)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Release bundle item is missing: $required"
    }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne "aia-release-v1") {
    throw "Unsupported release manifest schema: $($manifest.schema_version)"
}
if ([string]::IsNullOrWhiteSpace([string]$manifest.version)) {
    throw "Release manifest does not contain a version"
}

$packages = @(Get-ChildItem -LiteralPath $packagesPath -File |
    Where-Object { $_.Name -like "*.whl" -or $_.Name -like "*.tar.gz" } |
    Sort-Object Name)
if ($packages.Count -ne 2) {
    throw "A release bundle must contain exactly one wheel and one source archive"
}
if (@($packages | Where-Object { $_.Name -like "*.whl" }).Count -ne 1) {
    throw "Release bundle must contain exactly one wheel"
}
if (@($packages | Where-Object { $_.Name -like "*.tar.gz" }).Count -ne 1) {
    throw "Release bundle must contain exactly one source archive"
}

$expectedHashes = @{}
foreach ($line in Get-Content -LiteralPath $sumsPath) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    $parts = $line.Trim() -split "\s+", 2
    if ($parts.Count -ne 2 -or $parts[0] -notmatch "^[0-9a-fA-F]{64}$") {
        throw "Invalid SHA-256 manifest line: $line"
    }
    $relative = $parts[1].Trim()
    if ($relative -notlike "packages/*") {
        throw "SHA-256 manifest contains a path outside packages: $relative"
    }
    $expectedHashes[$relative.Replace("/", "\")] = $parts[0].ToLowerInvariant()
}

if ($expectedHashes.Count -ne $packages.Count) {
    throw "SHA-256 manifest does not cover exactly the release package files"
}

foreach ($package in $packages) {
    $relative = "packages\$($package.Name)"
    if (-not $expectedHashes.ContainsKey($relative)) {
        throw "SHA-256 manifest is missing: $relative"
    }
    $actual = (Get-FileHash -LiteralPath $package.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expectedHashes[$relative]) {
        throw "SHA-256 mismatch: $relative"
    }
}

$manifestPackageNames = @($manifest.packages | ForEach-Object {
    if ($_ -is [string]) {
        ($_ -split "\s+", 2)[1]
    }
}) | Sort-Object
$actualPackageNames = @($packages | ForEach-Object { "packages/$($_.Name)" }) | Sort-Object
if ((ConvertTo-Json $manifestPackageNames -Compress) -ne (ConvertTo-Json $actualPackageNames -Compress)) {
    throw "Release manifest package list does not match the bundle"
}

Write-Host "AIA release bundle verified"
Write-Host "Version: $($manifest.version)"
Write-Host "Packages: $($packages.Count)"
Write-Host "SHA-256: PASS"
