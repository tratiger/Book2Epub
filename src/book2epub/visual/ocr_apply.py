"""Execution engine for multimodal OCR correction proposals (M9 Section 11-16, Appendix K8-K16)."""

import json
import logging

from book2epub.config import JobConfig
from book2epub.errors import SemanticError
from book2epub.ir.models import (
    Block,
    BookIR,
    CodeBlock,
    Heading,
    Inline,
    Paragraph,
    PreformattedBlock,
    SourceTextSegment,
    Text,
)
from book2epub.ir.serializer import save_bookir
from book2epub.ir.text_join import join_prose_texts
from book2epub.paths import JobPaths
from book2epub.providers.base import StructuredProvider
from book2epub.providers.models import ImageInput, StructuredInferenceRequest
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.models import SemanticEvidenceBook
from book2epub.semantic.schemas import build_provider_schema
from book2epub.visual.crop import map_and_crop
from book2epub.visual.models import (
    OCRAuditRecord,
    OCRCorrectionBatch,
    OCRSensitiveConfirmation,
)
from book2epub.visual.ocr_candidates import detect_ocr_candidates
from book2epub.visual.ocr_schema import (
    OCR_CONFIRMATION_SYSTEM_INSTRUCTION,
    OCR_CONFIRMATION_USER_PROMPT,
    OCR_PROPOSAL_SYSTEM_INSTRUCTION,
    OCR_PROPOSAL_USER_PROMPT,
)
from book2epub.visual.raster import PageRasterCache
from book2epub.visual.source import VisualSource
from book2epub.visual.validation import (
    EditBudgetTracker,
    calculate_changed_codepoints,
    is_sensitive_change,
    validate_ocr_proposal,
)

logger = logging.getLogger(__name__)


