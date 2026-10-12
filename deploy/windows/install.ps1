<#
.SYNOPSIS
    Open Friday native Windows installer.

.DESCRIPTION
    One-click install for Windows 11:
      1. Check OS / Python 3.14 / git
      2. Clone (or update) the repo under %LOCALAPPDATA%\OpenFriday
      3. Create venv, install requirements/core.lock.txt, editable CLI
      4. Seed .env from .env.example
      5. Detect Ollama; optional model pulls
      6. Shim `friday` onto the user PATH
      7. Run `friday doctor`

    One-liner (after this file is on the default branch):
      irm https://raw.githubusercontent.com/skemadiya2833/open-friday/main/deploy/windows/install.ps1 | iex

    File invocation (supports switches):
      .\install.ps1 -Force
      .\install.ps1 -PullModels
      .\install.ps1 -PullModels -PullVision

    Env knobs (for irm | iex, where -switches are unreachable):
      $env:FRIDAY_HOME = 'D:\Apps\OpenFriday'
      $env:FRIDAY_REPO_URL = 'https://github.com/skemadiya2833/open-friday.git'
      $env:FRIDAY_FORCE = '1'
      $env:FRIDAY_PULL_MODELS = '1'
      $env:FRIDAY_PULL_VISION = '1'

.NOTES
    Doctor never downloads models unless you pass -PullModels / -PullVision.
    No OAuth connectors. No messaging bots. Leaves Ollama/Python on uninstall.
#>

[CmdletBinding()]
param(
    [switch] $Force,
    [switch] $PullModels,
    [switch] $PullVision
)

$ErrorActionPreference = 'Stop'

if (-not $Force -and $env:FRIDAY_FORCE) { $Force = $true }
if (-not $PullModels -and $env:FRIDAY_PULL_MODELS) { $PullModels = $true }
if (-not $PullVision -and $env:FRIDAY_PULL_VISION) { $PullVision = $true }

function Write-Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[ok]    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) {
    Write-Host "[fail]  $msg" -ForegroundColor Red
    throw [System.InvalidOperationException]::new([string] $msg)
}

function Update-PathFromRegistry {
    $machinePath = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = [System.Environment]::ExpandEnvironmentVariables("$machinePath;$userPath")
}

function Install-WithWinget {
    param([string] $WingetId, [string] $CommandName)
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $null }
    Write-Info "  Installing $WingetId via winget (silent)..."
    & winget install --id $WingetId --silent --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "  winget install $WingetId exited $LASTEXITCODE"
        return $null
    }
    Update-PathFromRegistry
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-Python314 {
    foreach ($name in @('python', 'python3', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            if ($name -eq 'py') {
                $verRaw = & $cmd.Source -3.14 --version 2>&1
                if ($LASTEXITCODE -eq 0 -and "$verRaw" -match '3\.14') {
                    return @{ Exe = $cmd.Source; Args = @('-3.14') }
                }
            } else {
                $verRaw = & $cmd.Source --version 2>&1
                if ("$verRaw" -match 'Python 3\.14') {
                    return @{ Exe = $cmd.Source; Args = @() }
                }
            }
        } catch { }
    }
    return $null
}

function Save-InstallState($path, $state) {
    $dir = Split-Path $path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    ($state | ConvertTo-Json -Depth 6) | Set-Content -Path $path -Encoding UTF8
}

# ---------------------------------------------------------------------------
# 1. OS
# ---------------------------------------------------------------------------
Write-Info "Checking OS..."
if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne 'Win32NT') {
    Write-Fail "install.ps1 is for native Windows 11."
}
$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 22000) {
    Write-Warn2 "Windows build $build looks older than Windows 11 (22000+). Continuing anyway."
} else {
    Write-Ok "Windows build $build"
}

