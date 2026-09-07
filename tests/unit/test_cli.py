"""Unit tests for CLI commands and help."""

from typer.testing import CliRunner

from book2epub.cli import app

runner = CliRunner()


def test_cli_help_returns_exit_code_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "book2epub" in result.output.lower()
    assert "convert" in result.output
    assert "doctor" in result.output
    assert "from-middle" in result.output
    assert "inspect-middle" in result.output
    assert "validate" in result.output


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "Book2Epub version:" in result.output


def test_cli_convert_help() -> None:
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--output" in result.output
    assert "--force-mineru" in result.output
