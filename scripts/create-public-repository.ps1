[CmdletBinding()]
param(
    [string]$OutputPath = "dist\public-repository",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$output = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    [System.IO.Path]::GetFullPath($OutputPath)
}
else {
    [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputPath))
}

if (Test-Path -LiteralPath $output) {
    if (-not $Force) {
        throw "Output path already exists. Use -Force to replace it: $output"
    }
    Remove-Item -LiteralPath $output -Recurse -Force
}
New-Item -ItemType Directory -Path $output -Force | Out-Null

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "export-public-tree.ps1") `
    -OutputPath $output -Force
if ($LASTEXITCODE -ne 0) {
    throw "Public source export failed."
}

Push-Location $output
try {
    & git init --initial-branch=main
    if ($LASTEXITCODE -ne 0) { throw "git init failed" }
    & git add -A
    if ($LASTEXITCODE -ne 0) { throw "git add failed" }

    $staged = @(git diff --cached --name-only)
    $forbidden = @($staged | Where-Object {
        $_ -match '(^|/)(\.env($|\.)|\.aia($|/)|\.codex($|/)|\.venv($|/)|__pycache__($|/)|dist($|/)|evaluation($|/))' -or
        $_ -match '\.(jsonl|log|db|sqlite|sqlite3|pem|key|pfx)$'
    })
    if ($forbidden.Count -gt 0) {
        throw "Public repository contains forbidden paths: $($forbidden -join ', ')"
    }

    & git -c user.name="AIA Public Release Builder" -c user.email="release@aia.invalid" `
        commit -m "chore: initialize public AIA source"
    if ($LASTEXITCODE -ne 0) { throw "public repository commit failed" }

    $commit = (git rev-parse --short HEAD).Trim()
    if ((git status --porcelain).Count -ne 0) {
        throw "Public repository is not clean after its initial commit."
    }
    Write-Host "Public repository created: $output"
    Write-Host "Initial commit: $commit"
    Write-Host "Files committed: $($staged.Count)"
}
finally {
    Pop-Location
}
