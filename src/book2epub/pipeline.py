"""Conversion pipeline coordinating stages from Ingest through EPUB validation."""

import json
import logging
from pathlib import Path

from book2epub.config import JobConfig
from book2epub.errors import NotImplementedStageError
from book2epub.ingest.pdf import create_source_pdf
from book2epub.ingest.scanner import scan_and_validate_directory
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
from book2epub.paths import JobPaths, create_job_paths
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
    can_skip = (
        not force_mineru
        and is_mineru_cache_valid(paths.mineru_stage_file, cache_key, canonical_middle)
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


def run_pipeline(
    input_dir: Path,
    output_epub: Path,
    cfg: JobConfig,
    force_mineru: bool = False,
) -> None:
    """Run conversion pipeline through the latest implemented milestone."""
    # Execute through M1
    paths, canonical_middle = run_conversion_m1(input_dir, cfg, force_mineru=force_mineru)

    # In M1, next stages are not yet implemented
    raise NotImplementedStageError(
        f"Milestone M1 (Ingest and MinerU) succeeded.\n"
        f"Canonical middle JSON ready at: {canonical_middle}\n"
        "Milestone M2 (BookIR) is not yet implemented."
    )
