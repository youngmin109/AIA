[CmdletBinding()]
param(
    [string]$PackageRoot = "dist\windows",
    [switch]$RequireSignature,
    [switch]$RequireNativeSignature
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packagePath = if ([IO.Path]::IsPathRooted($PackageRoot)) {
    [IO.Path]::GetFullPath($PackageRoot)
}
else {
    [IO.Path]::GetFullPath((Join-Path $repositoryRoot $PackageRoot))
}
$installer = Get-ChildItem -LiteralPath (Join-Path $packagePath "installer") -Filter "AIA-*-Setup.exe" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $installer) {
    throw "Windows installer를 찾지 못했습니다: $packagePath"
}

$verifyParameters = @{
    PackageRoot = $packagePath
    RequireSignature = [bool]$RequireSignature
    RequireNativeSignature = [bool]$RequireNativeSignature
}
& (Join-Path $repositoryRoot "scripts\verify-windows-package.ps1") @verifyParameters
if ($LASTEXITCODE -ne 0) {
    throw "Windows package verification failed"
}

$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$installRoot = [IO.Path]::GetFullPath(
    (Join-Path $tempRoot ("aia-installer-smoke-" + [guid]::NewGuid().ToString("N")))
)
if (-not $installRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Installer smoke 경로가 임시 폴더 밖에 있습니다: $installRoot"
}
New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
$installerLog = Join-Path $installRoot "installer.log"

try {
    $installArguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/DIR=$installRoot",
        "/LOG=$installerLog"
    )
    $installProcess = Start-Process -FilePath $installer.FullName -ArgumentList $installArguments -Wait -PassThru
    if ($installProcess.ExitCode -ne 0) {
        $signatureStatus = (Get-AuthenticodeSignature -LiteralPath $installer.FullName).Status
        $logTail = if (Test-Path -LiteralPath $installerLog) {
            (Get-Content -LiteralPath $installerLog -Tail 40) -join "`n"
        }
        else {
            "installer log not found"
        }
        throw "Installer failed with exit code $($installProcess.ExitCode). Authenticode=$signatureStatus. Windows Code Integrity may have blocked the unsigned installer or its temporary setup process. Sign the release package before retrying.`n$logTail"
    }

    $installedCli = Join-Path $installRoot "aia-cli\aia-cli.exe"
    $installedDesktop = Join-Path $installRoot "AIA.exe"
    if (-not (Test-Path -LiteralPath $installedDesktop -PathType Leaf)) {
        throw "설치된 AIA.exe를 찾지 못했습니다."
    }
    if (-not (Test-Path -LiteralPath $installedCli -PathType Leaf)) {
        throw "설치된 aia-cli.exe를 찾지 못했습니다."
    }
    $requiredDocs = @(
        "README.md",
        "INSTALL.md",
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "QUICKSTART.md",
        "USER-GUIDE.md",
        "TROUBLESHOOTING.md",
        "DISTRIBUTION.md"
    )
    $missingDocs = @($requiredDocs | Where-Object { -not (Test-Path -LiteralPath (Join-Path $installRoot "docs\$_") -PathType Leaf) })
    if ($missingDocs.Count -gt 0) {
        throw "설치된 제품 문서가 없습니다: $($missingDocs -join ', ')"
    }

    & $installedCli self-test --json | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "설치된 aia-cli self-test failed with exit code $LASTEXITCODE"
    }

    $uninstaller = Get-ChildItem -LiteralPath $installRoot -Filter "unins*.exe" -File |
        Select-Object -First 1
    if (-not $uninstaller) {
        throw "설치 제거 프로그램을 찾지 못했습니다."
    }
    if ($RequireSignature) {
        $installedSignatureTargets = @($installedDesktop, $installedCli, $uninstaller.FullName)
        if ($RequireNativeSignature) {
            $installedSignatureTargets += Get-ChildItem -LiteralPath $installRoot -Recurse -File |
                Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".dll", ".pyd") } |
                ForEach-Object { $_.FullName }
        }
        $invalidInstalledSignatures = @(
            $installedSignatureTargets |
                Sort-Object -Unique |
                Where-Object { (Get-AuthenticodeSignature -LiteralPath $_).Status -ne "Valid" }
        )
        if ($invalidInstalledSignatures.Count -gt 0) {
            throw "설치 후 서명 검증에 실패했습니다: $($invalidInstalledSignatures -join ', ')"
        }
    }
    $uninstallProcess = Start-Process -FilePath $uninstaller.FullName -ArgumentList @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART"
    ) -Wait -PassThru
    if ($uninstallProcess.ExitCode -ne 0) {
        throw "Uninstaller failed with exit code $($uninstallProcess.ExitCode)"
    }

    Write-Host "[AIA] Windows installer smoke: PASS"
}
finally {
    if (Test-Path -LiteralPath $installRoot) {
        Remove-Item -LiteralPath $installRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
