[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BundlePath,
    [switch]$SetupHook
)

$ErrorActionPreference = "Stop"

function Read-VersionFromText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $match = [regex]::Match($Text, "(?m)^AIA\s+(\d+\.\d+\.\d+)$")
    if (-not $match.Success) {
        throw "$Label did not report a semantic AIA version: $Text"
    }
    return [Version]$match.Groups[1].Value
}

$bundle = (Resolve-Path -LiteralPath $BundlePath -ErrorAction Stop).Path
$manifestPath = Join-Path $bundle "release-manifest.json"
$verifier = Join-Path $bundle "scripts\verify-release.ps1"
$installer = Join-Path $bundle "install.ps1"

foreach ($required in @($manifestPath, $verifier, $installer)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Rollback bundle item is missing: $required"
    }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne "aia-release-v1") {
    throw "Unsupported release manifest schema: $($manifest.schema_version)"
}
if ([string]$manifest.version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Rollback target has an invalid version: $($manifest.version)"
}
$targetVersion = [Version][string]$manifest.version

$aia = Get-Command aia -ErrorAction SilentlyContinue
if ($null -eq $aia) {
    throw "The installed aia command was not found. Open a PowerShell where aia is available before rolling back."
}
$currentOutput = (& $aia.Source --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the currently installed AIA version."
}
$currentVersion = Read-VersionFromText -Text $currentOutput -Label "Installed AIA"
if ($targetVersion -ge $currentVersion) {
    throw "Rollback target $targetVersion is not older than the installed version $currentVersion."
}

Write-Host "[AIA] Verifying rollback target $targetVersion before installation..."
& $verifier -BundlePath $bundle
if ($LASTEXITCODE -ne 0) {
    throw "Rollback target verification failed with exit code $LASTEXITCODE"
}

$installerArguments = @()
if ($SetupHook) {
    $installerArguments += "-SetupHook"
}
Write-Host "[AIA] Installing verified rollback target $targetVersion (current: $currentVersion)..."
& $installer @installerArguments
if ($LASTEXITCODE -ne 0) {
    throw "Rollback installation failed with exit code $LASTEXITCODE"
}

Write-Host "[AIA] Rollback complete: $currentVersion -> $targetVersion"
Write-Host "[AIA] Re-open Codex /hooks and review/trust the Hook if its command changed."
Write-Host "[AIA] Run 'aia hook verify' and 'aia doctor' before starting a Protected Run."
