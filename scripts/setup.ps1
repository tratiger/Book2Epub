<#
.SYNOPSIS
    Environment bootstrap and dependency installation for Book2Epub on Windows 11.
.DESCRIPTION
    Complies with Book2Epub M0 specification.
    - Uses uv with Python 3.12.
    - Installs Book2Epub in editable mode with dev dependencies.
    - Installs MinerU 3.4.5 [all].
    - Detects NVIDIA GPU; configures Blackwell (RTX 50xx) CUDA 12.8 + lmdeploy if detected.
    - Downloads EPUBCheck 5.3.0.
    - Runs book2epub doctor.
#>
[CmdletBinding()]
param(
    [switch]$SkipGpuInstall,
    [switch]$SkipEpubCheck
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Book2Epub Windows Environment Bootstrap" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Check uv on PATH
$uvPath = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvPath) {
    Write-Error "ERROR: 'uv' is not installed or not on your PATH. Please install uv from https://docs.astral.sh/uv/"
    exit 1
}
Write-Host "Found uv: $($uvPath.Source)" -ForegroundColor Green

# 2. Virtual environment with Python 3.12
Write-Host "--> Initializing Python 3.12 virtual environment..." -ForegroundColor Cyan
uv venv --python 3.12 .venv

# 3. Install project and dev dependencies
Write-Host "--> Installing Book2Epub and dev dependencies..." -ForegroundColor Cyan
uv sync --all-groups

# 4. Install MinerU 3.4.5 [all]
Write-Host "--> Installing MinerU 3.4.5 with all extras..." -ForegroundColor Cyan
uv pip install -U "mineru[all]==3.4.5"

# 5. Detect NVIDIA GPU
if (-not $SkipGpuInstall) {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($smi) {
        $gpuName = (nvidia-smi --query-gpu=name --format=csv,noheader | Out-String).Trim()
        Write-Host "Detected GPU: $gpuName" -ForegroundColor Green

        $isBlackwell = ($gpuName -match "5070" -or $gpuName -match "5080" -or $gpuName -match "5090" -or $gpuName -match "Blackwell")
        if ($isBlackwell) {
            Write-Host "--> Blackwell (RTX 50xx) detected. Installing PyTorch cu128 and lmdeploy 0.11.1..." -ForegroundColor Cyan
            uv pip install --reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128
            
            $LMDEPLOY_VERSION = "0.11.1"
            $PYTHON_VERSION = "312"
            $wheel = "https://github.com/InternLM/lmdeploy/releases/download/v$LMDEPLOY_VERSION/lmdeploy-$LMDEPLOY_VERSION+cu128-cp$PYTHON_VERSION-cp$PYTHON_VERSION-win_amd64.whl"
            Write-Host "Installing lmdeploy wheel: $wheel"
            uv pip install $wheel --no-deps
        } else {
            Write-Host "Non-Blackwell NVIDIA GPU detected ($gpuName). Primary target path is Blackwell (RTX 50-series). Letting doctor report GPU acceleration state." -ForegroundColor Yellow
        }
    } else {
        Write-Warning "nvidia-smi not found. GPU acceleration will not be available."
    }
}

# 6. Download EPUBCheck 5.3.0
if (-not $SkipEpubCheck) {
    Write-Host "--> Setting up EPUBCheck 5.3.0..." -ForegroundColor Cyan
    & "$PSScriptRoot\download_epubcheck.ps1"
}

# 7. Print MinerU model bootstrap instructions
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MinerU Local Model Setup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "MinerU models are large and not downloaded automatically during setup."
Write-Host "To download models for offline conversion, run either:"
Write-Host "  uv run mineru-models-download -s huggingface -m all" -ForegroundColor Yellow
Write-Host "  uv run mineru-models-download -s modelscope -m all" -ForegroundColor Yellow
Write-Host "After download, ensure offline use with:"
Write-Host '  $env:MINERU_MODEL_SOURCE = "local"' -ForegroundColor Yellow
Write-Host ""

# 8. Run doctor
Write-Host "--> Running Book2Epub doctor..." -ForegroundColor Cyan
uv run book2epub doctor
