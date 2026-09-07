"""Subprocess execution wrapper adhering to Book2Epub security and logging rules."""

import logging
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from book2epub.errors import SubprocessError

logger = logging.getLogger(__name__)

# Patterns for sensitive arguments that should be redacted from logs
_SECRET_PATTERNS = [
    re.compile(r"(password|token|secret|key|auth)[=:]\S+", re.IGNORECASE),
]


def redact_command(cmd: list[str]) -> list[str]:
    """Return a copy of the command arguments with sensitive values redacted."""
    redacted: list[str] = []
    for arg in cmd:
        cleaned = arg
        for pattern in _SECRET_PATTERNS:
            cleaned = pattern.sub(r"\1=***", cleaned)
        redacted.append(cleaned)
    return redacted


@dataclass(frozen=True)
class SubprocessResult:
    """Typed result of a subprocess execution."""

    cmd: list[str]
    exit_code: int
    stdout: str
    stderr: str


def run_command(
    cmd: list[str | Path],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = False,
    log_output: bool = False,
    custom_logger: logging.Logger | None = None,
    timeout: float | None = None,
) -> SubprocessResult:
    """
    Execute an external command as a child process.

    Rules:
    - accepts list[str | Path], never a shell command string.
    - shell=False is always enforced.
    - logs command with secrets redacted.
    - returns a typed SubprocessResult.
    - raises SubprocessError if check=True and exit code is nonzero.
    - properly handles Windows path spaces via standard argument passing.
    """
    cmd_str = [str(arg) for arg in cmd]
    log = custom_logger or logger
    safe_cmd = redact_command(cmd_str)

    log.debug("Executing external command: %s (cwd=%s)", safe_cmd, cwd)

    try:
        proc = subprocess.run(
            cmd_str,
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env is not None else None,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as e:
        log.error("Failed to spawn process %s: %s", safe_cmd, e)
        raise SubprocessError(
            message=f"Failed to spawn command '{safe_cmd[0]}': {e}",
            cmd=cmd_str,
            exit_code=-1,
            stdout="",
            stderr=str(e),
        ) from e

    stdout = proc.stdout
    stderr = proc.stderr
    exit_code = proc.returncode

    if log_output:
        if stdout:
            log.debug("Command stdout:\n%s", stdout.rstrip())
        if stderr:
            log.debug("Command stderr:\n%s", stderr.rstrip())

    if check and exit_code != 0:
        log.error(
            "Command %s exited with non-zero code %d.\nStderr: %s",
            safe_cmd,
            exit_code,
            stderr.strip(),
        )
        raise SubprocessError(
            message=f"Command '{safe_cmd[0]}' failed with exit code {exit_code}",
            cmd=cmd_str,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )

    return SubprocessResult(
        cmd=cmd_str,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )
