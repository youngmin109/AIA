[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RootPath
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $RootPath -ErrorAction Stop).Path

function Convert-ToRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $relative = $Path.Substring($root.Length).TrimStart([char]92, [char]47)
    return $relative.Replace('\\', "/")
}

function Add-Finding {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Reason
    )

    $script:findings += [pscustomobject]@{
        Path = $Path
        Reason = $Reason
    }
}

$script:findings = @()
$files = @(Get-ChildItem -LiteralPath $root -File -Recurse -Force)

$forbiddenPathPatterns = @(
    '(^|/)(\.env($|\.)|\.aia($|/)|\.codex($|/)|\.venv($|/)|__pycache__($|/)|dist($|/)|build($|/)|tmp($|/)|output($|/)|evaluation($|/))',
    '\.(jsonl|log|db|sqlite|sqlite3|pem|key|pfx)$'
)

$textExtensions = @(
    '.c', '.cfg', '.css', '.csv', '.html', '.ini', '.js', '.json', '.md',
    '.ps1', '.py', '.pyi', '.rst', '.toml', '.ts', '.txt', '.yaml', '.yml'
)

$currentUser = [regex]::Escape([Environment]::UserName)
$secretPatterns = @(
    '(?i)-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    '(?i)\b(?:sk|rk)-[A-Za-z0-9]{20,}\b',
    '(?i)\bgh[pousr]_[A-Za-z0-9_]{20,}\b',
    '(?i)\bgithub_pat_[A-Za-z0-9_]{20,}\b',
    '(?i)\bAKIA[0-9A-Z]{16}\b',
    '(?i)\bAIza[0-9A-Za-z_-]{30,}\b',
    '(?i)\bxox[baprs]-[0-9A-Za-z-]{20,}\b',
    '(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{24,}\b',
    '(?i)\b(?:api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*["'']?[A-Za-z0-9+/._=-]{20,}',
    "(?i)[A-Z]:\\Users\\$currentUser(?:\\|$)",
    '(?i)C:\\workspace\\01_projects\\aia-mvp(?:\\|$)'
)

foreach ($file in $files) {
    $relative = Convert-ToRelativePath -Path $file.FullName
    foreach ($pattern in $forbiddenPathPatterns) {
        if ($relative -match $pattern) {
            Add-Finding -Path $relative -Reason "forbidden public artifact path"
            break
        }
    }

    if ($relative -eq 'scripts/verify-public-tree.ps1') {
        continue
    }

    if ($textExtensions -contains $file.Extension.ToLowerInvariant() -and $file.Length -le 5MB) {
        try {
            $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
            if ($bytes -contains 0) {
                continue
            }
            $content = [System.Text.Encoding]::UTF8.GetString($bytes)
            foreach ($pattern in $secretPatterns) {
                if ($content -match $pattern) {
                    Add-Finding -Path $relative -Reason "secret or personal path pattern"
                    break
                }
            }
        }
        catch {
            Add-Finding -Path $relative -Reason "could not inspect text file"
        }
    }
}

$required = @(
    'README.md',
    'INSTALL.md',
    'LICENSE',
    'SECURITY.md',
    'CONTRIBUTING.md',
    'pyproject.toml',
    'uv.lock',
    'src',
    'tests',
    'scripts',
    'policies'
)
foreach ($item in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $item))) {
        Add-Finding -Path $item -Reason "required public source item is missing"
    }
}

if ($findings.Count -gt 0) {
    Write-Error ("Public tree verification failed with {0} finding(s):`n{1}" -f $findings.Count, (($findings | ForEach-Object { "- $($_.Path): $($_.Reason)" }) -join "`n"))
    exit 1
}

Write-Host "Public tree verified: PASS"
Write-Host "Files checked: $($files.Count)"
