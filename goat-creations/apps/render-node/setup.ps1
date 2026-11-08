# GOAT render node for Windows: our own image/video engine on hardware we control.
# Installs ComfyUI + the GOAT pack + open models, then starts it for the GOAT apps.
# Safe to re-run. In PowerShell:
#   powershell -ExecutionPolicy Bypass -File setup.ps1            # Light (~2.3 GB)
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Full      # + FLUX, Qwen edit, Wan video (~66 GB, 24 GB GPU)
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Pro       # flagship open models (~143 GB, 24 GB+ GPU)
param(
    [string]$Dir = "$HOME\goat-render-node",
    [int]$Port = 8188,
    [switch]$Full,
    [switch]$Pro,
    [switch]$NoStart
)
$ErrorActionPreference = "Stop"
$ComfyRepo = "https://github.com/comfyanonymous/ComfyUI"
$ComfyCommit = "2f89433"   # the version the GOAT workflows were checked against
$Pack = Resolve-Path (Join-Path $PSScriptRoot "..\comfyui-goat")
function Say($m) { Write-Host "`n==> $m" -ForegroundColor Yellow }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Please install Git for Windows first (git-scm.com)." }
$Py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Py) { throw "Please install Python 3.10+ from python.org (tick 'Add to PATH')." }
& python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required." }
$Gpu = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Set-Location $Dir

Say "ComfyUI"
if (-not (Test-Path "ComfyUI")) {
    git clone --filter=blob:none $ComfyRepo ComfyUI
    git -C ComfyUI checkout -q $ComfyCommit
} else { Write-Host "already here: $Dir\ComfyUI" }

Say "Python environment"
if (-not (Test-Path "venv")) { python -m venv venv }
$VPy = Join-Path $Dir "venv\Scripts\python.exe"
& $VPy -m pip install -q --upgrade pip
& $VPy -c "import torch" 2>$null
if ($LASTEXITCODE -ne 0) {
    if ($Gpu) { & $VPy -m pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128 }
    else { & $VPy -m pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu }
}
& $VPy -m pip install -q -r ComfyUI\requirements.txt

Say "GOAT pack"
$Dest = "ComfyUI\custom_nodes\comfyui-goat"
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item "$Pack\*.py", "$Pack\*.json", "$Pack\requirements.txt", "$Pack\README.md" $Dest
& $VPy -m pip install -q requests Pillow numpy
if ($Gpu) { & $VPy -m pip install -q onnxruntime-gpu } else { & $VPy -m pip install -q onnxruntime }

Say "Open models"
Push-Location ComfyUI
if ($Pro) { & $VPy custom_nodes\comfyui-goat\download_models.py --pro }
elseif ($Full) { & $VPy custom_nodes\comfyui-goat\download_models.py --full }
else { & $VPy custom_nodes\comfyui-goat\download_models.py }
Pop-Location

$Ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } | Select-Object -First 1).IPAddress
$Profile = if ($Pro) { "Pro" } elseif ($Full) { "Full" } else { "Light" }
Say "Ready"
Write-Host "In the GOAT CREATIONS app: Settings > My computer > http://${Ip}:$Port > $Profile > Save and test"
Write-Host "Windows may ask to allow Python through the firewall: allow it on Private networks only."
if ($NoStart) { Write-Host "Start later with: cd $Dir\ComfyUI; $VPy main.py --listen 0.0.0.0 --port $Port"; exit 0 }
Set-Location ComfyUI
$Extra = @(); if (-not $Gpu) { $Extra = @("--cpu") }
& $VPy main.py --listen 0.0.0.0 --port $Port --enable-cors-header "*" @Extra
