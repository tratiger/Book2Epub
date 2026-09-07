"""Conversion pipeline coordinating stages from Ingest through EPUB validation."""

import json
import logging
from pathlib import Path
from typing import Any

from book2epub.config import JobConfig
from book2epub.ingest.pdf import create_source_pdf
from book2epub.ingest.scanner import scan_and_validate_directory
from book2epub.ir.adapter import MiddleJsonAdapter
from book2epub.ir.models import BookIR, BookMetadata
from book2epub.ir.normalize import normalize_bookir
from book2epub.ir.serializer import save_bookir
from book2epub.logging import configure_logging
from book2epub.mineru.cache import (
    is_mineru_cache_valid,
    record_mineru_stage_complete,
    record_mineru_stage_failed,
)
from book2epub.mineru.canonical import canonicalize_mineru_output
from book2epub.mineru.discover import discover_middle_json
from book2epub.mineru.runner import execute_mineru
from book2epub.mineru.validate import (
    validate_middle_json_root,
    verify_referenced_images_exist,
)
from book2epub.package import EpubPackager, PackagingResult
from book2epub.paths import JobPaths, create_job_paths, get_epubcheck_jar_path
from book2epub.render import ReflowRenderer, RenderResult
from book2epub.util.hashing import compute_mineru_cache_key

logger = logging.getLogger(__name__)


def run_conversion_m1(
    input_dir: Path,
    cfg: JobConfig,
    force_mineru: bool = False,
    existing_paths: JobPaths | None = None,
) -> tuple[JobPaths, Path]:
    """
    Execute M1 (Ingest and MinerU execution) pipeline.

    Returns (job_paths, canonical_middle_json_path).
    """
    paths = existing_paths or create_job_paths(cfg.app.work_dir)
    configure_logging(level=cfg.app.logging_level, log_file=paths.log_file)

    logger.info("=== Starting Book2Epub Job: %s ===", paths.job_id)

    # 1. INGEST STAGE
    logger.info("[Stage 1/6] Ingesting and validating page images from %s...", input_dir)
    manifest = scan_and_validate_directory(input_dir, manifest_output_path=paths.manifest_file)
    logger.info("Ingest complete: %d pages validated.", manifest.total_pages)

    # 2. SOURCE PDF GENERATION
    logger.info("Generating lossless source PDF...")
    create_source_pdf(manifest, input_dir, paths.source_pdf_file)

    # 3. MINERU STAGE CACHE CHECK
    cache_key = compute_mineru_cache_key(
        file_hashes=[p.sha256 for p in manifest.pages],
        relative_names=[p.relative_path for p in manifest.pages],
        mineru_version=cfg.mineru.version,
        backend=cfg.mineru.backend,
        effort=cfg.mineru.effort,
        ocr=(cfg.mineru.method == "ocr"),
        formula=cfg.mineru.formula,
        table=cfg.mineru.table,
        image_analysis=cfg.mineru.image_analysis,
    )

    canonical_middle = paths.mineru_canonical_middle_json
    can_skip = not force_mineru and is_mineru_cache_valid(
        paths.mineru_stage_file, cache_key, canonical_middle
    )

    if can_skip:
        logger.info("[Stage 2/6] Skipping MinerU execution (cache hit).")
    else:
        logger.info("[Stage 2/6] Executing MinerU hybrid-engine...")
        try:
            execute_mineru(
                paths.source_pdf_file,
                paths.mineru_raw_dir,
                cfg.mineru,
                log_file=paths.log_file,
            )
            raw_middle = discover_middle_json(paths.mineru_raw_dir)

            with raw_middle.open("r", encoding="utf-8") as f:
                raw_data = json.load(f)

            validate_middle_json_root(raw_data, expected_page_count=manifest.total_pages)

            canonical_middle, _ = canonicalize_mineru_output(
                raw_middle,
                paths.mineru_canonical_dir,
            )

            # Check for referenced images
            _, missing_images = verify_referenced_images_exist(canonical_middle)
            if missing_images and cfg.app.strict:
                logger.warning(
                    "%d referenced images were missing in MinerU output: %s",
                    len(missing_images),
                    missing_images[:5],
                )

            record_mineru_stage_complete(
                paths.mineru_stage_file,
                cache_key=cache_key,
                mineru_version=cfg.mineru.version,
                backend=cfg.mineru.backend,
                canonical_middle_json=canonical_middle,
                page_count=manifest.total_pages,
            )
        except Exception:
            record_mineru_stage_failed(
                paths.mineru_stage_file,
                cache_key=cache_key,
                mineru_version=cfg.mineru.version,
                backend=cfg.mineru.backend,
            )
            raise

    logger.info("=== Milestone M1 Complete: canonical middle JSON at %s ===", canonical_middle)
    return paths, canonical_middle


