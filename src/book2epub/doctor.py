"""Diagnostic and environment verification for Book2Epub ('doctor' command)."""

import os
import platform
import shutil
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rich.table import Table

from book2epub.logging import console
from book2epub.paths import get_epubcheck_jar_path
from book2epub.util.subprocess import run_command


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"


@dataclass(frozen=True)
class CheckResult:
    """Individual diagnostic check result."""

    name: str
    status: CheckStatus
    message: str
    recommendation: str | None = None

    def formatted_line(self) -> str:
        rec = f" -> {self.recommendation}" if self.recommendation else ""
        return f"[{self.status.value}] {self.name}: {self.message}{rec}"


def check_platform() -> CheckResult:
    is_win = sys.platform == "win32"
    arch = platform.machine().lower()
    is_x64 = arch in ("amd64", "x86_64")
    if is_win and is_x64:
        return CheckResult("Platform", CheckStatus.PASS, f"Windows x64 ({platform.platform()})")
    return CheckResult(
        "Platform",
        CheckStatus.FAIL,
        f"Unsupported platform: {sys.platform} {arch}",
        recommendation="Book2Epub requires Windows 11 x64 native.",
    )


def check_python_version() -> CheckResult:
    v = sys.version_info
    if v.major == 3 and v.minor == 12:
        return CheckResult(
            "Python Version", CheckStatus.PASS, f"Python {v.major}.{v.minor}.{v.micro}"
        )
    return CheckResult(
        "Python Version",
        CheckStatus.FAIL,
        f"Python {v.major}.{v.minor}.{v.micro} is active",
        recommendation="Book2Epub strictly requires Python 3.12.x.",
    )


def check_uv() -> CheckResult:
    uv_bin = shutil.which("uv")
    if not uv_bin:
        return CheckResult(
            "uv Executable",
            CheckStatus.FAIL,
            "uv not found on PATH",
            recommendation="Install uv: https://docs.astral.sh/uv/",
        )
    res = run_command(["uv", "--version"])
    if res.exit_code == 0:
        return CheckResult("uv Executable", CheckStatus.PASS, res.stdout.strip())
    return CheckResult(
        "uv Executable",
        CheckStatus.FAIL,
        f"uv failed with exit code {res.exit_code}: {res.stderr.strip()}",
    )


def check_mineru_version() -> CheckResult:
    mineru_bin = shutil.which("mineru")
    if not mineru_bin:
        res = run_command([sys.executable, "-m", "mineru.cli", "--version"])
        if res.exit_code != 0:
            return CheckResult(
                "MinerU Version",
                CheckStatus.FAIL,
                "MinerU 3.4.5 is not installed",
                recommendation='Run: uv pip install -U "mineru[all]==3.4.5"',
            )
    else:
        res = run_command(["mineru", "--version"])

    out = (res.stdout + " " + res.stderr).strip()
    if "3.4.5" in out:
        return CheckResult("MinerU Version", CheckStatus.PASS, f"MinerU 3.4.5 ({out})")
    return CheckResult(
        "MinerU Version",
        CheckStatus.FAIL,
        f"Installed MinerU version mismatch: {out}",
        recommendation='Install exactly version 3.4.5: uv pip install -U "mineru[all]==3.4.5"',
    )


