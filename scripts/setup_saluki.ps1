# Underdog Saluki 27B as ONE Ollama multimodal tag (text GGUF + mmproj).
# Friday must use the same tag for chat AND vision — no second model in VRAM.
# Requires Ollama 0.40+ (0.30.x is too old for this GGUF).
# Vision via custom mmproj is experimental on Ollama; if create/run fails, do not use Saluki.
# https://huggingface.co/ConwayResearch/Underdog-Saluki-27B-1.0

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dir = Join-Path $Root "models\gguf\saluki"
$Gguf = "Underdog-Saluki-27B-1.0-IQ2-mix.gguf"
$Mmproj = "mmproj-Underdog-Saluki-27B-1.0-Q8_0.gguf"  # smaller add-on (~629 MB); use F16 if you prefer
$Tag = if ($env:FRIDAY_SALUKI_TAG) { $env:FRIDAY_SALUKI_TAG } else { "saluki" }

New-Item -ItemType Directory -Force -Path $Dir | Out-Null

function Ensure-File([string]$Name) {
    $Path = Join-Path $Dir $Name
    if (Test-Path $Path) {
        Write-Host "Present: $Name"
        return $Path
    }
    Write-Host "Downloading $Name…"
    hf download ConwayResearch/Underdog-Saluki-27B-1.0 $Name --local-dir $Dir
    if (-not (Test-Path $Path)) { throw "Download missing: $Path" }
    return $Path
}

$ModelPath = Ensure-File $Gguf
$ProjPath = Ensure-File $Mmproj

$Modelfile = Join-Path $Dir "Modelfile"
@"
FROM $ModelPath
FROM $ProjPath
PARAMETER temperature 0.6
PARAMETER num_ctx 16384
PARAMETER think false
"@ | Set-Content -Path $Modelfile -Encoding utf8

Write-Host "Creating Ollama multimodal model '$Tag' (single resident model)…"
ollama create $Tag -f $Modelfile

Write-Host ""
Write-Host "Smoke-test text:  ollama run $Tag `"reply with one word: pong`""
Write-Host "Then in Friday Systems set BOTH Chat model and Vision model to: $Tag"
Write-Host "If ollama create/run errors on mmproj, Saluki is a no-go on this GPU stack — stay on gemma4:12b."
