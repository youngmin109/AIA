[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipPackage,
    [string]$BundlePath
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $repositoryRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $false)][string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$Label
    )

    Write-Host "[AIA] $Label"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

if (-not $SkipTests) {
    Invoke-Checked -FilePath "uv" -Arguments @("sync", "--locked") -Label "Sync locked environment"
    Invoke-Checked -FilePath "uv" -Arguments @("run", "pytest", "-ra") -Label "Run full pytest"
    Invoke-Checked -FilePath "uv" -Arguments @("run", "aia", "demo") -Label "Run safe product demo"
}

$versionOutput = (& uv run aia --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch '^AIA (\d+\.\d+\.\d+)$') {
    throw "Could not determine the current AIA version"
}
$version = $Matches[1]

if (-not $SkipPackage) {
    Invoke-Checked -FilePath "powershell" -Arguments @(
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $repositoryRoot "scripts\package-release.ps1"),
        "-Force"
    ) -Label "Build release bundle"
    $BundlePath = Join-Path $repositoryRoot "dist\release\aia-$version"
}

if ([string]::IsNullOrWhiteSpace($BundlePath)) {
    throw "BundlePath is required when -SkipPackage is used"
}
$resolvedBundle = (Resolve-Path -LiteralPath $BundlePath -ErrorAction Stop).Path
Invoke-Checked -FilePath "powershell" -Arguments @(
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $repositoryRoot "scripts\verify-release.ps1"),
    "-BundlePath", $resolvedBundle
) -Label "Verify release bundle"

Write-Host "[AIA] Release gate: PASS"
Write-Host "[AIA] Version: $version"
Write-Host "[AIA] Bundle: $resolvedBundle"