def check_nvidia_smi() -> tuple[CheckResult, str]:
    smi_bin = shutil.which("nvidia-smi")
    if not smi_bin:
        return (
            CheckResult(
                "NVIDIA GPU (nvidia-smi)",
                CheckStatus.FAIL,
                "nvidia-smi not found on PATH",
                recommendation="Install NVIDIA drivers for your GPU.",
            ),
            "",
        )
    res = run_command(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if res.exit_code == 0:
        gpu_name = res.stdout.strip()
        return (
            CheckResult("NVIDIA GPU (nvidia-smi)", CheckStatus.PASS, f"Detected: {gpu_name}"),
            gpu_name,
        )
    return (
        CheckResult(
            "NVIDIA GPU (nvidia-smi)",
            CheckStatus.FAIL,
            f"nvidia-smi error: {res.stderr.strip()}",
        ),
        "",
    )


def check_torch_cuda() -> CheckResult:
    code = "import torch; print(torch.cuda.is_available())"
    res = run_command([sys.executable, "-c", code])
    if res.exit_code == 0 and "True" in res.stdout:
        return CheckResult("PyTorch CUDA", CheckStatus.PASS, "torch.cuda.is_available() is True")
    err = res.stderr.strip() or res.stdout.strip()
    return CheckResult(
        "PyTorch CUDA",
        CheckStatus.FAIL,
        f"CUDA acceleration not available in PyTorch: {err}",
        recommendation=(
            "Install PyTorch with CUDA: "
            "uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128"
        ),
    )


def check_torch_cuda_version() -> CheckResult:
    code = "import torch; print(torch.version.cuda)"
    res = run_command([sys.executable, "-c", code])
    if res.exit_code == 0 and res.stdout.strip() != "None":
        cuda_ver = res.stdout.strip()
        return CheckResult("PyTorch CUDA Version", CheckStatus.PASS, f"CUDA Runtime: {cuda_ver}")
    return CheckResult(
        "PyTorch CUDA Version",
        CheckStatus.FAIL,
        f"PyTorch CUDA version is None or not available: {res.stderr.strip()}",
        recommendation="Install PyTorch cu128 wheels for RTX 50-series.",
    )


def check_lmdeploy_blackwell(gpu_name: str) -> CheckResult:
    is_blackwell = any(kw in gpu_name for kw in ("5070", "5080", "5090", "Blackwell", "50-Series"))
    code = "import lmdeploy; print(getattr(lmdeploy, '__version__', 'available'))"
    res = run_command([sys.executable, "-c", code])
    if res.exit_code == 0:
        ver = res.stdout.strip()
        return CheckResult(
            "lmdeploy (Blackwell acceleration)",
            CheckStatus.PASS,
            f"lmdeploy import successful ({ver})",
        )

    if is_blackwell:
        return CheckResult(
            "lmdeploy (Blackwell acceleration)",
            CheckStatus.FAIL,
            f"Failed to import lmdeploy on Blackwell GPU: {res.stderr.strip()}",
            recommendation="Install lmdeploy 0.11.1+cu128 wheel as specified in scripts/setup.ps1",
        )
    return CheckResult(
        "lmdeploy (Blackwell acceleration)",
        CheckStatus.PASS,
        "Not running on Blackwell RTX 50-series; lmdeploy wheel optional.",
    )


def check_java() -> CheckResult:
    java_bin = shutil.which("java")
    if not java_bin:
        return CheckResult(
            "Java Runtime",
            CheckStatus.FAIL,
            "java not found on PATH",
            recommendation="Install Java 11+ or OpenJDK to run EPUBCheck.",
        )
    res = run_command(["java", "-version"])
    combined = (res.stdout + " " + res.stderr).strip()
    if res.exit_code == 0:
        first_line = combined.splitlines()[0] if combined else "Available"
        return CheckResult("Java Runtime", CheckStatus.PASS, first_line)
    return CheckResult(
        "Java Runtime",
        CheckStatus.FAIL,
        f"java command failed: {res.stderr.strip()}",
    )


def check_epubcheck_jar(tools_dir: Path | None = None) -> CheckResult:
    jar_path = get_epubcheck_jar_path(tools_dir)
    if jar_path.is_file():
        size_mb = jar_path.stat().st_size / (1024 * 1024)
        return CheckResult(
            "EPUBCheck Jar",
            CheckStatus.PASS,
            f"Found {jar_path} ({size_mb:.2f} MB)",
        )
    return CheckResult(
        "EPUBCheck Jar",
        CheckStatus.FAIL,
        f"EPUBCheck 5.3.0 jar not found at {jar_path}",
        recommendation=r"Run: .\scripts\download_epubcheck.ps1",
    )


def check_epubcheck_version(tools_dir: Path | None = None) -> CheckResult:
    jar_path = get_epubcheck_jar_path(tools_dir)
    if not jar_path.is_file():
        return CheckResult(
            "EPUBCheck Execution",
            CheckStatus.FAIL,
            "Cannot verify EPUBCheck execution because epubcheck.jar is missing",
            recommendation=r"Run: .\scripts\download_epubcheck.ps1",
        )
    res = run_command(["java", "-jar", str(jar_path), "--version"])
    combined = (res.stdout + " " + res.stderr).strip()
    if res.exit_code == 0 and "5.3.0" in combined:
        return CheckResult("EPUBCheck Execution", CheckStatus.PASS, combined)
    if res.exit_code == 0:
        return CheckResult(
            "EPUBCheck Execution",
            CheckStatus.FAIL,
            f"EPUBCheck version mismatch (expected 5.3.0): {combined}",
            recommendation="Download and use EPUBCheck 5.3.0.",
        )
    return CheckResult(
        "EPUBCheck Execution",
        CheckStatus.FAIL,
        f"EPUBCheck execution failed: {res.stderr.strip()}",
    )


def check_work_dir_writable(work_dir: Path) -> CheckResult:
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=work_dir, delete=True) as tmp:
            tmp.write(b"ok")
        return CheckResult("Work Directory", CheckStatus.PASS, f"Writable: {work_dir.resolve()}")
    except Exception as e:
        return CheckResult(
            "Work Directory",
            CheckStatus.FAIL,
            f"Cannot write to work directory {work_dir}: {e}",
            recommendation=f"Ensure write permissions for {work_dir}",
        )