def run_conversion_m2(
    canonical_middle_json: Path,
    paths: JobPaths,
    cfg: JobConfig,
) -> tuple[BookIR, BookIR]:
    """
    Execute M2 (Middle.json to normalized BookIR) pipeline.

    Writes:
      ir/bookir.raw.json
      ir/bookir.normalized.json

    Returns (raw_ir, normalized_ir).
    """
    logger.info("[Stage 3/6] Converting middle.json to BookIR...")

    with canonical_middle_json.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)

    # Extract raw page numbers from discarded_blocks
    raw_page_number_texts: list[str | None] = []
    for page in data.get("pdf_info", []):
        pn_texts: list[str] = []
        for db in page.get("discarded_blocks", []):
            if db.get("type") == "page_number":
                for line in db.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("content"):
                            pn_texts.append(span["content"])
        raw_page_number_texts.append(" ".join(pn_texts) if pn_texts else None)

    metadata = BookMetadata(
        title=cfg.metadata.title,
        authors=cfg.metadata.authors,
        language=cfg.metadata.language,
        identifier=cfg.metadata.identifier,
        publisher=cfg.metadata.publisher,
    )

    adapter = MiddleJsonAdapter(
        base_dir=canonical_middle_json.parent,
        metadata=metadata,
        strict=cfg.app.strict,
    )
    raw_ir = adapter.convert_middle_json(data)
    save_bookir(raw_ir, paths.ir_raw_json)

    logger.info("Applying normalization (cross-page joins, page labels, layout hints)...")
    normalized_ir = normalize_bookir(raw_ir, raw_page_number_texts=raw_page_number_texts)
    save_bookir(normalized_ir, paths.ir_normalized_json)

    logger.info(
        "=== Milestone M2 Complete: BookIR normalized with %d blocks, %d assets ===",
        len(normalized_ir.blocks),
        len(normalized_ir.assets),
    )
    return raw_ir, normalized_ir


def run_conversion_m3(
    normalized_ir: BookIR,
    paths: JobPaths,
    cfg: JobConfig,
) -> RenderResult:
    """
    Execute M3 (Reflow XHTML / MathML renderer) pipeline.

    Writes unpacked publication tree to:
      render/OEBPS/
        text/*.xhtml
        styles/book.css
        images/*
        render-manifest.json

    Returns RenderResult.
    """
    logger.info("[Stage 4/6] Rendering BookIR to reflowable XHTML/MathML...")
    renderer = ReflowRenderer(
        output_dir=paths.render_dir,
        cli_title=cfg.metadata.title,
        cli_language=cfg.metadata.language,
        cli_identifier=cfg.metadata.identifier,
    )
    result = renderer.render(normalized_ir)
    logger.info(
        "=== Milestone M3 Complete: %d XHTML parts, %d math, %d figures, %d tables ===",
        result.xhtml_part_count,
        result.math_count,
        result.figure_count + result.chart_count,
        result.table_count,
    )
    return result


def run_conversion_m4(
    render_result: RenderResult,
    output_epub: Path,
    paths: JobPaths,
    cfg: JobConfig,
) -> PackagingResult:
    """
    Execute M4 (Native EPUB 3.3 packaging and EPUBCheck validation) pipeline.

    Packages OEBPS tree into output_epub and validates with EPUBCheck.
    Returns PackagingResult.
    """
    logger.info("[Stage 5/6] Packaging reflowable EPUB 3.3 and validating with EPUBCheck...")
    packager = EpubPackager(
        epubcheck_jar=get_epubcheck_jar_path(),
        strict=cfg.app.strict,
    )
    res = packager.package(
        render_result=render_result,
        output_epub=output_epub,
        staging_dir=paths.render_dir,
        validation_dir=paths.validation_dir,
        authors=cfg.metadata.authors,
        publisher=cfg.metadata.publisher,
        qa_report_path=paths.qa_report_html,
    )
    logger.info(
        "=== Milestone M4 Complete: %s (%.2f MB, EPUBCheck PASS) ===",
        output_epub,
        res.file_size_bytes / (1024 * 1024),
    )
    return res


def run_pipeline(
    input_dir: Path,
    output_epub: Path,
    cfg: JobConfig,
    force_mineru: bool = False,
) -> PackagingResult:
    """Run full conversion pipeline from input page image directory to validated EPUB."""
    # Execute through M1
    paths, canonical_middle = run_conversion_m1(input_dir, cfg, force_mineru=force_mineru)

    # Execute M2
    _, normalized_ir = run_conversion_m2(canonical_middle, paths, cfg)

    # Execute M3
    render_result = run_conversion_m3(normalized_ir, paths, cfg)

    # Execute M4
    packaging_result = run_conversion_m4(render_result, output_epub, paths, cfg)

    return packaging_result


def run_from_middle(
    middle_json: Path,
    output_epub: Path,
    cfg: JobConfig,
) -> PackagingResult:
    """Run conversion pipeline directly from an existing MinerU middle.json."""
    paths = create_job_paths(cfg.app.work_dir)
    configure_logging(level=cfg.app.logging_level, log_file=paths.log_file)
    logger.info("=== Starting Book2Epub (from-middle) Job: %s ===", paths.job_id)

    # Copy / canonicalize middle.json and adjacent images to canonical area
    canonical_middle, _ = canonicalize_mineru_output(
        middle_json,
        paths.mineru_canonical_dir,
    )

    # Execute M2
    _, normalized_ir = run_conversion_m2(canonical_middle, paths, cfg)

    # Execute M3
    render_result = run_conversion_m3(normalized_ir, paths, cfg)

    # Execute M4
    packaging_result = run_conversion_m4(render_result, output_epub, paths, cfg)

    return packaging_result
