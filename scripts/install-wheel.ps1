[CmdletBinding()]
param(
    [string]$PackagePath = "",
    [switch]$SetupHook
)

$ErrorActionPreference = "Stop"

function Find-AiaExecutable {
    $command = Get-Command aia -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    # uv may have installed the shim successfully while the current
    # PowerShell has not refreshed PATH yet. Resolve uv's configured bin
    # directory directly so first-run setup can continue in this window.
    $binOutput = & uv tool dir --bin 2>$null
    if ($LASTEXITCODE -eq 0) {
        $binDirectory = ($binOutput | Select-Object -Last 1).ToString().Trim()
        if (-not [string]::IsNullOrWhiteSpace($binDirectory)) {
            foreach ($name in @("aia.exe", "aia")) {
                $candidate = Join-Path $binDirectory $name
                if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                    return (Resolve-Path -LiteralPath $candidate).Path
                }
            }
        }
    }
    return $null
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    throw "uv is required. Install uv and run this script again."
}

$scriptRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    throw "The installer directory could not be determined"
}

if ([string]::IsNullOrWhiteSpace($PackagePath)) {
    $packageCandidates = @(Get-ChildItem -LiteralPath (Join-Path $scriptRoot "packages") -Filter "aia_mvp-*.whl" -File -ErrorAction SilentlyContinue)
    if ($packageCandidates.Count -ne 1) {
        throw "Expected exactly one AIA wheel in '$scriptRoot\packages'. Pass -PackagePath to select a wheel."
    }
    $PackagePath = $packageCandidates[0].FullName
}
else {
    $PackagePath = (Resolve-Path -LiteralPath $PackagePath -ErrorAction Stop).Path
}

if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
    throw "AIA wheel was not found: $PackagePath"
}

Write-Host "[AIA] Installing the wheel as a user-level command..."
& uv tool install --force $PackagePath
if ($LASTEXITCODE -ne 0) {
    throw "uv tool install failed with exit code $LASTEXITCODE"
}

$aiaExecutable = Find-AiaExecutable
if ($null -eq $aiaExecutable) {
    if ($SetupHook) {
        throw "The aia command was installed, but its executable could not be found. Run 'uv tool dir --bin', open a new PowerShell window, and run 'aia setup'."
    }
    Write-Warning "The aia command is not on PATH in this PowerShell window. Open a new PowerShell window and run 'aia --version'."
}
else {
    & $aiaExecutable --version
    if ($SetupHook) {
        & $aiaExecutable setup
        if ($LASTEXITCODE -ne 0) {
            throw "AIA Hook setup failed with exit code $LASTEXITCODE"
        }
    }
}

Write-Host "[AIA] Installation complete."
Write-Host "Next: open Codex /hooks, review and trust the AIA Hook, then run 'aia hook verify'."
Write-Host "Start a protected run with: aia protect C:\workspace\my-project"
