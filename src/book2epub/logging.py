"""Logging configuration with Rich console output and clean file logging."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console()
error_console = Console(stderr=True)


class UtcIsoFormatter(logging.Formatter):
    """Formatter that outputs ISO 8601 UTC timestamps without ANSI codes."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        return dt.isoformat()


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
) -> None:
    """Configure root logger with RichHandler for console and optional plain file handler."""
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to allow reconfiguration
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # Console handler using Rich
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    rich_handler.setLevel(numeric_level)
    root_logger.addHandler(rich_handler)

    # File handler if log_file is provided
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_formatter = UtcIsoFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(name)
