param(
    [ValidateSet("Check", "Prepare", "Install")]
    [string]$Mode = "Check"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Test-PythonCandidate {
    param([string]$Exe, [string[]]$PrefixArgs)
    try {
        & $Exe @PrefixArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() },
        @{ Exe = "python3"; Args = @() }
    )
    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -Exe $candidate.Exe -PrefixArgs $candidate.Args) {
            return $candidate
        }
    }
    $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $localPrograms) {
        $installed = Get-ChildItem $localPrograms -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending
        foreach ($item in $installed) {
            if (Test-PythonCandidate -Exe $item.FullName -PrefixArgs @()) {
                return @{ Exe = $item.FullName; Args = @() }
            }
        }
    }
    return $null
}

$Python = Find-Python
if (-not $Python -and $Mode -eq "Install") {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
        $Python = Find-Python
    } else {
        throw "缺少Python 3.10+，且系统没有winget。请从python.org安装Python后重新运行。"
    }
}
if (-not $Python) {
    throw "缺少Python 3.10+。让Codex在取得你的确认后运行：powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 -Mode Install"
}

$Git = Get-Command git -ErrorAction SilentlyContinue
if (-not $Git -and $Mode -eq "Install") {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
        $gitCmd = "C:\Program Files\Git\cmd"
        if (Test-Path $gitCmd) { $env:Path = "$gitCmd;$env:Path" }
        $Git = Get-Command git -ErrorAction SilentlyContinue
    } else {
        Write-Warning "没有winget，ZIP仍可使用；自动Pull需要另行安装Git。"
    }
} elseif (-not $Git) {
    Write-Warning "未找到Git；ZIP可以使用，仓库自动Pull不可用。"
}

$RunExe = $Python.Exe
$RunArgs = @($Python.Args)
if ($Mode -eq "Prepare" -or $Mode -eq "Install") {
    $Runtime = Join-Path $ProjectRoot ".runtime"
    $Venv = Join-Path $Runtime "venv"
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    $PythonExe = [string]$Python.Exe
    $PythonArgs = [string[]]@($Python.Args)
    & $PythonExe @PythonArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "创建项目虚拟环境失败" }
    $RunExe = Join-Path $Venv "Scripts\python.exe"
    $RunArgs = @()
    & $RunExe (Join-Path $ProjectRoot "scripts\sync_role_dependencies.py") --install
    if ($LASTEXITCODE -ne 0) { throw "安装角色本地Python依赖失败" }
}

Write-Output "环境口径: Python>=3.10；包含APP图片Skill的角色额外使用项目venv中的Pillow；Node.js、FFmpeg和云厂商SDK不需要安装。"
& $RunExe @RunArgs (Join-Path $ProjectRoot "scripts\first_run_check.py") --offline
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Mode -eq "Prepare" -or $Mode -eq "Install") {
    Write-Output "environment_prepare=ok python=$RunExe"
} else {
    Write-Output "environment_check=ok python=$RunExe"
}
