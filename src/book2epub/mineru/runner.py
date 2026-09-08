"""MinerU CLI subprocess execution manager."""

import logging
import os
import shutil
from pathlib import Path

from book2epub.config import MinerUConfig
from book2epub.errors import MinerUError
from book2epub.util.subprocess import run_command

logger = logging.getLogger(__name__)


def verify_cuda_available() -> None:
    """Verify that PyTorch CUDA acceleration is active before executing MinerU hybrid-engine."""
    try:
        import torch

        if not torch.cuda.is_available():
            raise MinerUError(
                "CUDA acceleration is unavailable in PyTorch. "
                "Scanned book conversion requires NVIDIA GPU acceleration for "
                "hybrid-engine with high effort.\n"
                "Please run 'uv run book2epub doctor' to diagnose and resolve GPU setup."
            )
    except ImportError as e:
        raise MinerUError(
            "PyTorch is not installed in the current environment.\n"
            "Please run 'uv run book2epub doctor'."
        ) from e


def build_mineru_command(
    source_pdf: Path,
    raw_output_dir: Path,
    cfg: MinerUConfig,
) -> list[str]:
    """Build the exact argument list for the MinerU CLI invocation."""
    mineru_bin = shutil.which("mineru") or "mineru"
    cmd = [
        mineru_bin,
        "-p",
        str(source_pdf.resolve()),
        "-o",
        str(raw_output_dir.resolve()),
        "--backend",
        cfg.backend,
        "--effort",
        cfg.effort,
        "--method",
        cfg.method,
        "--formula",
        "true" if cfg.formula else "false",
        "--table",
        "true" if cfg.table else "false",
        "--image-analysis",
        "true" if cfg.image_analysis else "false",
    ]
    return cmd


def ensure_cuda_path_configured(env: dict[str, str]) -> None:
    """
    Ensure CUDA_PATH environment variable is configured for lmdeploy on Windows.

    If CUDA_PATH is not set in the environment or its bin directory is missing,
    detects PyTorch's bundled CUDA runtime DLLs and provisions a junction
    in .tools/cuda/bin to satisfy lmdeploy's turbomind bootstrap requirement.
    """
    if os.name != "nt":
        return

    current = env.get("CUDA_PATH") or os.environ.get("CUDA_PATH")
    if current and (Path(current) / "bin").is_dir():
        env["CUDA_PATH"] = current
        return

    try:
        import subprocess

        import torch

        torch_lib = Path(torch.__file__).parent / "lib"
        if torch_lib.is_dir() and any(torch_lib.glob("cudart*.dll")):
            tools_cuda = Path(".tools/cuda").resolve()
            tools_bin = tools_cuda / "bin"
            tools_cuda.mkdir(parents=True, exist_ok=True)
            if not tools_bin.exists():
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(tools_bin), str(torch_lib.resolve())],
                    check=False,
                    capture_output=True,
                )
            if tools_bin.is_dir():
                env["CUDA_PATH"] = str(tools_cuda)
                logger.info("Configured fallback CUDA_PATH for lmdeploy: %s", tools_cuda)
    except Exception as e:
        logger.debug("Failed to auto-configure CUDA_PATH from PyTorch: %s", e)


def execute_mineru(
    source_pdf: Path,
    raw_output_dir: Path,
    cfg: MinerUConfig,
    log_file: Path | None = None,
) -> None:
    """
    Execute MinerU with local models and frozen parameters.

    Raises MinerUError on failure.
    """
    verify_cuda_available()

    raw_output_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_mineru_command(source_pdf, raw_output_dir, cfg)

    env = dict(os.environ)
    env["MINERU_MODEL_SOURCE"] = cfg.model_source
    ensure_cuda_path_configured(env)

    logger.info("Executing MinerU CLI on %s...", source_pdf.name)
    logger.debug("MinerU command: %s", cmd)

    res = run_command(
        cmd,
        cwd=raw_output_dir,
        env=env,
        check=False,
        log_output=True,
    )

    if res.exit_code != 0:
        logger.error("MinerU process failed with exit code %d", res.exit_code)
        raise MinerUError(
            f"MinerU execution failed with exit code {res.exit_code}.\n"
            f"Raw output preserved at: {raw_output_dir}\n"
            f"Stderr: {res.stderr.strip()}",
            details={"cmd": cmd, "exit_code": res.exit_code, "stderr": res.stderr},
        )

    logger.info("MinerU execution finished successfully.")
