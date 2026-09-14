[CmdletBinding()]
param(
    [switch]$RemoveTool,
    [switch]$KeepHook
)

$ErrorActionPreference = "Stop"

function Get-ProjectName {
    $pyproject = Join-Path $PSScriptRoot "pyproject.toml"
    if (-not (Test-Path -LiteralPath $pyproject -PathType Leaf)) {
        return "aia-mvp"
    }
    $text = Get-Content -LiteralPath $pyproject -Raw
    $match = [regex]::Match($text, '(?m)^name\s*=\s*"([^"]+)"')
    if ($match.Success) {
        return $match.Groups[1].Value
    }
    return "aia-mvp"
}

function Invoke-AiaHookUninstall {
    $aia = Get-Command aia -ErrorAction SilentlyContinue
    if ($null -ne $aia) {
        & $aia.Source hook uninstall
        if ($LASTEXITCODE -ne 0) {
            throw "AIA Hook removal failed with exit code $LASTEXITCODE"
        }
        return
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $pyproject = Join-Path $PSScriptRoot "pyproject.toml"
    if ($null -ne $uv -and (Test-Path -LiteralPath $pyproject -PathType Leaf)) {
        & uv run aia hook uninstall
        if ($LASTEXITCODE -ne 0) {
            throw "AIA Hook removal failed with exit code $LASTEXITCODE"
        }
        return
    }

    throw "The aia command is unavailable. Keep the Hook with -KeepHook or run this script from an installed AIA environment."
}

if (-not $KeepHook) {
    Write-Host "[AIA] Removing only the AIA Codex Hook..."
    Invoke-AiaHookUninstall
    Write-Host "[AIA] AIA Hook removed. Other Codex Hooks and user data were preserved."
}
else {
    Write-Host "[AIA] Keeping the AIA Codex Hook by request."
}

if ($RemoveTool) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $uv) {
        throw "uv is required for -RemoveTool"
    }
    $packageName = Get-ProjectName
    Write-Host "[AIA] Removing the user-level uv tool: $packageName"
    & uv tool uninstall $packageName
    if ($LASTEXITCODE -ne 0) {
        throw "uv tool uninstall failed with exit code $LASTEXITCODE"
    }
}

Write-Host "[AIA] Protected-run evidence and Control Root were preserved."
if (-not $RemoveTool) {
    Write-Host "[AIA] The user-level aia command remains installed. Use -RemoveTool to remove it too."
}
