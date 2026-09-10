"""Command Line Interface (CLI) for Book2Epub."""

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from book2epub.config import (
    AppConfig,
    JobConfig,
    MetadataConfig,
    MinerUConfig,
    OCRCorrectionConfig,
    PresentationConfig,
    RenderConfig,
    SemanticConfig,
    normalize_provider_alias,
    normalize_vision_alias,
)
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
    semantic_provider: Annotated[
        str | None,
        typer.Option(
            "--semantic-provider",
            help="Check specific semantic provider environment/reachability (e.g. ollama).",
        ),
    ] = None,
) -> None:
    """Check system environment, GPU acceleration, and dependencies."""
    configure_logging(level="INFO")
    results = run_doctor_checks(
        work_dir=work_dir,
        tools_dir=tools_dir,
        semantic_provider=semantic_provider,
    )
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
    semantic: Annotated[
        bool,
        typer.Option("--semantic/--no-semantic", help="Enable LLM semantic reconstruction."),
    ] = False,
    semantic_provider: Annotated[
        str,
        typer.Option(
            "--semantic-provider",
            help="Semantic provider: ollama, openai, google, anthropic (gemini aliases google).",
        ),
    ] = "ollama",
    semantic_model: Annotated[
        str | None,
        typer.Option("--semantic-model", help="Semantic model override."),
    ] = None,
    semantic_vision: Annotated[
        str,
        typer.Option(
            "--semantic-vision",
            help="Visual review policy: off, auto, on (always aliases on).",
        ),
    ] = "auto",
    allow_cloud: Annotated[
        bool,
        typer.Option("--allow-cloud", help="Allow external cloud provider API calls."),
    ] = False,
    ocr_correction: Annotated[
        str,
        typer.Option(
            "--ocr-correction",
            help="OCR correction mode (off, safe, all).",
        ),
    ] = "off",
    presentation: Annotated[
        str,
        typer.Option(
            "--presentation",
            help="Presentation style mode (legacy, enhanced, infer).",
        ),
    ] = "legacy",
    source_pdf: Annotated[
        Path | None,
        typer.Option(
            "--source-pdf",
            help="Explicit source PDF path for visual review/OCR.",
        ),
    ] = None,
    source_images_dir: Annotated[
        Path | None,
        typer.Option(
            "--source-images-dir",
            help="Explicit source page images directory for visual review/OCR.",
        ),
    ] = None,
    force_semantic: Annotated[
        bool,
        typer.Option("--force-semantic", help="Force re-running semantic reconstruction."),
    ] = False,
    force_visual: Annotated[
        bool,
        typer.Option("--force-visual", help="Force re-running visual arbitration and OCR."),
    ] = False,
    force_presentation: Annotated[
        bool,
        typer.Option("--force-presentation", help="Force re-running presentation style inference."),
    ] = False,
) -> None:
    """Convert a directory of page images into a reflowable EPUB 3.3."""
    app_cfg = AppConfig(
        work_dir=work_dir,
        strict=strict,
        logging_level="DEBUG" if verbose else "INFO",
        source_pdf=source_pdf,
        source_images_dir=source_images_dir,
        force_semantic=force_semantic,
        force_visual=force_visual,
        force_presentation=force_presentation,
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
    semantic_cfg = SemanticConfig(
        enabled=semantic,
        provider=normalize_provider_alias(semantic_provider),
        model=semantic_model,
        allow_cloud=allow_cloud,
        vision=normalize_vision_alias(semantic_vision),
    )
    ocr_cfg = OCRCorrectionConfig(
        mode=ocr_correction,  # type: ignore[arg-type]
    )
    pres_cfg = PresentationConfig(
        mode=presentation,  # type: ignore[arg-type]
    )
    job_cfg = JobConfig(
        app=app_cfg,
        mineru=mineru_cfg,
        render=RenderConfig(language=language),
        metadata=meta_cfg,
        semantic=semantic_cfg,
        ocr_correction=ocr_cfg,
        presentation=pres_cfg,
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
    table.add_row("Code/Preformatted Blocks", str(result.code_count))
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
    semantic: Annotated[
        bool,
        typer.Option("--semantic/--no-semantic", help="Enable LLM semantic reconstruction."),
    ] = False,
    semantic_provider: Annotated[
        str,
        typer.Option(
            "--semantic-provider",
            help="Semantic provider: ollama, openai, google, anthropic (gemini aliases google).",
        ),
    ] = "ollama",
    semantic_model: Annotated[
        str | None,
        typer.Option("--semantic-model", help="Semantic model override."),
    ] = None,
    semantic_vision: Annotated[
        str,
        typer.Option(
            "--semantic-vision",
            help="Visual review policy: off, auto, on (always aliases on).",
        ),
    ] = "auto",
    allow_cloud: Annotated[
        bool,
        typer.Option("--allow-cloud", help="Allow external cloud provider API calls."),
    ] = False,
    ocr_correction: Annotated[
        str,
        typer.Option(
            "--ocr-correction",
            help="OCR correction mode (off, safe, all).",
        ),
    ] = "off",
    presentation: Annotated[
        str,
        typer.Option(
            "--presentation",
            help="Presentation style mode (legacy, enhanced, infer).",
        ),
    ] = "legacy",
    source_pdf: Annotated[
        Path | None,
        typer.Option(
            "--source-pdf",
            help="Explicit source PDF path for visual review/OCR.",
        ),
    ] = None,
    source_images_dir: Annotated[
        Path | None,
        typer.Option(
            "--source-images-dir",
            help="Explicit source page images directory for visual review/OCR.",
        ),
    ] = None,
) -> None:
    """Render EPUB directly from an existing MinerU middle.json without running OCR."""
    app_cfg = AppConfig(
        work_dir=work_dir,
        strict=strict,
        logging_level="DEBUG" if verbose else "INFO",
        source_pdf=source_pdf,
        source_images_dir=source_images_dir,
    )
    meta_cfg = MetadataConfig(
        title=title,
        authors=author or [],
        language=language,
        identifier=identifier,
        publisher=publisher,
        cover_image=cover_image,
    )
    semantic_cfg = SemanticConfig(
        enabled=semantic,
        provider=normalize_provider_alias(semantic_provider),
        model=semantic_model,
        allow_cloud=allow_cloud,
        vision=normalize_vision_alias(semantic_vision),
    )
    ocr_cfg = OCRCorrectionConfig(
        mode=ocr_correction,  # type: ignore[arg-type]
    )
    pres_cfg = PresentationConfig(
        mode=presentation,  # type: ignore[arg-type]
    )
    job_cfg = JobConfig(
        app=app_cfg,
        render=RenderConfig(language=language),
        metadata=meta_cfg,
        semantic=semantic_cfg,
        ocr_correction=ocr_cfg,
        presentation=pres_cfg,
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


@app.command()
def evaluate(
    job_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to job workspace directory containing qa/report.json.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
) -> None:
    """Print structural preservation and semantic fidelity metrics for a conversion job."""
    report_json = job_dir / "qa" / "report.json"
    if not report_json.is_file():
        error_console.print(f"[bold red]QA report not found at {report_json}[/bold red]")
        raise typer.Exit(code=1)

    import json

    data = json.loads(report_json.read_text(encoding="utf-8"))
    metrics = data.get("metrics", {})

    table = Table(title=f"Structural Evaluation Metrics ({job_dir.name})", show_header=False)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Block Coverage", f"{metrics.get('block_coverage', 0) * 100:.2f}%")
    table.add_row("Math Semantic Rate", f"{metrics.get('math_semantic_rate', 0) * 100:.2f}%")
    table.add_row("Table Semantic Rate", f"{metrics.get('table_semantic_rate', 0) * 100:.2f}%")
    table.add_row("Code Text Rate", f"{metrics.get('code_text_rate', 0) * 100:.2f}%")
    table.add_row(
        "Caption Retention Rate",
        f"{metrics.get('caption_retention_rate', 0) * 100:.2f}%",
    )
    table.add_row(
        "Heading Level Known Rate",
        f"{metrics.get('heading_level_known_rate', 0) * 100:.2f}%",
    )
    table.add_row("Unknown Block Count", str(metrics.get("unknown_block_count", 0)))
    table.add_row(
        "Unknown Blocks / 100 Pages",
        f"{metrics.get('unknown_block_rate_per_100_pages', 0):.2f}",
    )
    table.add_row("EPUBCheck Errors", str(metrics.get("epubcheck_error_count", 0)))
    table.add_row("EPUBCheck Warnings", str(metrics.get("epubcheck_warning_count", 0)))

    console.print(table)

    sem = data.get("semantic_metrics")
    if sem:
        sem_tbl = Table(title="Semantic Reconstruction Metrics", show_header=False)
        sem_tbl.add_column("Metric", style="bold cyan")
        sem_tbl.add_column("Value", style="white")
        sem_tbl.add_row("Semantic Change Rate", f"{sem.get('semantic_change_rate', 0) * 100:.2f}%")
        sem_tbl.add_row("Auto-Apply Rate", f"{sem.get('semantic_auto_apply_rate', 0) * 100:.2f}%")
        sem_tbl.add_row("Conflict Rate", f"{sem.get('semantic_conflict_rate', 0) * 100:.2f}%")
        transitions = sem.get("type_transitions", {})
        if transitions:
            sem_tbl.add_row("Transitions", ", ".join(f"{k}: {v}" for k, v in transitions.items()))
        console.print()
        console.print(sem_tbl)

    pres = data.get("presentation_metrics")
    if pres:
        pres_tbl = Table(title="Presentation & Typography Metrics", show_header=False)
        pres_tbl.add_column("Metric", style="bold cyan")
        pres_tbl.add_column("Value", style="white")
        pres_tbl.add_row("Presentation Mode", str(pres.get("presentation_mode", "legacy")))
        pres_tbl.add_row("Duplicate List Markers", str(pres.get("list_duplicate_marker_count", 0)))
        comp_counts = pres.get("component_counts", {})
        if comp_counts:
            pres_tbl.add_row("Total Components", str(sum(comp_counts.values())))
        console.print()
        console.print(pres_tbl)


@app.command()
def compare(
    job_a: Annotated[
        Path,
        typer.Argument(
            help="Path to first job workspace directory.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
    job_b: Annotated[
        Path,
        typer.Argument(
            help="Path to second job workspace directory.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
) -> None:
    """Compare QA reports between two conversion jobs (M12 Section 15)."""
    report_a = job_a / "qa" / "report.json"
    report_b = job_b / "qa" / "report.json"

    if not report_a.is_file():
        error_console.print(f"[bold red]QA report not found at {report_a}[/bold red]")
        raise typer.Exit(code=1)
    if not report_b.is_file():
        error_console.print(f"[bold red]QA report not found at {report_b}[/bold red]")
        raise typer.Exit(code=1)

    from book2epub.qa.compare import compare_qa_reports, format_comparison_text

    diff = compare_qa_reports(report_a, report_b)
    console.print(format_comparison_text(diff))


if __name__ == "__main__":
    app()
