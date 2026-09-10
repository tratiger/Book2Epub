"""Conversion pipeline coordinating stages from Ingest through EPUB validation."""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from book2epub.cache import (
    compute_ocr_cache_key,
    compute_visual_cache_key,
    hash_bookir_relevant,
    hash_model,
    hash_model_without_job_paths,
    materialize_global_stage_cache,
    persist_global_stage_cache,
    rebase_cached_bookir_blocks,
    stable_hash,
    stage_cache_hit,
)
from book2epub.config import JobConfig
from book2epub.ingest.pdf import create_source_pdf
from book2epub.ingest.scanner import scan_and_validate_directory
from book2epub.ir.adapter import MiddleJsonAdapter
from book2epub.ir.models import BookIR, BookMetadata
from book2epub.ir.normalize import normalize_bookir
from book2epub.ir.serializer import load_bookir, save_bookir
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
from book2epub.qa import QAReportData, QAViolation, generate_qa_report
from book2epub.qa.stage import StageState, record_stage_status
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
    global_cache_dir = cfg.app.work_dir / "cache" / cache_key
    cached_canonical = global_cache_dir / "canonical"
    cached_stage = global_cache_dir / "stage.json"
    cached_middle = cached_canonical / "book_middle.json"

    can_skip = not force_mineru and (
        is_mineru_cache_valid(paths.mineru_stage_file, cache_key, canonical_middle)
        or (
            global_cache_dir.is_dir()
            and is_mineru_cache_valid(cached_stage, cache_key, cached_middle)
        )
    )

    if can_skip:
        logger.info("[Stage 2/6] Skipping MinerU execution (cache hit).")
        if not canonical_middle.is_file() and cached_middle.is_file():
            paths.mineru_dir.mkdir(parents=True, exist_ok=True)
            if cached_stage.is_file():
                shutil.copy2(cached_stage, paths.mineru_stage_file)
            shutil.copytree(cached_canonical, paths.mineru_canonical_dir, dirs_exist_ok=True)
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

            # Populate global cache
            global_cache_dir.mkdir(parents=True, exist_ok=True)
            if paths.mineru_stage_file.is_file():
                shutil.copy2(paths.mineru_stage_file, cached_stage)
            if paths.mineru_canonical_dir.is_dir():
                shutil.copytree(paths.mineru_canonical_dir, cached_canonical, dirs_exist_ok=True)
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
    # Propagate invalidation downstream without changing the semantic provider
    # decision: visual/OCR/presentation depend on semantic output, while a
    # visual force must not cause semantic provider calls.
    if cfg.app.force_semantic:
        cfg.app.force_visual = True
        cfg.app.force_presentation = True
    elif cfg.app.force_visual:
        cfg.app.force_presentation = True
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

    is_evidence_needed = (
        cfg.semantic.enabled
        or cfg.ocr_correction.mode != "off"
        or cfg.presentation.mode == "infer"
    )

    if is_evidence_needed:
        from book2epub.semantic.draft import build_semantic_draft
        from book2epub.semantic.evidence import build_semantic_evidence
        from book2epub.semantic.hashing import compute_file_sha256

        mid_sha = compute_file_sha256(canonical_middle_json)
        raw_ir_sha = compute_file_sha256(paths.ir_raw_json)

        evidence_book = build_semantic_evidence(
            middle_data=data,
            raw_ir=raw_ir,
            source_middle_sha256=mid_sha,
            raw_bookir_sha256=raw_ir_sha,
        )
        paths.semantic_evidence_json.parent.mkdir(parents=True, exist_ok=True)
        paths.semantic_evidence_json.write_text(
            evidence_book.model_dump_json(indent=2), encoding="utf-8"
        )

        draft_book = build_semantic_draft(
            evidence_book=evidence_book,
            book_id=paths.job_id,
        )
        paths.semantic_draft_json.write_text(
            draft_book.model_dump_json(indent=2), encoding="utf-8"
        )
        logger.info(
            "Saved semantic evidence (%d blocks) and draft to %s",
            len(evidence_book.blocks),
            paths.semantic_dir,
        )

    ocr_recommended_block_ids: set[str] = set()

    if cfg.semantic.enabled:
        from book2epub.semantic.stage import run_semantic_reconstruction

        logger.info("[Semantic] Running two-pass document semantic reconstruction...")
        semantic_result = run_semantic_reconstruction(
            raw_ir=raw_ir,
            evidence=evidence_book,
            draft=draft_book,
            cfg=cfg,
            paths=paths,
        )
        semantic_ir = semantic_result.bookir
        logger.info(
            "[Semantic] Reconstruction complete: %d applied changes, %d preserved, %d conflicts",
            semantic_result.applied_changes_count,
            semantic_result.preserved_originals_count,
            semantic_result.conflict_count,
        )

        # M9 Visual Arbitration (if vision is not off)
        if cfg.semantic.vision != "off":
            from book2epub.providers.factory import create_provider
            from book2epub.visual.arbitration import run_visual_arbitration
            from book2epub.visual.source import VisualSource

            visual_source = VisualSource.resolve(cfg, paths=paths)
            if visual_source.has_visual:
                vis_provider = create_provider(cfg, purpose="visual")
                from book2epub.semantic.schemas import build_provider_schema
                from book2epub.visual.arbitration import (
                    VISUAL_ARBITRATION_SYSTEM_INSTRUCTION,
                    VISUAL_ARBITRATION_USER_PROMPT,
                    run_visual_arbitration,
                )
                from book2epub.visual.models import VisualSemanticBatch

                visual_key = compute_visual_cache_key(
                    semantic_decision_hash=stable_hash(
                        [a.model_dump() for a in semantic_result.audits]
                    ),
                    evidence_hash=hash_model_without_job_paths(evidence_book),
                    visual_hash=visual_source.source_hash,
                    provider=vis_provider.name,
                    model=vis_provider.model,
                    prompt=VISUAL_ARBITRATION_SYSTEM_INSTRUCTION + VISUAL_ARBITRATION_USER_PROMPT,
                    schema=build_provider_schema(VisualSemanticBatch),
                    mode=cfg.semantic.vision,
                    thresholds={
                        "auto_apply": cfg.semantic.auto_apply_threshold,
                        "review_floor": cfg.semantic.review_floor,
                    },
                )
                visual_outputs = (
                    paths.semantic_visual_ir_json,
                    paths.semantic_visual_audits_json,
                )
                visual_cache_artifacts = {
                    "stage.json": paths.semantic_visual_stage_json,
                    "bookir.json": paths.semantic_visual_ir_json,
                    "audits.json": paths.semantic_visual_audits_json,
                }
                visual_cache_hit = False
                if not cfg.app.force_visual:
                    visual_cache_hit = materialize_global_stage_cache(
                        cfg.app.work_dir, "visual", visual_key, visual_cache_artifacts
                    ) or stage_cache_hit(
                        paths.semantic_visual_stage_json, visual_key, visual_outputs
                    )
                if visual_cache_hit:
                    cached_visual_ir = load_bookir(paths.semantic_visual_ir_json)
                    # The cached BookIR may contain asset paths from another job.
                    # Reuse only visual-stage blocks and retain this run's root,
                    # metadata, and assets.
                    semantic_ir = rebase_cached_bookir_blocks(semantic_ir, cached_visual_ir)
                    visual_payload = json.loads(
                        paths.semantic_visual_audits_json.read_text(encoding="utf-8")
                    )
                    from book2epub.semantic.decisions import SemanticAuditRecord

                    updated_audits = [
                        SemanticAuditRecord.model_validate(item)
                        for item in visual_payload.get("audits", [])
                    ]
                    ocr_recommended_block_ids = set(
                        visual_payload.get("ocr_recommended_block_ids", [])
                    )
                    record_stage_status(
                        paths.semantic_visual_stage_json,
                        "semantic_visual",
                        StageState.CACHE_HIT,
                        input_hash=visual_key,
                        cache_key=visual_key,
                        provider=vis_provider.name,
                        model=vis_provider.model,
                        output_artifact=str(paths.semantic_visual_ir_json),
                        reason="visual arbitration cache hit",
                    )
                    persist_global_stage_cache(
                        cfg.app.work_dir, "visual", visual_key, visual_cache_artifacts
                    )
                else:
                    record_stage_status(
                        paths.semantic_visual_stage_json,
                        "semantic_visual",
                        StageState.RUNNING,
                        input_hash=visual_key,
                        cache_key=visual_key,
                        provider=vis_provider.name,
                        model=vis_provider.model,
                        reason="visual arbitration requested",
                    )
                    semantic_ir, updated_audits, ocr_recommended_block_ids = (
                        run_visual_arbitration(
                            bookir=semantic_ir,
                            evidence=evidence_book,
                            draft=draft_book,
                            audits=semantic_result.audits,
                            cfg=cfg,
                            paths=paths,
                            visual_source=visual_source,
                            provider=vis_provider,
                            raw_ir=raw_ir,
                            struct_decisions=semantic_result.struct_decisions,
                            semantic_decisions=semantic_result.semantic_decisions,
                        )
                    )
                    paths.semantic_visual_ir_json.parent.mkdir(parents=True, exist_ok=True)
                    save_bookir(semantic_ir, paths.semantic_visual_ir_json)
                    paths.semantic_visual_audits_json.write_text(
                        json.dumps(
                            {
                                "audits": [a.model_dump() for a in updated_audits],
                                "ocr_recommended_block_ids": sorted(
                                    ocr_recommended_block_ids
                                ),
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    record_stage_status(
                        paths.semantic_visual_stage_json,
                        "semantic_visual",
                        StageState.COMPLETE,
                        input_hash=visual_key,
                        cache_key=visual_key,
                        provider=vis_provider.name,
                        model=vis_provider.model,
                        output_artifact=str(paths.semantic_visual_ir_json),
                        reason="visual arbitration complete",
                    )
                    persist_global_stage_cache(
                        cfg.app.work_dir, "visual", visual_key, visual_cache_artifacts
                    )
                save_bookir(semantic_ir, paths.ir_semantic_json)
                # Write authoritative final audit artifact (M9-updated).
                # applied.m8.json (written by stage.py) remains as the M8-only provisional.
                paths.semantic_applied_json.write_text(
                    json.dumps([a.model_dump() for a in updated_audits], indent=2),
                    encoding="utf-8",
                )
            else:
                record_stage_status(
                    paths.semantic_visual_stage_json,
                    "semantic_visual",
                    StageState.SKIPPED,
                    reason="no source visual evidence",
                )
        else:
            record_stage_status(
                paths.semantic_visual_stage_json,
                "semantic_visual",
                StageState.SKIPPED,
                reason="semantic.vision=off",
            )
    else:
        semantic_ir = raw_ir
        record_stage_status(
            paths.semantic_stage_json,
            "semantic_structure",
            StageState.SKIPPED,
            reason="semantic.enabled=false",
        )

    # M9 Multimodal OCR Correction (safe | all)
    if cfg.ocr_correction.mode in ("safe", "all"):
        from book2epub.providers.factory import create_provider
        from book2epub.semantic.schemas import build_provider_schema
        from book2epub.visual.models import OCRCorrectionBatch
        from book2epub.visual.ocr_apply import run_ocr_correction
        from book2epub.visual.ocr_candidates import iter_ocr_eligible_segments
        from book2epub.visual.ocr_schema import (
            OCR_PROPOSAL_SYSTEM_INSTRUCTION,
            OCR_PROPOSAL_USER_PROMPT,
        )
        from book2epub.visual.source import VisualSource

        visual_source = VisualSource.resolve(cfg, paths=paths)
        ocr_provider = create_provider(cfg, purpose="ocr")
        candidate_old_hash = stable_hash(
            [
                {
                    "block_id": s.block_id,
                    "segment_id": s.segment_id,
                    "old_sha256": s.text_sha256,
                }
                for s in iter_ocr_eligible_segments(semantic_ir.blocks, cfg.ocr_correction.mode)
            ]
        )
        ocr_key = compute_ocr_cache_key(
            pre_ocr_ir_hash=hash_bookir_relevant(semantic_ir),
            candidate_old_hash=candidate_old_hash,
            visual_hash=visual_source.source_hash,
            mode=cfg.ocr_correction.mode,
            provider=ocr_provider.name,
            model=ocr_provider.model,
            prompt=OCR_PROPOSAL_SYSTEM_INSTRUCTION + OCR_PROPOSAL_USER_PROMPT,
            schema=build_provider_schema(OCRCorrectionBatch),
            policy_version="M9-ocr-policy-1.0",
            ocr_recommendation_hash=stable_hash(sorted(ocr_recommended_block_ids)),
        )
        ocr_cache_artifacts = {
            "stage.json": paths.semantic_ocr_stage_json,
            "bookir.corrected.json": paths.ir_corrected_json,
            "ocr-corrections.json": paths.semantic_ocr_corrections_json,
        }
        ocr_cache_hit = False
        if not cfg.app.force_visual:
            ocr_cache_hit = materialize_global_stage_cache(
                cfg.app.work_dir, "ocr", ocr_key, ocr_cache_artifacts
            ) or stage_cache_hit(
                paths.semantic_ocr_stage_json,
                ocr_key,
                (paths.ir_corrected_json, paths.semantic_ocr_corrections_json),
            )
        if ocr_cache_hit:
            cached_corrected_ir = load_bookir(paths.ir_corrected_json)
            # OCR cache artifacts can come from a different job.  Keep current
            # run asset/source paths and apply only cached corrected blocks.
            corrected_ir = rebase_cached_bookir_blocks(semantic_ir, cached_corrected_ir)
            record_stage_status(
                paths.semantic_ocr_stage_json,
                "ocr_correction",
                StageState.CACHE_HIT,
                input_hash=ocr_key,
                cache_key=ocr_key,
                provider=ocr_provider.name,
                model=ocr_provider.model,
                output_artifact=str(paths.ir_corrected_json),
                reason="OCR correction cache hit",
            )
            persist_global_stage_cache(
                cfg.app.work_dir, "ocr", ocr_key, ocr_cache_artifacts
            )
        else:
            record_stage_status(
                paths.semantic_ocr_stage_json,
                "ocr_correction",
                StageState.RUNNING,
                input_hash=ocr_key,
                cache_key=ocr_key,
                provider=ocr_provider.name,
                model=ocr_provider.model,
                reason="OCR correction requested",
            )
            corrected_ir, _ = run_ocr_correction(
                bookir=semantic_ir,
                evidence=evidence_book,
                cfg=cfg,
                paths=paths,
                visual_source=visual_source,
                provider=ocr_provider,
                ocr_recommended_block_ids=ocr_recommended_block_ids,
            )
            record_stage_status(
                paths.semantic_ocr_stage_json,
                "ocr_correction",
                StageState.COMPLETE,
                input_hash=ocr_key,
                cache_key=ocr_key,
                provider=ocr_provider.name,
                model=ocr_provider.model,
                output_artifact=str(paths.ir_corrected_json),
                reason="OCR correction complete",
            )
            persist_global_stage_cache(
                cfg.app.work_dir, "ocr", ocr_key, ocr_cache_artifacts
            )
    else:
        corrected_ir = semantic_ir
        record_stage_status(
            paths.semantic_ocr_stage_json,
            "ocr_correction",
            StageState.SKIPPED,
            reason="ocr_correction.mode=off",
        )

    logger.info("Applying normalization (cross-page joins, page labels, layout hints)...")
    normalized_ir = normalize_bookir(corrected_ir, raw_page_number_texts=raw_page_number_texts)
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
    profile: Any | None = None,
) -> RenderResult:
    """
    Execute M3/M10 (Reflow XHTML / MathML renderer) pipeline.

    Writes unpacked publication tree to:
      render/OEBPS/
        text/*.xhtml
        styles/book.css
        images/*
        render-manifest.json

    Returns RenderResult.
    """
    render_ir = normalized_ir
    if cfg.presentation.mode != "legacy":
        if profile is None:
            from book2epub.presentation.stage import resolve_style_profile

            profile, _ = resolve_style_profile(normalized_ir, cfg, paths)

        from book2epub.typography.normalize import typography_normalize_bookir
        from book2epub.typography.report import save_normalization_report

        logger.info(
            "[Typography] Running whitespace and list normalization (mode=%s)...",
            cfg.presentation.mode,
        )
        typography_key = stable_hash(
            {
                "ir": hash_model(normalized_ir),
                "profile": hash_model(profile) if profile is not None else None,
                "rules": "M11-typography-1.0",
            }
        )
        record_stage_status(
            paths.typography_stage_json,
            "typography",
            StageState.RUNNING,
            input_hash=typography_key,
            cache_key=typography_key,
            output_artifact=str(paths.ir_typography_json),
            reason="typography normalization requested",
        )
        render_ir, norm_report = typography_normalize_bookir(normalized_ir, profile=profile)
        save_bookir(render_ir, paths.ir_typography_json)
        save_normalization_report(norm_report, paths.normalization_report_file)
        record_stage_status(
            paths.typography_stage_json,
            "typography",
            StageState.COMPLETE,
            input_hash=typography_key,
            cache_key=typography_key,
            output_artifact=str(paths.ir_typography_json),
            reason="typography normalization complete",
        )
        logger.info(
            "[Typography] Reconstructed %d text segments, %d markers extracted, %d dehyphenations",
            norm_report.source_segment_reconstructions,
            norm_report.list_markers_extracted,
            norm_report.dehyphenations,
        )

    logger.info(
        "[Stage 4/6] Rendering BookIR to reflowable XHTML/MathML (presentation=%s)...",
        cfg.presentation.mode,
    )
    render_key = stable_hash(
        {
            "ir": hash_model(render_ir),
            "presentation_mode": cfg.presentation.mode,
            "profile": hash_model(profile) if profile is not None else None,
            "renderer": "M10-render-1.0",
        }
    )
    record_stage_status(
        paths.render_stage_json,
        "render",
        StageState.RUNNING,
        input_hash=render_key,
        cache_key=render_key,
        output_artifact=str(paths.render_oebps_dir),
        reason="render requested",
    )
    renderer = ReflowRenderer(
        output_dir=paths.render_dir,
        cli_title=cfg.metadata.title,
        cli_language=cfg.metadata.language,
        cli_identifier=cfg.metadata.identifier,
        presentation_config=cfg.presentation,
        profile=profile,
    )
    result = renderer.render(render_ir)
    result.rendered_ir = render_ir
    logger.info(
        "=== Milestone M3 Complete: %d XHTML parts, %d math, %d figures, %d tables ===",
        result.xhtml_part_count,
        result.math_count,
        result.figure_count + result.chart_count,
        result.table_count,
    )
    record_stage_status(
        paths.render_stage_json,
        "render",
        StageState.COMPLETE,
        input_hash=render_key,
        cache_key=render_key,
        output_artifact=str(paths.render_oebps_dir),
        reason="render complete",
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
    package_key = stable_hash(
        {
            "render_manifest": render_result.manifest.to_dict(),
            "packager": "M4-package-1.0",
        }
    )
    record_stage_status(
        paths.package_stage_json,
        "package",
        StageState.RUNNING,
        input_hash=package_key,
        cache_key=package_key,
        output_artifact=str(output_epub),
        reason="package requested",
    )
    record_stage_status(
        paths.validate_stage_json,
        "validate",
        StageState.RUNNING,
        input_hash=package_key,
        cache_key=package_key,
        output_artifact=str(paths.epubcheck_json_file),
        reason="EPUBCheck requested",
    )
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
    record_stage_status(
        paths.package_stage_json,
        "package",
        StageState.COMPLETE,
        input_hash=package_key,
        cache_key=package_key,
        output_artifact=str(output_epub),
        reason="package complete",
    )
    record_stage_status(
        paths.validate_stage_json,
        "validate",
        StageState.COMPLETE,
        input_hash=package_key,
        cache_key=package_key,
        output_artifact=str(paths.epubcheck_json_file),
        reason="EPUBCheck complete",
    )
    return res


def run_conversion_m5(
    paths: JobPaths,
    raw_middle_path: Path,
    book_ir: BookIR,
    render_result: RenderResult,
    packaging_result: PackagingResult,
    cfg: JobConfig,
    manifest_data: dict[str, Any] | None = None,
) -> QAReportData:
    """
    Execute M5 (QA diagnostics, structural checks, and release reporting).

    Writes:
      qa/report.json
      qa/report.html
    """
    logger.info("[Stage 6/6] Generating comprehensive QA report and reconciliation checks...")
    qa_key = stable_hash(
        {
            "book_ir": hash_model(book_ir),
            "render_manifest": render_result.manifest.to_dict(),
            "qa": "M12-qa-1.0",
        }
    )
    record_stage_status(
        paths.qa_stage_json,
        "qa",
        StageState.RUNNING,
        input_hash=qa_key,
        cache_key=qa_key,
        output_artifact=str(paths.qa_report_json),
        reason="QA requested",
    )
    with raw_middle_path.open("r", encoding="utf-8") as f:
        raw_middle_data = json.load(f)

    # Use final rendered typography-normalized BookIR when available
    if render_result.rendered_ir is not None:
        book_ir = render_result.rendered_ir
    elif paths.ir_typography_json.is_file():
        try:
            from book2epub.ir.serializer import load_bookir

            book_ir = load_bookir(paths.ir_typography_json)
        except Exception as e:
            raise RuntimeError(
                f"Failed to load typography-normalized BookIR from {paths.ir_typography_json}: {e}"
            ) from e

    evidence = None
    if paths.semantic_evidence_json.is_file():
        from book2epub.semantic.models import SemanticEvidenceBook

        evidence = SemanticEvidenceBook.model_validate_json(
            paths.semantic_evidence_json.read_text(encoding="utf-8")
        )

    audits = None
    if paths.semantic_applied_json.is_file():
        from book2epub.semantic.decisions import SemanticAuditRecord

        applied_data = json.loads(paths.semantic_applied_json.read_text(encoding="utf-8"))
        if isinstance(applied_data, list):
            audits = [SemanticAuditRecord.model_validate(a) for a in applied_data]
        elif isinstance(applied_data, dict):
            audits = [SemanticAuditRecord.model_validate(a) for a in applied_data.get("audits", [])]

    ocr_audits = None
    if paths.semantic_ocr_corrections_json.is_file():
        try:
            from book2epub.visual.models import OCRCorrectionAuditFile

            ocr_raw = json.loads(paths.semantic_ocr_corrections_json.read_text(encoding="utf-8"))
            if isinstance(ocr_raw, dict) and "audits" in ocr_raw:
                ocr_audits = OCRCorrectionAuditFile.model_validate(ocr_raw).audits
        except Exception:
            pass

    outline = None
    outline_violations: list[QAViolation] = []
    if paths.semantic_outline_json.is_file():
        from book2epub.semantic.structure import BookOutline

        try:
            outline = BookOutline.model_validate_json(
                paths.semantic_outline_json.read_text(encoding="utf-8")
            )
            from book2epub.qa.semantic import evaluate_outline_qa

            _, outline_violations = evaluate_outline_qa(
                outline,
                book_ir,
                oebps_dir=paths.render_oebps_dir,
                toc_entries=render_result.manifest.toc,
            )
        except Exception as e:
            outline_violations.append(
                QAViolation(
                    category="outline",
                    severity="error",
                    code="OUTLINE_PARSE_ERROR",
                    message=f"Failed to parse outline JSON: {e}",
                )
            )

    from book2epub.qa.ocr import evaluate_ocr_qa
    from book2epub.qa.presentation import evaluate_presentation_qa
    from book2epub.qa.semantic import (
        build_preservation_ledger,
        evaluate_preservation_qa,
        evaluate_semantic_transitions,
    )

    preservation_ledger = build_preservation_ledger(
        evidence, book_ir, audits, ocr_audits=ocr_audits
    )
    preservation_violations = evaluate_preservation_qa(
        preservation_ledger, evidence, book_ir, ocr_audits=ocr_audits
    )
    semantic_metrics = evaluate_semantic_transitions(evidence, book_ir, audits, outline=outline)
    ocr_metrics, ocr_warns = evaluate_ocr_qa(
        paths.semantic_ocr_corrections_json, cfg.ocr_correction.mode
    )
    ocr_violations = [
        QAViolation(
            category="ocr",
            severity="fatal",
            code="OCR_INVARIANT_VIOLATION",
            message=w,
        )
        for w in ocr_warns
    ]

    presentation_metrics, pres_warns = evaluate_presentation_qa(
        oebps_dir=paths.render_oebps_dir,
        manifest=render_result.manifest,
        mode=cfg.presentation.mode,
    )
    pres_violations = [
        QAViolation(
            category="presentation",
            severity="fatal" if "forbidden" in w.lower() else "error",
            code="PRESENTATION_VIOLATION",
            message=w,
        )
        for w in pres_warns
    ]

    all_violations: list[QAViolation] = (
        preservation_violations + ocr_violations + pres_violations + outline_violations
    )

    qa_data = generate_qa_report(
        job_id=paths.job_id,
        raw_middle_data=raw_middle_data,
        book_ir=book_ir,
        render_result=render_result,
        packaging_result=packaging_result,
        cfg=cfg,
        report_json_path=paths.qa_report_json,
        report_html_path=paths.qa_report_html,
        manifest_data=manifest_data,
        preservation_ledger=preservation_ledger,
        semantic_metrics=semantic_metrics,
        ocr_metrics=ocr_metrics,
        presentation_metrics=presentation_metrics,
        violations=all_violations,
    )
    packaging_result.qa_report_path = paths.qa_report_html

    # Strict QA Release Gate Enforcement
    if cfg.app.strict:
        fatal_errors = [v for v in all_violations if v.severity in ("fatal", "error")]
        failed_checks = [c for c in qa_data.structural_checks if not c.passed]
        if fatal_errors or failed_checks:
            err_msgs = [f"[{v.category.upper()}] {v.message}" for v in fatal_errors]
            err_msgs.extend([f"[CHECK] {c.name}: {c.details}" for c in failed_checks])
            summary = "\n".join(f"  - {m}" for m in err_msgs)
            logger.error(
                "Strict QA release gate failed with %d fatal/error issue(s):\n%s",
                len(err_msgs),
                summary,
            )
            raise RuntimeError(
                f"Strict QA release gate failed with {len(err_msgs)} issue(s):\n{summary}\n"
                f"Diagnostic report saved at: {paths.qa_report_html}"
            )

    logger.info("=== Milestone M5 Complete: QA report at %s ===", paths.qa_report_html)
    record_stage_status(
        paths.qa_stage_json,
        "qa",
        StageState.COMPLETE,
        input_hash=qa_key,
        cache_key=qa_key,
        output_artifact=str(paths.qa_report_json),
        reason="QA complete",
    )
    return qa_data


def run_pipeline(
    input_dir: Path,
    output_epub: Path,
    cfg: JobConfig,
    force_mineru: bool = False,
) -> PackagingResult:
    """Run full conversion pipeline from input page image directory to validated EPUB."""
    if force_mineru:
        # MinerU is the strongest upstream invalidation boundary.  Keep the
        # caller's config immutable while forcing every dependent stage.
        cfg = cfg.model_copy(deep=True)
        cfg.app.force_semantic = True
        cfg.app.force_visual = True
        cfg.app.force_presentation = True
    # Execute through M1
    paths, canonical_middle = run_conversion_m1(input_dir, cfg, force_mineru=force_mineru)

    # Execute M2
    _, normalized_ir = run_conversion_m2(canonical_middle, paths, cfg)

    # Execute M3
    render_result = run_conversion_m3(normalized_ir, paths, cfg)

    # Atomic EPUB packaging: write candidate to temporary file first
    tmp_epub = output_epub.with_suffix(".epub.tmp")
    packaging_result = run_conversion_m4(render_result, tmp_epub, paths, cfg)

    # Execute M5
    manifest_data = (
        json.loads(paths.manifest_file.read_text(encoding="utf-8"))
        if paths.manifest_file.is_file()
        else None
    )
    try:
        run_conversion_m5(
            paths=paths,
            raw_middle_path=canonical_middle,
            book_ir=render_result.rendered_ir or normalized_ir,
            render_result=render_result,
            packaging_result=packaging_result,
            cfg=cfg,
            manifest_data=manifest_data,
        )
    except Exception:
        if tmp_epub.is_file():
            tmp_epub.unlink(missing_ok=True)
        raise

    # Promote candidate to final output_epub only after all release gates pass
    if tmp_epub.is_file():
        os.replace(tmp_epub, output_epub)
        packaging_result.epub_path = output_epub

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

    # Atomic EPUB packaging: write candidate to temporary file first
    tmp_epub = output_epub.with_suffix(".epub.tmp")
    packaging_result = run_conversion_m4(render_result, tmp_epub, paths, cfg)

    # Execute M5
    try:
        run_conversion_m5(
            paths=paths,
            raw_middle_path=canonical_middle,
            book_ir=render_result.rendered_ir or normalized_ir,
            render_result=render_result,
            packaging_result=packaging_result,
            cfg=cfg,
            manifest_data=None,
        )
    except Exception:
        if tmp_epub.is_file():
            tmp_epub.unlink(missing_ok=True)
        raise

    # Promote candidate to final output_epub only after all release gates pass
    if tmp_epub.is_file():
        os.replace(tmp_epub, output_epub)
        packaging_result.epub_path = output_epub

    return packaging_result
