[CmdletBinding()]
param(
    [string]$PackageRoot = "dist\windows",
    [int]$StartupSeconds = 8,
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
$desktopPath = Join-Path $packagePath "AIA\AIA.exe"

if (-not (Test-Path -LiteralPath $desktopPath -PathType Leaf)) {
    throw "AIA.exe를 찾지 못했습니다: $desktopPath"
}

& (Join-Path $repositoryRoot "scripts\verify-windows-package.ps1") `
    -PackageRoot $packagePath `
    -RequireSignature:$RequireSignature `
    -RequireNativeSignature:$RequireNativeSignature
if ($LASTEXITCODE -ne 0) {
    throw "Windows package verification failed"
}

function Get-DescendantProcessIds {
    param([int]$RootProcessId)

    $all = @(Get-CimInstance Win32_Process)
    $result = New-Object System.Collections.Generic.List[int]
    $frontier = New-Object System.Collections.Generic.Queue[int]
    $frontier.Enqueue($RootProcessId)
    while ($frontier.Count -gt 0) {
        $parentId = $frontier.Dequeue()
        foreach ($child in @($all | Where-Object { $_.ParentProcessId -eq $parentId })) {
            if (-not $result.Contains([int]$child.ProcessId)) {
                $result.Add([int]$child.ProcessId)
                $frontier.Enqueue([int]$child.ProcessId)
            }
        }
    }
    return @($result)
}

try {
    $desktop = Start-Process -FilePath $desktopPath -PassThru
}
catch {
    throw "AIA.exe를 시작하지 못했습니다. 현재 Windows Code Integrity 정책이 unsigned 실행 파일을 차단했을 가능성이 큽니다. 공개 빌드는 Authenticode 서명 후 실행하거나, 개발 PC에서는 관리자에게 해당 빌드의 허용 목록 등록을 요청하세요. 원본 오류: $($_.Exception.Message)"
}
try {
    Start-Sleep -Seconds ([Math]::Max(1, $StartupSeconds))
    $desktop.Refresh()
    if ($desktop.HasExited) {
        throw "AIA.exe가 시작 중 종료되었습니다. exit=$($desktop.ExitCode)"
    }
    $children = @(Get-DescendantProcessIds -RootProcessId $desktop.Id)
    if ($children.Count -eq 0) {
        throw "AIA.exe가 서버 또는 WebView2 하위 프로세스를 만들지 못했습니다."
    }
    Write-Host "[AIA] Desktop startup: PASS (pid=$($desktop.Id), descendants=$($children.Count))"
}
finally {
    $descendants = @(Get-DescendantProcessIds -RootProcessId $desktop.Id) |
        Sort-Object -Descending
    foreach ($processId in $descendants) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $desktop.Id -Force -ErrorAction SilentlyContinue
}
