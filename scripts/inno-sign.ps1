[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$FilePath
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $sdkRoots = @(
        (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"),
        (Join-Path ${env:ProgramFiles} "Windows Kits\10\bin")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    $candidate = $sdkRoots |
        ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter signtool.exe -Recurse -File -ErrorAction SilentlyContinue } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }
    return $null
}

$normalizedPath = $FilePath.Trim('"')
if (-not (Test-Path -LiteralPath $normalizedPath -PathType Leaf)) {
    throw "Inno Setup이 서명할 파일을 찾지 못했습니다: $normalizedPath"
}

$signTool = Find-SignTool
if (-not $signTool) {
    throw "signtool.exe를 찾지 못했습니다. Windows SDK를 설치하거나 PATH에 추가하세요."
}

$timestampUrl = if ($env:AIA_INNO_TIMESTAMP_URL) { $env:AIA_INNO_TIMESTAMP_URL } else { "https://timestamp.digicert.com" }
$signArguments = @("sign", "/fd", "SHA256", "/tr", $timestampUrl, "/td", "SHA256")
$certificatePath = $env:AIA_INNO_CERTIFICATE_PATH
$certificateThumbprint = $env:AIA_INNO_CERTIFICATE_THUMBPRINT

if ($certificatePath) {
    if (-not (Test-Path -LiteralPath $certificatePath -PathType Leaf)) {
        throw "코드 서명 인증서 파일이 없습니다: $certificatePath"
    }
    if ([IO.Path]::GetExtension($certificatePath).ToLowerInvariant() -eq ".pfx" -and -not $env:AIA_SIGNING_CERT_PASSWORD) {
        throw "PFX 인증서에는 AIA_SIGNING_CERT_PASSWORD 환경 변수가 필요합니다."
    }
    $signArguments += @("/f", [IO.Path]::GetFullPath($certificatePath), "/p", $env:AIA_SIGNING_CERT_PASSWORD)
}
elseif ($certificateThumbprint) {
    $signArguments += @("/sha1", ($certificateThumbprint -replace "\s", ""), "/s", "My")
}
else {
    throw "Inno Setup 서명에 CertificatePath 또는 CertificateThumbprint가 필요합니다."
}

Write-Host "[AIA] Inno signing: $normalizedPath"
& $signTool @signArguments $normalizedPath
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup 파일 서명 실패: $normalizedPath (exit $LASTEXITCODE)"
}

& $signTool verify /pa /all $normalizedPath
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup 파일 서명 검증 실패: $normalizedPath (exit $LASTEXITCODE)"
}
