# Install Underdog Saluki 27B (+ vision mmproj) into Ollama for Friday.
# Usage:  powershell -File scripts/install_saluki.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dir = Join-Path $Root "models\saluki"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

$env:HF_HUB_DISABLE_XET = "1"
Push-Location $Dir
try {
    & hf download ConwayResearch/Underdog-Saluki-27B-1.0 `
        Underdog-Saluki-27B-1.0-IQ2-mix.gguf `
        mmproj-Underdog-Saluki-27B-1.0-Q8_0.gguf `
        --local-dir $Dir
    if (-not (Test-Path (Join-Path $Dir "Modelfile"))) {
        @"
FROM ./Underdog-Saluki-27B-1.0-IQ2-mix.gguf
FROM ./mmproj-Underdog-Saluki-27B-1.0-Q8_0.gguf
PARAMETER temperature 0.6
PARAMETER top_p 0.95
PARAMETER top_k 20
PARAMETER num_ctx 8192
"@ | Set-Content -Path (Join-Path $Dir "Modelfile") -Encoding utf8
    }
    ollama create saluki -f Modelfile
    Write-Host "Created ollama tag: saluki"
    Write-Host "In Friday say: switch to saluki"
} finally {
    Pop-Location
}
