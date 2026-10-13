[CmdletBinding()]
param(
    [string]$OutputPath = "dist\public-source",
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

if (([System.IO.Path]::GetFullPath($output)).TrimEnd('\') -eq $repositoryRoot.TrimEnd('\')) {
    throw "OutputPath must not be the repository root."
}

if (Test-Path -LiteralPath $output) {
    if (-not $Force) {
        throw "Output path already exists. Use -Force to replace it: $output"
    }
    Remove-Item -LiteralPath $output -Recurse -Force
}
New-Item -ItemType Directory -Path $output -Force | Out-Null

$rootFiles = @(
    ".gitignore",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "INSTALL.md",
    "LICENSE",
    "PROJECT.md",
    "README.md",
    "README.ko.md",
    "SECURITY.md",
    "THIRD-PARTY-NOTICES.md",
    "install.ps1",
    "pyproject.toml",
    "uninstall.ps1",
    "uv.lock"
)

$rootDirectories = @(
    ".github",
    "frontend",
    "packaging",
    "policies",
    "scripts",
    "src",
    "tests"
)

function Copy-PublicItem {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $source = Join-Path $repositoryRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) {
        return
    }

    $destination = Join-Path $output $RelativePath
    if ((Get-Item -LiteralPath $source).PSIsContainer) {
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        Get-ChildItem -LiteralPath $source -File -Recurse -Force | ForEach-Object {
            $childRelative = $_.FullName.Substring($repositoryRoot.Length).TrimStart([char]92, [char]47)
            $normalized = $childRelative.Replace('\', '/')
            if ($normalized -match '(^|/)(\.env($|\.)|\.aia($|/)|\.codex($|/)|\.venv($|/)|__pycache__($|/)|dist($|/)|build($|/)|tmp($|/)|output($|/))' -or
                $normalized -match '\.(jsonl|log|db|sqlite|sqlite3|pem|key|pfx)$' -or
                $normalized -match '(^|/)node_modules/' -or
                $normalized -match '^src/aia_web/static/app/' -or
                $normalized -match '\.tsbuildinfo$' -or
                $normalized -match '^docs/generated/' -or
                $normalized -match '^docs/validation/evidence/') {
                return
            }
            $childDestination = Join-Path $output $childRelative
            New-Item -ItemType Directory -Path (Split-Path -Parent $childDestination) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $childDestination -Force
        }
        return
    }

    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

foreach ($item in $rootFiles + $rootDirectories) {
    Copy-PublicItem -RelativePath $item
}

# Technical and user-facing documentation is public source material. Generated
# documents and captured validation evidence are intentionally excluded above.
Copy-PublicItem -RelativePath "docs"

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify-public-tree.ps1") -RootPath $output
if ($LASTEXITCODE -ne 0) {
    throw "The generated public tree did not pass verification: $output"
}

Write-Host "Public source tree exported: $output"
