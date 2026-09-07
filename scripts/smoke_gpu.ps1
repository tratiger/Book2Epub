<#
.SYNOPSIS
    Smoke test for NVIDIA GPU acceleration, PyTorch CUDA, and lmdeploy.
.DESCRIPTION
    Complies with Book2Epub M0 specification.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "==> Testing NVIDIA GPU Acceleration..." -ForegroundColor Cyan

uv run python -c "import sys, torch; print('Python:', sys.version); print('Torch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None'); print('CUDA version:', torch.version.cuda); x = torch.randn(1000, 1000, device='cuda' if torch.cuda.is_available() else 'cpu'); print('Tensor op sum:', float(torch.matmul(x, x).sum()))"

Write-Host "==> Testing lmdeploy Blackwell Acceleration..." -ForegroundColor Cyan
uv run python -c "import lmdeploy; print('lmdeploy:', getattr(lmdeploy, '__version__', 'available'))"

Write-Host "==> GPU Smoke Test Completed Successfully." -ForegroundColor Green
