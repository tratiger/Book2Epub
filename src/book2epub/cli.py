"""Command Line Interface (CLI) for Book2Epub."""

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from book2epub.config import AppConfig, JobConfig, MetadataConfig, MinerUConfig, RenderConfig
from book2epub.doctor import print_doctor_report, run_doctor_checks
from book2epub.logging import configure_logging, console, error_console
from book2epub.mineru.inspect import print_inspect_report
from book2epub.package.models import PackagingResult
from book2epub.package.validator import run_epubcheck
from book2epub.paths import get_epubcheck_jar_path
from book2epub.pipeline import run_from_middle, run_pipeline
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

    result = run_pipeline(
        input_dir=input_dir,
        output_epub=output,
        cfg=job_cfg,
        force_mineru=force_mineru,
    )
    print_conversion_summary(result)


def print_conversion_summary(result: PackagingResult) -> None:
    """Print standard conversion completion summary to console."""
    console.print()
    console.print("[bold green]Conversion completed successfully![/bold green]")

    table = Table(title="Book2Epub Conversion Summary", show_header=False)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Output Path", str(result.epub_path))
    table.add_row(
        "EPUB File Size",
        f"{result.file_size_bytes:,} bytes ({result.file_size_bytes / (1024 * 1024):.2f} MB)",
    )
    table.add_row("Source Page Count", str(result.source_page_count))
    table.add_row("XHTML Part Count", str(result.xhtml_part_count))
    table.add_row("Figure Count", str(result.figure_count))
    table.add_row("Chart Count", str(result.chart_count))
    table.add_row("Table Count", str(result.table_count))
    table.add_row("Code Blocks", str(result.code_count))
    table.add_row("Math Formulas", str(result.math_count))
    table.add_row("Fallbacks Used", str(result.fallback_count))
    table.add_row("Warnings Count", str(result.warning_count))
    table.add_row("EPUBCheck Result", "[bold green]EPUBCheck PASS[/bold green]")
    table.add_row("QA Report Path", str(result.qa_report_path or "N/A"))

    console.print(table)


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
    app_cfg = AppConfig(
        work_dir=work_dir,
        strict=strict,
        logging_level="DEBUG" if verbose else "INFO",
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
        render=RenderConfig(language=language),
        metadata=meta_cfg,
    )

    result = run_from_middle(
        middle_json=middle_json,
        output_epub=output,
        cfg=job_cfg,
    )
    print_conversion_summary(result)


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
    strict: Annotated[
        bool,
        typer.Option("--strict/--no-strict", help="Fail on warnings."),
    ] = True,
) -> None:
    """Validate an EPUB file using internal checks and EPUBCheck 5.3.0."""
    jar_path = get_epubcheck_jar_path(tools_dir)
    console.print(f"[bold]Validating EPUB:[/] {epub_file}")
    report = run_epubcheck(epub_file, epubcheck_jar=jar_path, fail_on_warnings=strict)

    table = Table(title="Validation Summary", show_header=False)
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("EPUB File", str(epub_file))
    table.add_row("EPUBCheck Exit Code", str(report.epubcheck_exit_code))
    table.add_row("Fatal Issues", str(report.fatal_count))
    table.add_row("Errors", str(report.error_count))
    table.add_row("Warnings", str(report.warning_count))
    table.add_row("Info Notices", str(report.info_count))

    if report.is_valid:
        table.add_row("Overall Status", "[bold green]PASS[/bold green]")
        console.print(table)
        raise typer.Exit(code=0)
    else:
        table.add_row("Overall Status", "[bold red]FAIL[/bold red]")
        console.print(table)
        error_console.print()
        error_console.print("[bold red]Validation Issues:[/bold red]")
        for issue in report.issues:
            loc_str = f" ({issue.location})" if issue.location else ""
            if issue.severity in ("FATAL", "ERROR"):
                error_console.print(f"  [red][{issue.severity}][/red] {issue.message}{loc_str}")
            elif issue.severity == "WARNING":
                error_console.print(
                    f"  [yellow][{issue.severity}][/yellow] {issue.message}{loc_str}"
                )
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
