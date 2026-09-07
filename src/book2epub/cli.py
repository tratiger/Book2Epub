"""Command Line Interface (CLI) for Book2Epub."""

from pathlib import Path
from typing import Annotated

import typer

from book2epub.config import AppConfig, JobConfig, MetadataConfig, MinerUConfig, RenderConfig
from book2epub.doctor import print_doctor_report, run_doctor_checks
from book2epub.errors import NotImplementedStageError
from book2epub.logging import configure_logging, console, error_console
from book2epub.mineru.inspect import print_inspect_report
from book2epub.pipeline import run_pipeline
from book2epub.version import __version__

app = typer.Typer(
    name="book2epub",
    help="Reflowable EPUB 3.3 generator from technical book page images using MinerU middle.json.",
    no_args_is_help=True,
    add_completion=False,
)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"Book2Epub version: {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            help="Show the version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Book2Epub: technical book page images to reflowable EPUB 3.3."""


@app.command()
def doctor(
    work_dir: Annotated[
        Path,
        typer.Option(
            "--work-dir",
            help="Base working directory to check for write access.",
        ),
    ] = Path(".work"),
    tools_dir: Annotated[
        Path | None,
        typer.Option(
            "--tools-dir",
            help="Path to .tools directory where epubcheck is installed.",
        ),
    ] = None,
) -> None:
    """Check system environment, GPU acceleration, and dependencies."""
    configure_logging(level="INFO")
    results = run_doctor_checks(work_dir=work_dir, tools_dir=tools_dir)
    success = print_doctor_report(results)
    if not success:
        error_console.print(
            "[bold red]Doctor reported critical failures. "
            "Please fix the items marked [FAIL] above.[/bold red]"
        )
        raise typer.Exit(code=1)


@app.command()
def convert(
    input_dir: Annotated[
        Path,
        typer.Argument(
            help="Directory containing cleaned, rectified page images.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output",
            help="Target path for the generated .epub file.",
        ),
    ],
    title: Annotated[str | None, typer.Option("--title", help="Book title override.")] = None,
    author: Annotated[
        list[str] | None,
        typer.Option("--author", help="Book author (can be repeated)."),
    ] = None,
    language: Annotated[
        str,
        typer.Option("--language", help="BCP 47 language code or 'auto'."),
    ] = "auto",
    identifier: Annotated[
        str | None,
        typer.Option("--identifier", help="Book unique identifier (e.g. urn:uuid:...)."),
    ] = None,
    publisher: Annotated[
        str | None,
        typer.Option("--publisher", help="Book publisher."),
    ] = None,
    cover_image: Annotated[
        Path | None,
        typer.Option("--cover-image", help="Explicit cover image path."),
    ] = None,
    work_dir: Annotated[
        Path,
        typer.Option("--work-dir", help="Base working directory."),
    ] = Path(".work"),
    keep_work: Annotated[
        bool,
        typer.Option("--keep-work/--no-keep-work", help="Retain intermediate job files."),
    ] = True,
    force_mineru: Annotated[
        bool,
        typer.Option("--force-mineru", help="Force MinerU re-execution, bypassing stage cache."),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option("--strict/--no-strict", help="Fail on warnings from generated markup."),
    ] = True,
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Enable verbose debug logging."),
    ] = False,
    mineru_model_source: Annotated[
        str,
        typer.Option(
            "--mineru-model-source",
            help="MinerU model source (local, huggingface, modelscope).",
        ),
    ] = "local",
) -> None:
    """Convert a directory of page images into a reflowable EPUB 3.3."""
    app_cfg = AppConfig(
        work_dir=work_dir,
        strict=strict,
        logging_level="DEBUG" if verbose else "INFO",
    )
    mineru_cfg = MinerUConfig(
        model_source=mineru_model_source,  # type: ignore[arg-type]
    )
    meta_cfg = MetadataConfig(
        title=title,
        authors=author or [],
        language=language,
        identifier=identifier,
        publisher=publisher,
        cover_image=cover_image,
    )
    job_cfg = JobConfig(
        app=app_cfg,
        mineru=mineru_cfg,
        render=RenderConfig(language=language),
        metadata=meta_cfg,
    )

    run_pipeline(
        input_dir=input_dir,
        output_epub=output,
        cfg=job_cfg,
        force_mineru=force_mineru,
    )


@app.command()
def from_middle(
    middle_json: Annotated[
        Path,
        typer.Argument(
            help="Path to authoritative MinerU book_middle.json.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output",
            help="Target path for the generated .epub file.",
        ),
    ],
    title: Annotated[str | None, typer.Option("--title", help="Book title override.")] = None,
    author: Annotated[
        list[str] | None,
        typer.Option("--author", help="Book author (can be repeated)."),
    ] = None,
    language: Annotated[
        str,
        typer.Option("--language", help="BCP 47 language code or 'auto'."),
    ] = "auto",
    identifier: Annotated[
        str | None,
        typer.Option("--identifier", help="Book unique identifier."),
    ] = None,
    publisher: Annotated[
        str | None,
        typer.Option("--publisher", help="Book publisher."),
    ] = None,
    cover_image: Annotated[
        Path | None,
        typer.Option("--cover-image", help="Explicit cover image path."),
    ] = None,
    work_dir: Annotated[
        Path,
        typer.Option("--work-dir", help="Base working directory."),
    ] = Path(".work"),
    strict: Annotated[
        bool,
        typer.Option("--strict/--no-strict", help="Fail on warnings from generated markup."),
    ] = True,
    verbose: Annotated[
        bool,
        typer.Option("-v", "--verbose", help="Enable verbose debug logging."),
    ] = False,
) -> None:
    """Render EPUB directly from an existing MinerU middle.json without running OCR."""
    configure_logging(level="DEBUG" if verbose else "INFO")
    error_console.print(
        "[bold yellow]from-middle command is not yet implemented in M1.[/bold yellow]"
    )
    raise NotImplementedStageError("Milestone M1 does not implement from-middle yet.")


@app.command()
def inspect_middle(
    middle_json: Annotated[
        Path,
        typer.Argument(
            help="Path to MinerU middle.json to inspect.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
) -> None:
    """Inspect and display structural metrics of a MinerU middle.json file."""
    print_inspect_report(middle_json)


@app.command()
def validate(
    epub_file: Annotated[
        Path,
        typer.Argument(
            help="Path to .epub file to validate.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    tools_dir: Annotated[
        Path | None,
        typer.Option(
            "--tools-dir",
            help="Path to .tools directory where epubcheck is installed.",
        ),
    ] = None,
) -> None:
    """Validate an EPUB file using internal checks and EPUBCheck 5.3.0."""
    error_console.print(
        "[bold yellow]validate command is not yet implemented in M1.[/bold yellow]"
    )
    raise NotImplementedStageError("Milestone M1 does not implement validate yet.")


if __name__ == "__main__":
    app()