def run_ocr_correction(
    bookir: BookIR,
    evidence: SemanticEvidenceBook,
    cfg: JobConfig,
    paths: JobPaths,
    visual_source: VisualSource,
    provider: StructuredProvider | None = None,
    ocr_recommended_block_ids: set[str] | None = None,
) -> tuple[BookIR, list[OCRAuditRecord]]:
    """
    Execute multimodal OCR correction pipeline (M9 Section 15-16).
    Operates when cfg.ocr_correction.mode in ('safe', 'all').
    Writes:
      ir/bookir.corrected.json
      semantic/ocr-corrections.json
    Returns (corrected_bookir, ocr_audits).
    """
    mode = cfg.ocr_correction.mode
    if mode == "off":
        # OCR correction is OFF: make zero calls, do not mutate text
        return bookir, []

    if not visual_source.has_visual:
        raise SemanticError(f"OCR correction mode '{mode}' requires valid visual evidence source.")

    if provider is None:
        from book2epub.providers.factory import create_provider

        provider = create_provider(cfg, purpose="ocr")

    # 1. Candidate Detection
    explicit_keys: set[tuple[str, str]] = set()
    if ocr_recommended_block_ids:
        for blk_id in ocr_recommended_block_ids:
            explicit_keys.add((blk_id, f"{blk_id}-seg-0"))

    candidates = detect_ocr_candidates(
        blocks=bookir.blocks,
        mode=mode,
        explicit_candidate_keys=explicit_keys,
    )

    paths.semantic_dir.mkdir(parents=True, exist_ok=True)
    paths.semantic_visual_crops_dir.mkdir(parents=True, exist_ok=True)

    if not candidates:
        logger.info("No OCR correction candidates detected.")
        paths.semantic_ocr_corrections_json.write_text("[]", encoding="utf-8")
        save_bookir(bookir, paths.ir_corrected_json)
        return bookir, []

    logger.info(
        "Detected %d OCR correction candidates for review in '%s' mode.",
        len(candidates),
        mode,
    )

    # 2. Setup Budget Tracker
    total_segments = 0
    total_codepoints = 0
    for blk in bookir.blocks:
        if isinstance(blk, (Paragraph, Heading)):
            for inl in blk.inlines:
                if isinstance(inl, Text):
                    total_segments += len(inl.source_segments)
                    total_codepoints += sum(len(s.text) for s in inl.source_segments)
        elif isinstance(blk, (CodeBlock, PreformattedBlock)) and mode == "all":
            total_segments += 1
            total_codepoints += len(getattr(blk, "text", ""))

    budget_tracker = EditBudgetTracker(
        mode=mode,
        total_segments=total_segments,
        total_codepoints=total_codepoints,
    )

    raster_cache = PageRasterCache(paths.semantic_visual_pages_dir, visual_source)
    evidence_lookup = {b.block_id: b for b in evidence.blocks}

    audits: list[OCRAuditRecord] = []
    # Segment-level replacements: (block_id, segment_id) -> new_text
    applied_replacements: dict[tuple[str, str], str] = {}

    for cand in candidates:
        ev = evidence_lookup.get(cand.block_id)
        bbox = cand.bbox or (ev.bbox if ev else None)
        if not bbox:
            audits.append(
                OCRAuditRecord(
                    block_id=cand.block_id,
                    segment_id=cand.segment_id,
                    page_idx=cand.page_idx,
                    bbox=None,
                    old_text=cand.old_text,
                    new_text=cand.old_text,
                    old_sha256=cand.old_text_sha256,
                    new_sha256=cand.old_text_sha256,
                    provider=provider.name,
                    model=provider.model,
                    request_ids=[],
                    first_confidence=0.0,
                    visible_error_type="no_clear_error",
                    mode=mode,
                    status="rejected",
                    rejection_reasons=["No visual bounding box available for candidate segment"],
                )
            )
            continue

        source_page_size = (
            (int(ev.page_size[0]), int(ev.page_size[1]))
            if ev and ev.page_size and len(ev.page_size) >= 2 and ev.page_size[0] > 0
            else (600, 800)
        )

        # 3. Generate segment crop
        try:
            _, page_img = raster_cache.get_page_image(cand.page_idx, max_edge=1800)
            crop_path, _ = map_and_crop(
                page_img=page_img,
                bbox=bbox,
                source_page_size=source_page_size,
                crops_dir=paths.semantic_visual_crops_dir,
                crop_name=f"{cand.block_id}_{cand.segment_id}",
                is_segment=True,
            )
        except Exception as exc:
            logger.warning("Failed to render crop for segment %s: %s", cand.segment_id, exc)
            continue

        # 4. Request Proposal from Vision Provider
        req_id = f"ocr-{cand.block_id}-{cand.segment_id}"
        user_prompt = OCR_PROPOSAL_USER_PROMPT.format(
            block_id=cand.block_id,
            segment_id=cand.segment_id,
            current_text=cand.old_text,
            candidate_reason=cand.reason,
        )

        req = StructuredInferenceRequest(
            request_id=req_id,
            system_instruction=OCR_PROPOSAL_SYSTEM_INSTRUCTION,
            user_text=user_prompt,
            response_model_name="OCRCorrectionBatch",
            response_schema=build_provider_schema(OCRCorrectionBatch),
            images=[ImageInput(path=crop_path, media_type="image/png", label="Segment Crop")],
        )

        try:
            batch, _ = provider.infer(req, response_model=OCRCorrectionBatch)
        except Exception as exc:
            logger.warning("OCR inference failed for segment %s: %s", cand.segment_id, exc)
            continue

        if not batch.proposals:
            continue

        prop = batch.proposals[0]

        # Verify old hash matches
        if prop.old_text_sha256 != cand.old_text_sha256:
            audits.append(
                OCRAuditRecord(
                    block_id=cand.block_id,
                    segment_id=cand.segment_id,
                    page_idx=cand.page_idx,
                    bbox=bbox,
                    old_text=cand.old_text,
                    new_text=cand.old_text,
                    old_sha256=cand.old_text_sha256,
                    new_sha256=cand.old_text_sha256,
                    provider=provider.name,
                    model=provider.model,
                    request_ids=[req_id],
                    first_confidence=prop.confidence,
                    visible_error_type=prop.visible_error_type,
                    mode=mode,
                    status="rejected",
                    rejection_reasons=["Old text SHA-256 hash mismatch"],
                )
            )
            continue

        # Validate proposal safety & budget
        is_valid, val_status, val_reasons = validate_ocr_proposal(
            proposal=prop,
            old_text=cand.old_text,
            is_code_or_preformatted=cand.is_code,
            is_math=False,
            is_table_html=False,
            mode=mode,
            budget_tracker=budget_tracker,
        )

        if not is_valid:
            audits.append(
                OCRAuditRecord(
                    block_id=cand.block_id,
                    segment_id=cand.segment_id,
                    page_idx=cand.page_idx,
                    bbox=bbox,
                    old_text=cand.old_text,
                    new_text=prop.proposed_text or cand.old_text,
                    old_sha256=cand.old_text_sha256,
                    new_sha256=compute_text_sha256(prop.proposed_text or cand.old_text),
                    provider=provider.name,
                    model=provider.model,
                    request_ids=[req_id],
                    first_confidence=prop.confidence,
                    visible_error_type=prop.visible_error_type,
                    mode=mode,
                    status=val_status,  # type: ignore[arg-type]
                    rejection_reasons=val_reasons,
                )
            )
            continue

        # 5. Sensitive Confirmation Pass (Appendix K11, M9 Section 13)
        is_sensitive = is_sensitive_change(
            cand.old_text, prop.proposed_text or "", is_code_or_preformatted=cand.is_code
        )
        conf_ok = True
        conf_result: bool | None = None
        conf_conf: float | None = None
        request_ids = [req_id]

        if is_sensitive or cand.is_code:
            conf_req_id = f"ocr-conf-{cand.block_id}-{cand.segment_id}"
            request_ids.append(conf_req_id)
            conf_prompt = OCR_CONFIRMATION_USER_PROMPT.format(
                old_text=cand.old_text,
                proposed_candidate=prop.proposed_text,
            )
            conf_req = StructuredInferenceRequest(
                request_id=conf_req_id,
                system_instruction=OCR_CONFIRMATION_SYSTEM_INSTRUCTION,
                user_text=conf_prompt,
                response_model_name="OCRSensitiveConfirmation",
                response_schema=build_provider_schema(OCRSensitiveConfirmation),
                images=[ImageInput(path=crop_path, media_type="image/png", label="Segment Crop")],
            )
            try:
                conf_res, _ = provider.infer(conf_req, response_model=OCRSensitiveConfirmation)
                conf_result = conf_res.confirm and conf_res.exact_visible_match
                conf_conf = conf_res.confidence
                if not (conf_result and conf_conf >= 0.95 and prop.confidence >= 0.95):
                    conf_ok = False
            except Exception as exc:
                logger.warning("Confirmation inference failed: %s", exc)
                conf_ok = False

        if not conf_ok:
            audits.append(
                OCRAuditRecord(
                    block_id=cand.block_id,
                    segment_id=cand.segment_id,
                    page_idx=cand.page_idx,
                    bbox=bbox,
                    old_text=cand.old_text,
                    new_text=prop.proposed_text or cand.old_text,
                    old_sha256=cand.old_text_sha256,
                    new_sha256=compute_text_sha256(prop.proposed_text or cand.old_text),
                    provider=provider.name,
                    model=provider.model,
                    request_ids=request_ids,
                    first_confidence=prop.confidence,
                    confirmation_confidence=conf_conf,
                    confirmation_result=conf_result,
                    visible_error_type=prop.visible_error_type,
                    mode=mode,
                    status="rejected",
                    rejection_reasons=["Sensitive change failed independent visual confirmation"],
                )
            )
            continue

        # 6. Apply Validated Correction
        assert prop.proposed_text is not None
        applied_replacements[(cand.block_id, cand.segment_id)] = prop.proposed_text
        changed_cp = calculate_changed_codepoints(cand.old_text, prop.proposed_text)
        budget_tracker.record_applied(changed_cp)

        audits.append(
            OCRAuditRecord(
                block_id=cand.block_id,
                segment_id=cand.segment_id,
                page_idx=cand.page_idx,
                bbox=bbox,
                old_text=cand.old_text,
                new_text=prop.proposed_text,
                old_sha256=cand.old_text_sha256,
                new_sha256=compute_text_sha256(prop.proposed_text),
                provider=provider.name,
                model=provider.model,
                request_ids=request_ids,
                first_confidence=prop.confidence,
                confirmation_confidence=conf_conf,
                confirmation_result=conf_result,
                visible_error_type=prop.visible_error_type,
                mode=mode,
                status="applied",
            )
        )

    # 7. Materialize Corrected BookIR
    new_blocks: list[Block] = []
    for blk in bookir.blocks:
        if isinstance(blk, (Paragraph, Heading)):
            modified_inlines: list[Inline] = []
            for inl in blk.inlines:
                if isinstance(inl, Text):
                    modified_segs: list[SourceTextSegment] = []
                    seg_changed = False
                    for seg in inl.source_segments:
                        key = (blk.id, seg.segment_id)
                        if key in applied_replacements:
                            new_t = applied_replacements[key]
                            modified_segs.append(
                                seg.model_copy(
                                    update={
                                        "text": new_t,
                                        "text_sha256": compute_text_sha256(new_t),
                                    }
                                )
                            )
                            seg_changed = True
                        else:
                            modified_segs.append(seg)

                    if seg_changed:
                        new_inl_text = join_prose_texts([s.text for s in modified_segs])
                        modified_inlines.append(
                            inl.model_copy(
                                update={
                                    "text": new_inl_text,
                                    "source_segments": modified_segs,
                                }
                            )
                        )
                    else:
                        modified_inlines.append(inl)
                else:
                    modified_inlines.append(inl)

            new_blocks.append(blk.model_copy(update={"inlines": modified_inlines}))

        elif isinstance(blk, (CodeBlock, PreformattedBlock)) and mode == "all":
            seg_id = f"{blk.id}-seg-0"
            key = (blk.id, seg_id)
            if key in applied_replacements:
                new_code_text = applied_replacements[key]
                new_blocks.append(blk.model_copy(update={"text": new_code_text}))
            else:
                new_blocks.append(blk)
        else:
            new_blocks.append(blk)

    corrected_ir = bookir.model_copy(update={"blocks": new_blocks})

    # Save outputs
    paths.semantic_ocr_corrections_json.write_text(
        json.dumps([a.model_dump() for a in audits], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    save_bookir(corrected_ir, paths.ir_corrected_json)

    logger.info(
        "OCR correction complete: %d applied, %d rejected/suggested.",
        len(applied_replacements),
        len(audits) - len(applied_replacements),
    )
    return corrected_ir, audits