# ---------------------------------------------------------------------------
# Paths / state
# ---------------------------------------------------------------------------
$installRoot = if ($env:FRIDAY_HOME) { $env:FRIDAY_HOME } else { Join-Path $env:LOCALAPPDATA 'OpenFriday' }
$srcDir      = Join-Path $installRoot 'src'
$venvDir     = Join-Path $installRoot 'friday_env'
$binDir      = Join-Path $installRoot 'bin'
$stateDir    = Join-Path $installRoot '.state'
$statePath   = Join-Path $stateDir 'install-state.json'
$repoUrl     = if ($env:FRIDAY_REPO_URL) { $env:FRIDAY_REPO_URL } else { 'https://github.com/skemadiya2833/open-friday.git' }

$state = @{ completed = @() }
if ((Test-Path $statePath) -and -not $Force) {
    try {
        $raw = Get-Content $statePath -Raw | ConvertFrom-Json
        $done = @()
        if ($raw.completed) { $done = @($raw.completed) }
        $state = @{ completed = $done }
    } catch {
        $state = @{ completed = @() }
    }
}
if (-not $state.completed) { $state.completed = @() }

function Step-Done([string]$name) {
    return (-not $Force) -and ($state.completed -contains $name)
}
function Mark-Done([string]$name) {
    if ($state.completed -notcontains $name) {
        $state.completed = @($state.completed) + @($name)
    }
    Save-InstallState $statePath $state
}

Write-Info "Install root: $installRoot"
if (-not (Test-Path $installRoot)) { New-Item -ItemType Directory -Path $installRoot | Out-Null }

# ---------------------------------------------------------------------------
# 2. Python 3.14
# ---------------------------------------------------------------------------
Write-Info "Checking Python 3.14..."
$py = Get-Python314
if (-not $py) {
    Write-Info "Python 3.14 not found — attempting winget install..."
    $null = Install-WithWinget -WingetId 'Python.Python.3.14' -CommandName 'python'
    $py = Get-Python314
}
if (-not $py) {
    Write-Fail @"
Python 3.14 (64-bit) is required.

Install from https://www.python.org/downloads/ (check 'Add python.exe to PATH')
or:  winget install Python.Python.3.14

Then re-run this installer.
"@
}
$pythonExe = $py.Exe
$pythonPrefix = $py.Args
Write-Ok "Python 3.14 ($pythonExe $($pythonPrefix -join ' '))"

# ---------------------------------------------------------------------------
# 3. git
# ---------------------------------------------------------------------------
Write-Info "Checking git..."
$gitExe = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $gitExe) {
    $gitExe = Install-WithWinget -WingetId 'Git.Git' -CommandName 'git'
}
if (-not $gitExe) {
    Write-Fail "git not found. Install via winget install Git.Git then re-run."
}
Write-Ok "git ($gitExe)"

# ---------------------------------------------------------------------------
# 4. Clone / update
# ---------------------------------------------------------------------------
if (Step-Done 'clone' -and (Test-Path (Join-Path $srcDir '.git'))) {
    Write-Ok "Repository already present (use -Force to update)"
} elseif (Test-Path (Join-Path $srcDir '.git')) {
    Write-Info "Updating repository..."
    & $gitExe -C $srcDir pull --ff-only
    if ($LASTEXITCODE -ne 0) { Write-Fail "git pull failed" }
    Mark-Done 'clone'
    Write-Ok "Repository updated"
} else {
    if (Test-Path $srcDir) { Remove-Item $srcDir -Recurse -Force }
    Write-Info "Cloning $repoUrl ..."
    & $gitExe clone --depth 1 $repoUrl $srcDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "git clone failed" }
    Mark-Done 'clone'
    Write-Ok "Cloned to $srcDir"
}

# ---------------------------------------------------------------------------
# 5. Venv + deps
# ---------------------------------------------------------------------------
if (-not (Step-Done 'venv') -or -not (Test-Path (Join-Path $venvDir 'Scripts\python.exe'))) {
    Write-Info "Creating venv at $venvDir ..."
    & $pythonExe @pythonPrefix -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "venv creation failed" }
    Mark-Done 'venv'
    Write-Ok "venv ready"
} else {
    Write-Ok "venv already exists"
}

$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$venvPip    = Join-Path $venvDir 'Scripts\pip.exe'

