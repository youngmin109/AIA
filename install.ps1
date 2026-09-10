[CmdletBinding()]
param(
    [string]$ProjectRoot = $PSScriptRoot,
    [switch]$SetupHook,
    [switch]$SkipDoctor,
    [switch]$InstallTool
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $scriptPath = $MyInvocation.MyCommand.Path
    if (-not [string]::IsNullOrWhiteSpace($scriptPath)) {
        $ProjectRoot = Split-Path -Parent $scriptPath
    }
    else {
        $ProjectRoot = (Get-Location).Path
    }
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    throw "uv is required. Install uv from https://docs.astral.sh/uv/ and run this script again."
}

$root = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath (Join-Path $root "pyproject.toml"))) {
    throw "ProjectRoot does not contain pyproject.toml: $root"
}

Push-Location $root
try {
    Write-Host "[AIA] Syncing the locked environment..."
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE. Close any running aia-web or AIA Python process and run the installer again."
    }

    if ($InstallTool) {
        Write-Host "[AIA] Installing the aia command as a user-level uv tool..."
        & uv tool install --force .
        if ($LASTEXITCODE -ne 0) {
            throw "uv tool install failed with exit code $LASTEXITCODE"
        }
    }

    if ($SetupHook) {
        Write-Host "[AIA] Installing the AIA Codex Hook definition..."
        if ($InstallTool) {
            $aiaCommand = Get-Command aia -ErrorAction SilentlyContinue
            if ($null -eq $aiaCommand) {
                throw "The aia command is not on PATH after uv tool install. Open a new PowerShell window and run 'aia setup'."
            }
            & $aiaCommand.Source setup
        }
        else {
            & uv run aia setup
        }
        if ($LASTEXITCODE -ne 0) {
            throw "AIA Hook setup failed with exit code $LASTEXITCODE"
        }
    }

    if (-not $SkipDoctor) {
        Write-Host "[AIA] Checking the local protected-run prerequisites..."
        if ($InstallTool) {
            & aia doctor
        }
        else {
            & uv run aia doctor
        }
        $doctorExitCode = $LASTEXITCODE
        if ($doctorExitCode -ne 0) {
            Write-Warning "AIA is installed, but the local prerequisites are not ready yet. Run 'uv run aia doctor' for details."
        }
    }

    Write-Host "[AIA] Installation complete."
    if ($InstallTool) {
        Write-Host "Next: review/trust the Hook in Codex with /hooks, then run 'aia doctor'."
        Write-Host "Start a protected run with: aia protect C:\workspace\my-project"
    }
    else {
        Write-Host "Next: review/trust the Hook in Codex with /hooks, then run 'uv run aia doctor'."
        Write-Host "Start a protected run with: uv run aia protect C:\workspace\my-project"
        Write-Host "For a user-level command available from any folder, rerun with -InstallTool."
    }
}
finally {
    Pop-Location
}
