# Install Wav2Lip under data/vendor/Wav2Lip (+ dedicated .venv) for Friday lip-sync.
# Usage (repo root):  .\scripts\install_wav2lip.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Vendor = Join-Path $Root "data\vendor\Wav2Lip"
$CkptDir = Join-Path $Vendor "checkpoints"
$SfdDir = Join-Path $Vendor "face_detection\detection\sfd"
$Venv = Join-Path $Vendor ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"

Write-Host "[Wav2Lip] Target: $Vendor"

if (-not (Test-Path (Join-Path $Vendor "inference.py"))) {
  if (Test-Path $Vendor) {
    Write-Host "[Wav2Lip] Incomplete folder — removing and recloning…"
    Remove-Item -Recurse -Force $Vendor
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $Vendor) | Out-Null
  Write-Host "[Wav2Lip] Cloning Rudrabha/Wav2Lip…"
  git clone --depth 1 https://github.com/Rudrabha/Wav2Lip.git $Vendor
} else {
  Write-Host "[Wav2Lip] Repo already present."
}

New-Item -ItemType Directory -Force -Path $CkptDir | Out-Null
New-Item -ItemType Directory -Force -Path $SfdDir | Out-Null

function Get-File($Url, $Dest) {
  if (Test-Path $Dest) {
    $len = (Get-Item $Dest).Length
    if ($len -gt 1MB) {
      Write-Host "[Wav2Lip] Have $(Split-Path $Dest -Leaf) ($([math]::Round($len/1MB,1)) MB)"
      return
    }
  }
  Write-Host "[Wav2Lip] Downloading $(Split-Path $Dest -Leaf)…"
  curl.exe -L --fail --retry 3 -o $Dest $Url
  if (-not (Test-Path $Dest) -or (Get-Item $Dest).Length -lt 1MB) {
    throw "Download failed or too small: $Dest"
  }
}

$Gan = Join-Path $CkptDir "wav2lip_gan.pth"
$Sfd = Join-Path $SfdDir "s3fd.pth"
Get-File "https://huggingface.co/camenduru/Wav2Lip/resolve/main/checkpoints/wav2lip_gan.pth" $Gan
Get-File "https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth" $Sfd

# Dedicated venv on Python 3.12 — torch CUDA wheels are not on 3.14 yet.
$Py312 = $null
try { $Py312 = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null) } catch {}
if (-not $Py312) { throw "Python 3.12 required for Wav2Lip (py -3.12). Friday can stay on 3.14." }
if (-not (Test-Path $VenvPy)) {
  Write-Host "[Wav2Lip] Creating .venv with Python 3.12…"
  & py -3.12 -m venv $Venv
}
Write-Host "[Wav2Lip] Installing torch + deps into vendor venv…"
& $VenvPy -m pip install -U pip wheel
& $VenvPy -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
# Core only — audio.py is a numpy mel shim (avoids flaky scipy/librosa wheels).
& $VenvPy -m pip install numpy tqdm
try {
  & $VenvPy -m pip install --default-timeout=120 opencv-python-headless
} catch {
  Write-Host "[Wav2Lip] opencv pip failed — copy abi3 cv2 from friday_env if present."
}
& $VenvPy -c "import cv2" 2>$null
if ($LASTEXITCODE -ne 0) {
  $srcCv2 = Join-Path $Root "friday_env\Lib\site-packages\cv2"
  $dstSp = Join-Path $Venv "Lib\site-packages"
  if (Test-Path $srcCv2) {
    Copy-Item -Recurse -Force $srcCv2 (Join-Path $dstSp "cv2")
    Get-ChildItem (Join-Path $Root "friday_env\Lib\site-packages") -Filter "opencv*" |
      ForEach-Object { Copy-Item -Recurse -Force $_.FullName (Join-Path $dstSp $_.Name) }
  }
}

# Keep vendor audio.py as Friday's numpy shim if present in repo scripts overlay
$AudioShim = Join-Path $PSScriptRoot "wav2lip_audio_numpy.py"
if (Test-Path $AudioShim) {
  Copy-Item -Force $AudioShim (Join-Path $Vendor "audio.py")
  Write-Host "[Wav2Lip] Applied numpy audio shim (no librosa/scipy)."
}

& $VenvPy -c "import torch,cv2,numpy; print('[Wav2Lip] torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'cv2', cv2.__version__)"

$OkInfer = Test-Path (Join-Path $Vendor "inference.py")
$OkCkpt = Test-Path $Gan
$OkSfd = Test-Path $Sfd
$OkVenv = Test-Path $VenvPy
Write-Host ""
Write-Host "[Wav2Lip] inference.py  : $OkInfer"
Write-Host "[Wav2Lip] wav2lip_gan   : $OkCkpt"
Write-Host "[Wav2Lip] s3fd face det : $OkSfd"
Write-Host "[Wav2Lip] vendor .venv  : $OkVenv"
if ($OkInfer -and $OkCkpt -and $OkSfd -and $OkVenv) {
  Write-Host "[Wav2Lip] Ready. Systems → Presence → Lip-sync ON → engine Wav2Lip (or auto)."
  exit 0
}
Write-Host "[Wav2Lip] Incomplete — check errors above."
exit 1
