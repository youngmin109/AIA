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

# Verify the installable wheel in a clean temporary environment. Hash
# verification alone cannot catch missing package data or a broken console
# entry point after the source tree is no longer present.
$wheel = @($packages | Where-Object { $_.Name -like "*.whl" })[0]
# Some Windows application-control policies block executables created under
# %TEMP%. Keep the disposable verification environment beside the already
# selected release bundle, then remove it in the finally block.
$verifyTempRoot = Join-Path $bundle (".verify-" + [guid]::NewGuid().ToString("N"))
$verifyVenv = Join-Path $verifyTempRoot ".venv"
try {
    New-Item -ItemType Directory -Path $verifyTempRoot -Force | Out-Null
    & uv venv --python 3.13 $verifyVenv
    if ($LASTEXITCODE -ne 0) {
        throw "uv venv failed with exit code $LASTEXITCODE"
    }

    $verifyPython = Join-Path $verifyVenv "Scripts\python.exe"
    & uv pip install --python $verifyPython $wheel.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "clean wheel installation failed with exit code $LASTEXITCODE"
    }

    # Run the installed module through the clean interpreter. Some Windows
    # application-control policies reject freshly generated console wrappers
    # even when the package itself is allowed to run; the module path tests the
    # same installed wheel without turning that host policy into a package
    # failure.
    $versionOutput = (& $verifyPython -m aia.cli --version | Out-String).Trim()
    $expectedVersionOutput = "AIA $([string]$manifest.version)"
    if ($LASTEXITCODE -ne 0 -or $versionOutput -ne $expectedVersionOutput) {
        throw "installed wheel CLI failed: $versionOutput"
    }

    $startHelp = (& $verifyPython -m aia.cli start --help | Out-String)
    if ($LASTEXITCODE -ne 0 -or $startHelp -notmatch "interactive protected session") {
        throw "installed wheel start entrypoint failed"
    }

    $hookExplainHelp = (& $verifyPython -m aia.cli hook explain --help | Out-String)
    if ($LASTEXITCODE -ne 0 -or $hookExplainHelp -notmatch "review") {
        throw "installed wheel Hook onboarding entrypoint failed"
    }

    $demoHelp = (& $verifyPython -m aia.cli demo --help | Out-String)
    if ($LASTEXITCODE -ne 0 -or $demoHelp -notmatch "--live") {
        throw "installed wheel demo entrypoint failed"
    }

    $demoOutput = (& $verifyPython -m aia.cli demo | Out-String)
    if ($LASTEXITCODE -ne 0 -or $demoOutput -notmatch "AIA Core Self-Test") {
        throw "installed wheel safe demo failed"
    }

    $selfTestJson = (& $verifyPython -m aia.cli self-test --json | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "installed wheel self-test failed with exit code $LASTEXITCODE"
    }
    $selfTest = $selfTestJson | ConvertFrom-Json
    if ($selfTest.passed -ne $true) {
        throw "installed wheel self-test did not report passed=true"
    }

    $capabilitiesJson = (& $verifyPython -m aia.cli capabilities --json | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "installed wheel capabilities command failed with exit code $LASTEXITCODE"
    }
    $capabilities = $capabilitiesJson | ConvertFrom-Json
    if ($capabilities.schema_version -ne "aia-capabilities-v1" -or
        $capabilities.support.pretool_matcher -ne "*" -or
        @($capabilities.support.pretool_matchers).Count -eq 0 -or
        @($capabilities.support.pretool_aliases.apply_patch) -notcontains "Edit" -or
        @($capabilities.support.pretool_aliases.apply_patch) -notcontains "Write") {
        throw "installed wheel capabilities contract is incomplete"
    }

    $webAssetsCheck = @'
from pathlib import Path
import aia_web

root = Path(aia_web.__file__).resolve().parent
required = (
    root / "templates" / "new_run.html",
    root / "templates" / "live_run.html",
    root / "static" / "app.css",
)
missing = [str(path) for path in required if not path.is_file()]
if missing:
    raise SystemExit("missing installed web assets: " + "; ".join(missing))
print("installed web assets: PASS")
'@
    $webAssetsOutput = $webAssetsCheck | & $verifyPython -
    if ($LASTEXITCODE -ne 0 -or $webAssetsOutput -notmatch "installed web assets: PASS") {
        throw "installed wheel local console assets failed: $webAssetsOutput"
    }
}
finally {
    if (Test-Path -LiteralPath $verifyTempRoot) {
        Remove-Item -LiteralPath $verifyTempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "AIA release bundle verified"
Write-Host "Version: $($manifest.version)"
Write-Host "Packages: $($packages.Count)"
Write-Host "SHA-256: PASS"
Write-Host "Clean wheel install: PASS"
Write-Host "Local console assets: PASS"
