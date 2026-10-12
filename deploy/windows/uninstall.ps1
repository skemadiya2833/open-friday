<#
.SYNOPSIS
    Remove an Open Friday install created by deploy/windows/install.ps1.

.DESCRIPTION
    Deletes %LOCALAPPDATA%\OpenFriday (or $env:FRIDAY_HOME) and removes the
    PATH shim. Leaves Python, git, Ollama, and uv installed.

    irm https://raw.githubusercontent.com/skemadiya2833/open-friday/main/deploy/windows/uninstall.ps1 | iex
#>

[CmdletBinding()]
param(
    [switch] $Yes
)

$ErrorActionPreference = 'Stop'

function Write-Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[ok]    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }

$installRoot = if ($env:FRIDAY_HOME) { $env:FRIDAY_HOME } else { Join-Path $env:LOCALAPPDATA 'OpenFriday' }
$binDir = Join-Path $installRoot 'bin'

if (-not (Test-Path $installRoot)) {
    Write-Warn2 "Nothing to remove at $installRoot"
} else {
    if (-not $Yes -and -not $env:FRIDAY_UNINSTALL_YES) {
        $answer = Read-Host "Remove Open Friday at $installRoot ? [y/N]"
        if ($answer -notmatch '^[Yy]') {
            Write-Info "Cancelled."
            return
        }
    }
    Write-Info "Removing $installRoot ..."
    Remove-Item -LiteralPath $installRoot -Recurse -Force
    Write-Ok "Removed install directory"
}

$userPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath) {
    $parts = $userPath.Split(';') | Where-Object { $_ -and ($_ -ne $binDir) }
    $newPath = $parts -join ';'
    [System.Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Ok "Removed PATH entry for $binDir"
}

Write-Ok "Uninstall complete. Python / Ollama / git / uv were left in place."