def check_mineru_model_source() -> CheckResult:
    val = os.environ.get("MINERU_MODEL_SOURCE")
    if val == "local":
        return CheckResult("MINERU_MODEL_SOURCE", CheckStatus.PASS, "Set to 'local'")
    if val is None:
        return CheckResult(
            "MINERU_MODEL_SOURCE",
            CheckStatus.WARN,
            "Not set in environment (defaults to 'local' during Book2Epub conversion)",
            recommendation="Set $env:MINERU_MODEL_SOURCE = 'local' for normal offline conversion.",
        )
    return CheckResult(
        "MINERU_MODEL_SOURCE",
        CheckStatus.WARN,
        f"Set to '{val}' (normal offline conversion requires 'local')",
        recommendation="Set $env:MINERU_MODEL_SOURCE = 'local'",
    )


def check_provider_sdks() -> list[CheckResult]:
    """Check installed versions of optional provider SDKs."""
    import importlib.metadata

    packages = [
        ("ollama", "semantic-local"),
        ("openai", "semantic-openai"),
        ("google-genai", "semantic-google"),
        ("anthropic", "semantic-anthropic"),
    ]
    results: list[CheckResult] = []
    for pkg, extra in packages:
        try:
            ver = importlib.metadata.version(pkg)
            results.append(
                CheckResult(
                    f"Provider SDK ({pkg})",
                    CheckStatus.PASS,
                    f"Installed version {ver}",
                )
            )
        except importlib.metadata.PackageNotFoundError:
            results.append(
                CheckResult(
                    f"Provider SDK ({pkg})",
                    CheckStatus.INFO,
                    f"Not installed (optional; install with: uv sync --extra {extra})",
                )
            )
    return results


