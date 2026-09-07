"""Inspection and metric extraction for MinerU middle.json."""

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table

from book2epub.logging import console
from book2epub.mineru.validate import verify_referenced_images_exist

logger = logging.getLogger(__name__)


def analyze_middle_json(middle_json_path: Path) -> dict[str, Any]:
    """Analyze a middle.json and compute structural metrics."""
    with middle_json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    version_name = data.get("_version_name", "unknown")
    backend = data.get("_backend", "unknown")
    effort = data.get("_effort", "unknown")

    pdf_info: list[dict[str, Any]] = data.get("pdf_info", [])
    page_count = len(pdf_info)

    page_sizes: Counter[str] = Counter()
    para_block_types: Counter[str] = Counter()
    discarded_block_types: Counter[str] = Counter()
    span_types: Counter[str] = Counter()

    titles_with_level = 0
    titles_without_level = 0

    def _walk_spans(block: dict[str, Any]) -> None:
        nonlocal titles_with_level, titles_without_level
        btype = block.get("type", "unknown")
        para_block_types[btype] += 1

        if btype == "title":
            if "level" in block and block["level"] is not None:
                titles_with_level += 1
            else:
                titles_without_level += 1

        # Check lines / spans or nested blocks
        lines = block.get("lines", [])
        for line in lines:
            for span in line.get("spans", []):
                stype = span.get("type", "unknown")
                span_types[stype] += 1

        # Check blocks inside (e.g. image_body, caption, code_body)
        nested_blocks = block.get("blocks", [])
        for nb in nested_blocks:
            _walk_spans(nb)

    for page in pdf_info:
        size = page.get("page_size", [])
        size_str = f"{size[0]}x{size[1]}" if len(size) >= 2 else "unknown"
        page_sizes[size_str] += 1

        for pb in page.get("para_blocks", []):
            _walk_spans(pb)

        for db in page.get("discarded_blocks", []):
            db_type = db.get("type", "unknown")
            discarded_block_types[db_type] += 1

    total_images, missing_images = verify_referenced_images_exist(middle_json_path, data)

    return {
        "version_name": version_name,
        "backend": backend,
        "effort": effort,
        "page_count": page_count,
        "page_sizes": dict(page_sizes),
        "para_block_types": dict(para_block_types),
        "discarded_block_types": dict(discarded_block_types),
        "span_types": dict(span_types),
        "total_referenced_images": total_images,
        "missing_images_count": len(missing_images),
        "missing_images": missing_images,
        "titles_with_level": titles_with_level,
        "titles_without_level": titles_without_level,
    }


def print_inspect_report(middle_json_path: Path) -> None:
    """Print a Rich-formatted inspection report for a MinerU middle.json file."""
    metrics = analyze_middle_json(middle_json_path)

    title = f"MinerU Middle JSON Inspection: {middle_json_path.name}"
    console.print(
        Panel.fit(
            f"[bold cyan]MinerU Version:[/bold cyan] {metrics['version_name']}\n"
            f"[bold cyan]Backend:[/bold cyan] {metrics['backend']}   "
            f"[bold cyan]Effort:[/bold cyan] {metrics['effort']}\n"
            f"[bold cyan]Total Pages:[/bold cyan] {metrics['page_count']}\n"
            f"[bold cyan]Referenced Images:[/bold cyan] {metrics['total_referenced_images']} "
            f"(Missing: {metrics['missing_images_count']})\n"
            f"[bold cyan]Titles With Level:[/bold cyan] {metrics['titles_with_level']}  |  "
            f"[bold cyan]Without Level:[/bold cyan] {metrics['titles_without_level']}",
            title=title,
        )
    )

    # Tables
    p_table = Table(title="Page Size Distribution", show_header=True)
    p_table.add_column("Dimensions (WxH)")
    p_table.add_column("Pages", justify="right")
    for size, count in metrics["page_sizes"].items():
        p_table.add_row(size, str(count))
    console.print(p_table)

    b_table = Table(title="Para Blocks Distribution", show_header=True)
    b_table.add_column("Block Type")
    b_table.add_column("Count", justify="right")
    for btype, count in metrics["para_block_types"].items():
        b_table.add_row(btype, str(count))
    console.print(b_table)

    d_table = Table(title="Discarded Blocks Distribution", show_header=True)
    d_table.add_column("Discarded Type")
    d_table.add_column("Count", justify="right")
    for dtype, count in metrics["discarded_block_types"].items():
        d_table.add_row(dtype, str(count))
    console.print(d_table)

    s_table = Table(title="Span Types Distribution", show_header=True)
    s_table.add_column("Span Type")
    s_table.add_column("Count", justify="right")
    for stype, count in metrics["span_types"].items():
        s_table.add_row(stype, str(count))
    console.print(s_table)

    if metrics["missing_images"]:
        console.print(
            f"[bold red]Missing Image Assets ({metrics['missing_images_count']}):[/bold red]"
        )
        for missing in metrics["missing_images"][:10]:
            console.print(f"  - {missing}")
        if len(metrics["missing_images"]) > 10:
            console.print(f"  ... and {len(metrics['missing_images']) - 10} more.")
