"""Structural quality checks and evaluation metrics for Book2Epub publications."""

import logging
from typing import Any

from book2epub.ir.models import (
    BookIR,
    Chart,
    DisplayMath,
    Figure,
    Heading,
    Table,
    UnknownBlock,
)
from book2epub.package.models import PackagingResult
from book2epub.qa.models import EvaluationMetrics, StructuralCheckResult
from book2epub.render.models import RenderResult

logger = logging.getLogger(__name__)

MEANINGFUL_SOURCE_TYPES = {
    "text",
    "title",
    "code",
    "table",
    "image",
    "chart",
    "equation_inline",
    "equation_interline",
    "algorithm",
}


def run_structural_checks(
    raw_middle_data: dict[str, Any],
    book_ir: BookIR,
    render_result: RenderResult,
    packaging_result: PackagingResult,
) -> tuple[list[StructuralCheckResult], EvaluationMetrics]:
    """
    Execute deterministic reconciliation checks comparing authoritative middle.json,
    normalized BookIR, rendered XHTML tree, and final EPUB validation results.
    """
    checks: list[StructuralCheckResult] = []

    # 1. Source blocks inspection
    source_blocks_count = 0
    source_meaningful_count = 0
    source_code_count = 0
    source_table_count = 0
    source_math_count = 0
    source_figure_count = 0
    source_captions_count = 0

    for page in raw_middle_data.get("pdf_info", []):
        for block in page.get("para_blocks", []):
            source_blocks_count += 1
            b_type = block.get("type", "")
            if b_type in MEANINGFUL_SOURCE_TYPES:
                source_meaningful_count += 1
            if b_type in ("code", "algorithm"):
                source_code_count += 1
            elif b_type == "table":
                source_table_count += 1
            elif b_type in ("equation_inline", "equation_interline", "isolated_formula"):
                source_math_count += 1
            elif b_type in ("image", "chart"):
                source_figure_count += 1
                if block.get("caption") or block.get("caption_list"):
                    source_captions_count += 1

    # Also count inline equations inside text lines
    for page in raw_middle_data.get("pdf_info", []):
        for block in page.get("para_blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("type") in ("inline_equation", "equation_inline"):
                        source_math_count += 1

    # 2. Target counts from BookIR and RenderResult
    ir_captions_count = sum(
        1 for b in book_ir.blocks if isinstance(b, (Figure, Chart, Table)) and b.caption
    )
    ir_math_display = sum(1 for b in book_ir.blocks if isinstance(b, DisplayMath))
    ir_unknown_count = sum(1 for b in book_ir.blocks if isinstance(b, UnknownBlock))
    ir_headings = [b for b in book_ir.blocks if isinstance(b, Heading)]

    # Heading hierarchy check
    heading_jumps_warning = False
    prev_level = 1
    for h in ir_headings:
        lvl = h.level or 1
        if lvl - prev_level > 1 and prev_level > 0:
            heading_jumps_warning = True
        prev_level = lvl

    # Check 1: Content Loss Check
    meaningful_ir_count = len(book_ir.blocks) - ir_unknown_count
    content_loss_passed = (
        meaningful_ir_count >= source_meaningful_count * 0.7 or source_meaningful_count == 0
    )
    checks.append(
        StructuralCheckResult(
            name="Content-Loss Check",
            passed=content_loss_passed,
            source_count=source_meaningful_count,
            target_count=meaningful_ir_count,
            details=f"Mapped {meaningful_ir_count} blocks from {source_meaningful_count} source.",
        )
    )

    # Check 2: Math Reconciliation Check
    math_target_count = render_result.math_count
    # Pass if target math encompasses source equations or fallbacks
    math_passed = (math_target_count >= ir_math_display) or (source_math_count == 0)
    checks.append(
        StructuralCheckResult(
            name="Math Reconciliation Check",
            passed=math_passed,
            source_count=source_math_count,
            target_count=math_target_count,
            details=f"Rendered {math_target_count} math formulas (source: {source_math_count}).",
        )
    )

    # Check 3: Table Reconciliation Check
    table_passed = render_result.table_count >= source_table_count
    checks.append(
        StructuralCheckResult(
            name="Table Reconciliation Check",
            passed=table_passed,
            source_count=source_table_count,
            target_count=render_result.table_count,
            details=f"Rendered {render_result.table_count} tables (source: {source_table_count}).",
        )
    )

    # Check 4: Code Reconciliation Check
    code_passed = render_result.code_count >= source_code_count
    checks.append(
        StructuralCheckResult(
            name="Code Reconciliation Check",
            passed=code_passed,
            source_count=source_code_count,
            target_count=render_result.code_count,
            details=f"Rendered {render_result.code_count} code (source: {source_code_count}).",
        )
    )

    # Check 5: Heading Hierarchy Check
    heading_passed = (
        all(1 <= (h.level or 1) <= 6 for h in ir_headings) and not heading_jumps_warning
    )
    checks.append(
        StructuralCheckResult(
            name="Heading Hierarchy Check",
            passed=heading_passed,
            source_count=len(ir_headings),
            target_count=len(render_result.manifest.toc),
            details=(
                "Heading levels valid (1..6) and no gap jumps."
                if heading_passed
                else "Headings contained level jumps > 1 or invalid levels."
            ),
        )
    )

    # 3. Compute Standard Evaluation Metrics
    total_pages = max(1, len(raw_middle_data.get("pdf_info", [])))
    block_coverage = (
        min(1.0, meaningful_ir_count / source_meaningful_count)
        if source_meaningful_count > 0
        else 1.0
    )
    successful_math = render_result.math_count - render_result.fallback_count
    math_semantic_rate = (
        min(1.0, successful_math / render_result.math_count)
        if render_result.math_count > 0
        else 1.0
    )
    table_semantic_rate = (
        min(1.0, render_result.table_count / max(1, source_table_count))
        if source_table_count > 0
        else 1.0
    )
    code_text_rate = (
        min(1.0, render_result.code_count / max(1, source_code_count))
        if source_code_count > 0
        else 1.0
    )
    caption_retention = (
        min(1.0, ir_captions_count / max(1, source_captions_count))
        if source_captions_count > 0
        else 1.0
    )
    known_headings = sum(1 for h in ir_headings if h.level is not None)
    heading_rate = known_headings / max(1, len(ir_headings)) if ir_headings else 1.0

    metrics = EvaluationMetrics(
        block_coverage=round(block_coverage, 4),
        math_semantic_rate=round(math_semantic_rate, 4),
        table_semantic_rate=round(table_semantic_rate, 4),
        code_text_rate=round(code_text_rate, 4),
        caption_retention_rate=round(caption_retention, 4),
        heading_level_known_rate=round(heading_rate, 4),
        unknown_block_count=ir_unknown_count,
        unknown_block_rate_per_100_pages=round((ir_unknown_count / total_pages) * 100, 2),
        epubcheck_error_count=packaging_result.validation_report.error_count,
        epubcheck_warning_count=packaging_result.validation_report.warning_count,
    )

    return checks, metrics
