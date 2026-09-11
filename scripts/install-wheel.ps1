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

function Verify-ReleasePackageHash {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WheelPath,
        [Parameter(Mandatory = $true)]
        [string]$BundleRoot
    )

    $sumsPath = Join-Path $BundleRoot "SHA256SUMS.txt"
    if (-not (Test-Path -LiteralPath $sumsPath -PathType Leaf)) {
        Write-Warning "SHA256SUMS.txt was not provided; package hash verification was skipped for this external wheel."
        return
    }

    $resolvedWheel = (Resolve-Path -LiteralPath $WheelPath -ErrorAction Stop).Path
    $resolvedRoot = (Resolve-Path -LiteralPath $BundleRoot -ErrorAction Stop).Path
    $rootPrefix = $resolvedRoot.TrimEnd("\") + "\"
    if (-not $resolvedWheel.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Warning "Wheel is outside the release bundle; package hash verification was skipped."
        return
    }
    $relative = $resolvedWheel.Substring($rootPrefix.Length).Replace("\", "/")
    if (-not $relative.StartsWith("packages/", [StringComparison]::OrdinalIgnoreCase)) {
        Write-Warning "Wheel is outside the release packages directory; package hash verification was skipped."
        return
    }

    $expected = $null
    foreach ($line in Get-Content -LiteralPath $sumsPath) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $parts = $line.Trim() -split "\s+", 2
        if ($parts.Count -eq 2 -and $parts[1].Trim() -eq $relative) {
            $expected = $parts[0].Trim().ToLowerInvariant()
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($expected) -or $expected -notmatch "^[0-9a-f]{64}$") {
        throw "SHA256SUMS.txt does not contain a valid hash for $relative"
    }

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($resolvedWheel)
        try {
            $actual = ([BitConverter]::ToString($sha256.ComputeHash($stream)) -replace "-", "").ToLowerInvariant()
        }
        finally {
            $stream.Dispose()
        }
    }
    finally {
        $sha256.Dispose()
    }
    if ($actual -ne $expected) {
        throw "SHA-256 mismatch for $relative. The release wheel may be corrupted or modified."
    }
    Write-Host "[AIA] Release wheel SHA-256: PASS"
}

Verify-ReleasePackageHash -WheelPath $PackagePath -BundleRoot $scriptRoot

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
Write-Host "Prove a disposable Codex block with: aia proof"
Write-Host "Prove .env secret-read blocking with: aia proof --scenario block-env"
Write-Host "Start a protected run with: aia protect C:\workspace\my-project"
