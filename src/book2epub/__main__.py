"""Package entry point for python -m book2epub."""

import sys

from book2epub.cli import app
from book2epub.errors import Book2EpubError
from book2epub.logging import error_console


def main() -> None:
    try:
        app()
    except Book2EpubError as e:
        stage_str = f"[{e.stage}] " if e.stage else ""
        error_console.print(f"[bold red]Error: {stage_str}{e.message}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
