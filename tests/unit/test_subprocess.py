"""Unit tests for subprocess wrapper."""

import sys
from pathlib import Path

import pytest

from book2epub.errors import SubprocessError
from book2epub.util.subprocess import redact_command, run_command


def test_subprocess_harmless_python_call() -> None:
    res = run_command([sys.executable, "-c", "print('hello from python')"])
    assert res.exit_code == 0
    assert "hello from python" in res.stdout


def test_subprocess_windows_path_with_spaces(tmp_path: Path) -> None:
    # Create directory with spaces
    spaced_dir = tmp_path / "folder with spaces" / "sub dir"
    spaced_dir.mkdir(parents=True)
    script_file = spaced_dir / "my test script.py"
    script_file.write_text("import sys\nprint(f'ARG:{sys.argv[1]}')", encoding="utf-8")

    arg_with_spaces = "argument with spaces and 'quotes'"
    res = run_command([sys.executable, str(script_file), arg_with_spaces], check=True)
    assert res.exit_code == 0
    assert f"ARG:{arg_with_spaces}" in res.stdout


def test_subprocess_error_raised_when_check_true() -> None:
    with pytest.raises(SubprocessError) as exc_info:
        run_command([sys.executable, "-c", "import sys; sys.exit(42)"], check=True)
    assert exc_info.value.exit_code == 42


def test_subprocess_redaction() -> None:
    raw_cmd = ["tool", "--api-key=secret12345", "--password=mypass", "normal_arg"]
    redacted = redact_command(raw_cmd)
    assert redacted[0] == "tool"
    assert "secret12345" not in redacted[1]
    assert "mypass" not in redacted[2]
    assert redacted[3] == "normal_arg"
