[CmdletBinding()]
param(
    [string]$OutputRoot = "dist\windows",
    [switch]$Clean,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputPath = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    [IO.Path]::GetFullPath($OutputRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $repositoryRoot $OutputRoot))
}
$buildPath = Join-Path $repositoryRoot ".tmp-build\windows"

if ($Clean -and (Test-Path -LiteralPath $outputPath)) {
    Remove-Item -LiteralPath $outputPath -Recurse -Force
}
if ($Clean -and (Test-Path -LiteralPath $buildPath)) {
    Remove-Item -LiteralPath $buildPath -Recurse -Force
}
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
New-Item -ItemType Directory -Path $buildPath -Force | Out-Null

Push-Location $repositoryRoot
try {
    if (-not $SkipFrontendBuild) {
        Write-Host "[AIA] Building frontend SPA..."
        Push-Location (Join-Path $repositoryRoot "frontend")
        try {
            & npm ci
            if ($LASTEXITCODE -ne 0) {
                throw "npm ci failed with exit code $LASTEXITCODE"
            }
            & npm run build
            if ($LASTEXITCODE -ne 0) {
                throw "npm run build failed with exit code $LASTEXITCODE"
            }
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "[AIA] Skipping frontend build (-SkipFrontendBuild); using existing src\aia_web\static\app output."
    }

    Write-Host "[AIA] Building AIA.exe desktop shell..."
    & uv run --group build pyinstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name AIA `
        --distpath $outputPath `
        --workpath (Join-Path $buildPath "AIA") `
        --specpath (Join-Path $buildPath "spec") `
        --collect-all aia `
        --collect-all aia_app `
        --collect-all aia_desktop `
        --collect-all aia_web `
        --collect-all winpty `
        (Join-Path $repositoryRoot "src\aia_desktop\__main__.py")
    if ($LASTEXITCODE -ne 0) {
        throw "AIA.exe build failed with exit code $LASTEXITCODE"
    }

    Write-Host "[AIA] Building optional CLI diagnostics..."
    & uv run --group build pyinstaller `
        --noconfirm `
        --clean `
        --onedir `
        --console `
        --name aia-cli `
        --distpath $outputPath `
        --workpath (Join-Path $buildPath "aia-cli") `
        --specpath (Join-Path $buildPath "spec") `
        --collect-all aia `
        --collect-all aia_app `
        --collect-all aia_web `
        (Join-Path $repositoryRoot "src\aia\cli.py")
    if ($LASTEXITCODE -ne 0) {
        throw "aia-cli build failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "[AIA] Desktop build created: $outputPath\AIA\AIA.exe"
Write-Host "[AIA] CLI build created: $outputPath\aia-cli\aia-cli.exe"