Write-Info "Installing dependencies (core.lock.txt)..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Fail "pip upgrade failed" }
& $venvPip install -r (Join-Path $srcDir 'requirements\core.lock.txt')
if ($LASTEXITCODE -ne 0) { Write-Fail "pip install core.lock.txt failed" }
& $venvPip install -e $srcDir
if ($LASTEXITCODE -ne 0) { Write-Fail "editable install (friday CLI) failed" }
Mark-Done 'deps'
Write-Ok "Dependencies installed"

# ---------------------------------------------------------------------------
# 6. .env
# ---------------------------------------------------------------------------
$envExample = Join-Path $srcDir '.env.example'
$envFile    = Join-Path $srcDir '.env'
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Ok "Created .env from .env.example"
    } else {
        Write-Warn2 ".env.example missing — create .env manually"
    }
} else {
    Write-Ok ".env already present"
}
Mark-Done 'env'

# ---------------------------------------------------------------------------
# 7. PATH shim
# ---------------------------------------------------------------------------
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir | Out-Null }
$cmdPath = Join-Path $binDir 'friday.cmd'
@"
@echo off
"$venvPython" -m friday.cli %*
"@ | Set-Content -Path $cmdPath -Encoding ASCII

$userPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
$parts = $userPath.Split(';') | Where-Object { $_ -and ($_ -ne $binDir) }
$newUserPath = (@($binDir) + $parts) -join ';'
[System.Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
$env:Path = "$binDir;$env:Path"
Write-Ok "PATH shim: $cmdPath"
Mark-Done 'shim'

# ---------------------------------------------------------------------------
# 8. Ollama
# ---------------------------------------------------------------------------
Write-Info "Checking Ollama..."
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Warn2 "Ollama not on PATH. Install from https://ollama.com/download then re-open the terminal."
    Write-Warn2 "Friday will not pull models automatically (use -PullModels / -PullVision)."
} else {
    Write-Ok "ollama ($($ollama.Source))"
    if ($PullModels -or $PullVision) {
        $toPull = @('qwen3.5:9b', 'nomic-embed-text')
        if ($PullVision) { $toPull += 'qwen3-vl:8b-instruct' }
        foreach ($tag in $toPull) {
            Write-Info "ollama pull $tag ..."
            & ollama pull $tag
            if ($LASTEXITCODE -ne 0) { Write-Warn2 "pull failed for $tag (continuing)" }
        }
    } else {
        Write-Info "Skipping model pulls. Later run: ollama pull qwen3.5:9b && ollama pull nomic-embed-text"
        Write-Info "Vision (optional): ollama pull qwen3-vl:8b-instruct"
        Write-Info "Or re-run installer with -PullModels / -PullVision"
    }
}
Mark-Done 'ollama'

# Optional uv hint (hybrid MCP)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Warn2 "uv not on PATH. Hybrid desktop agent (Windows-MCP) needs uv: https://docs.astral.sh/uv/"
}

# ---------------------------------------------------------------------------
# 9. Doctor
# ---------------------------------------------------------------------------
Write-Info "Running friday doctor..."
Push-Location $srcDir
try {
    & $venvPython -m friday.cli doctor
    $doctorCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($doctorCode -eq 0) {
    Write-Ok "Doctor: PASS"
} elseif ($doctorCode -eq 1) {
    Write-Warn2 "Doctor: WARN (see next steps above)"
} else {
    Write-Warn2 "Doctor: FAIL (fix issues above, then: friday doctor)"
}
Mark-Done 'doctor'

Write-Host ""
Write-Ok "Open Friday installed."
Write-Host "  Start:   friday"
Write-Host "  Doctor:  friday doctor"
Write-Host "  Version: friday version"
Write-Host "  UI:      http://127.0.0.1:8787/"
Write-Host "  Source:  $srcDir"
Write-Host "  Uninstall: irm https://raw.githubusercontent.com/skemadiya2833/open-friday/main/deploy/windows/uninstall.ps1 | iex"
Write-Host ""
Write-Info "If 'friday' is not found, open a new PowerShell window (PATH refresh)."