def check_provider_env_keys() -> list[CheckResult]:
    """Check presence of provider API keys (SET / NOT SET, never printing value)."""
    env_keys = [
        ("OPENAI_API_KEY", "Required for OpenAI cloud provider (--allow-cloud)"),
        ("GEMINI_API_KEY", "Required for Google Gemini cloud provider (--allow-cloud)"),
        ("ANTHROPIC_API_KEY", "Required for Anthropic cloud provider (--allow-cloud)"),
        ("BOOK2EPUB_OLLAMA_HOST", "Optional host for Ollama (default http://localhost:11434)"),
    ]
    results: list[CheckResult] = []
    for key, desc in env_keys:
        val = os.environ.get(key)
        if val is not None and val.strip():
            results.append(
                CheckResult(
                    f"Provider Env ({key})",
                    CheckStatus.PASS,
                    "SET",
                )
            )
        else:
            results.append(
                CheckResult(
                    f"Provider Env ({key})",
                    CheckStatus.INFO,
                    f"NOT SET ({desc})",
                )
            )
    return results


def check_ollama_reachable() -> CheckResult:
    """Check if Ollama host is reachable (only executed if explicitly asked)."""
    import urllib.request

    host = os.environ.get("BOOK2EPUB_OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.Request(f"{host}/api/tags", headers={"User-Agent": "Book2Epub-Doctor"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                return CheckResult(
                    "Ollama Host Reachability",
                    CheckStatus.PASS,
                    f"Reachable at {host}",
                )
            return CheckResult(
                "Ollama Host Reachability",
                CheckStatus.WARN,
                f"Responded with HTTP {resp.status} at {host}",
            )
    except Exception as exc:
        return CheckResult(
            "Ollama Host Reachability",
            CheckStatus.WARN,
            f"Cannot connect to {host}: {exc}",
            recommendation="Start Ollama service: ollama serve",
        )


def run_doctor_checks(
    work_dir: Path = Path(".work"),
    tools_dir: Path | None = None,
    semantic_provider: str | None = None,
) -> list[CheckResult]:
    """Execute all diagnostic checks and return a list of CheckResults."""
    results: list[CheckResult] = []

    results.append(check_platform())
    results.append(check_python_version())
    results.append(check_uv())
    results.append(check_mineru_version())

    smi_result, gpu_name = check_nvidia_smi()
    results.append(smi_result)
    results.append(check_torch_cuda())
    results.append(check_torch_cuda_version())
    results.append(check_lmdeploy_blackwell(gpu_name))

    results.append(check_java())
    results.append(check_epubcheck_jar(tools_dir))
    results.append(check_epubcheck_version(tools_dir))

    results.append(check_work_dir_writable(work_dir))
    results.append(check_mineru_model_source())

    # Provider diagnostic checks (optional, non-failing)
    results.extend(check_provider_sdks())
    results.extend(check_provider_env_keys())
    if semantic_provider == "ollama":
        results.append(check_ollama_reachable())

    return results


def print_doctor_report(results: list[CheckResult]) -> bool:
    """Print a Rich table of doctor results. Return True if no FAIL statuses."""
    table = Table(title="Book2Epub Doctor Diagnostic Report", show_header=True)
    table.add_column("Status", width=8)
    table.add_column("Component", width=32)
    table.add_column("Details / Recommendation")

    has_fail = False
    for res in results:
        if res.status == CheckStatus.PASS:
            status_str = "[bold green]PASS[/bold green]"
        elif res.status == CheckStatus.WARN:
            status_str = "[bold yellow]WARN[/bold yellow]"
        elif res.status == CheckStatus.INFO:
            status_str = "[bold blue]INFO[/bold blue]"
        else:
            status_str = "[bold red]FAIL[/bold red]"
            has_fail = True

        detail = res.message
        if res.recommendation:
            detail += f"\n[dim yellow]Recommendation: {res.recommendation}[/dim yellow]"
        table.add_row(status_str, res.name, detail)

    console.print(table)

    console.print("\n[bold]MinerU Model Setup Reference:[/bold]")
    console.print("To download MinerU models for local offline conversion:")
    console.print("  [cyan]uv run mineru-models-download -s huggingface -m all[/cyan]")
    console.print("  or: [cyan]uv run mineru-models-download -s modelscope -m all[/cyan]\n")

    return not has_fail
