"""Execution engine for multimodal OCR correction proposals (M9 Section 11-16, Appendix K8-K16)."""

import logging
from typing import Any

from book2epub.config import JobConfig
from book2epub.errors import SemanticError
from book2epub.ir.models import (
    Aside,
    Block,
    BlockQuote,
    BookIR,
    Callout,
    Chart,
    CodeBlock,
    DefinitionList,
    DisplayMath,
    ExampleBlock,
    ExerciseBlock,
    Figure,
    Footnote,
    Heading,
    Hyperlink,
    IndexBlock,
    Inline,
    ListBlock,
    Paragraph,
    PreformattedBlock,
    SourceTextSegment,
    Table,
    Text,
)
from book2epub.ir.serializer import save_bookir
from book2epub.ir.text_join import join_prose_texts
from book2epub.paths import JobPaths
from book2epub.providers.base import StructuredProvider
from book2epub.providers.models import ImageInput, StructuredInferenceRequest
from book2epub.providers.usage import record_provider_usage
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.models import SemanticEvidenceBook
from book2epub.semantic.schemas import build_provider_schema
from book2epub.visual.crop import map_and_crop
from book2epub.visual.models import (
    OCRAuditRecord,
    OCRCorrectionAuditFile,
    OCRCorrectionBatch,
    OCRIndependentRead,
)
from book2epub.visual.ocr_candidates import (
    detect_ocr_candidates,
    iter_ocr_eligible_segments,
)
from book2epub.visual.ocr_schema import (
    OCR_INDEPENDENT_READ_SYSTEM_INSTRUCTION,
    OCR_INDEPENDENT_READ_USER_PROMPT,
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


def _replace_inlines(
    inlines: list[Inline],
    block_id: str,
    replacements: dict[tuple[str, str], str],
) -> list[Inline]:
    """Recursively replace text in inlines (Text, Hyperlink) and recompute hashes/joined text."""
    new_inlines: list[Inline] = []
    for inl in inlines:
        if isinstance(inl, Text):
            modified_segs: list[SourceTextSegment] = []
            seg_changed = False
            for seg in inl.source_segments:
                key = (block_id, seg.segment_id)
                if key in replacements:
                    new_t = replacements[key]
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
                new_inlines.append(
                    inl.model_copy(
                        update={
                            "text": new_inl_text,
                            "source_segments": modified_segs,
                        }
                    )
                )
            else:
                new_inlines.append(inl)
        elif isinstance(inl, Hyperlink):
            new_children = _replace_inlines(inl.children, block_id, replacements)
            new_inlines.append(inl.model_copy(update={"children": new_children}))
        else:
            new_inlines.append(inl)
    return new_inlines


def apply_segment_replacements(
    blocks: list[Block],
    replacements: dict[tuple[str, str], str],
    mode: str,
) -> list[Block]:
    """
    Recursively apply validated OCR segment replacements to BookIR blocks.
    Strictly preserves Math and Table HTML immutability.
    """
    new_blocks: list[Block] = []
    for blk in blocks:
        if isinstance(blk, DisplayMath):
            new_blocks.append(blk)
        elif isinstance(blk, Table):
            new_cap = _replace_inlines(blk.caption, blk.id, replacements)
            new_fn = _replace_inlines(blk.footnotes, blk.id, replacements)
            new_blocks.append(blk.model_copy(update={"caption": new_cap, "footnotes": new_fn}))
        elif isinstance(blk, (Figure, Chart)):
            new_cap = _replace_inlines(blk.caption, blk.id, replacements)
            new_fn = _replace_inlines(blk.footnotes, blk.id, replacements)
            new_blocks.append(blk.model_copy(update={"caption": new_cap, "footnotes": new_fn}))
        elif isinstance(blk, (Paragraph, Heading, Aside, Footnote)):
            new_inls = _replace_inlines(blk.inlines, blk.id, replacements)
            new_blocks.append(blk.model_copy(update={"inlines": new_inls}))
        elif isinstance(blk, (CodeBlock, PreformattedBlock)):
            new_cap = _replace_inlines(blk.caption, blk.id, replacements)
            new_fn = _replace_inlines(blk.footnotes, blk.id, replacements)
            updates: dict[str, Any] = {"caption": new_cap, "footnotes": new_fn}
            if mode == "all":
                key = (blk.id, f"{blk.id}-seg-0")
                if key in replacements:
                    updates["text"] = replacements[key]
            new_blocks.append(blk.model_copy(update=updates))
        elif isinstance(blk, Callout):
            new_title = _replace_inlines(blk.title, blk.id, replacements)
            new_sub_blocks = apply_segment_replacements(blk.blocks, replacements, mode)
            new_blocks.append(
                blk.model_copy(update={"title": new_title, "blocks": new_sub_blocks})
            )
        elif isinstance(blk, BlockQuote):
            new_attr = _replace_inlines(blk.attribution, blk.id, replacements)
            new_sub_blocks = apply_segment_replacements(blk.blocks, replacements, mode)
            new_blocks.append(
                blk.model_copy(update={"attribution": new_attr, "blocks": new_sub_blocks})
            )
        elif isinstance(blk, (ExampleBlock, ExerciseBlock)):
            new_label = _replace_inlines(blk.label, blk.id, replacements)
            new_sub_blocks = apply_segment_replacements(blk.blocks, replacements, mode)
            new_blocks.append(
                blk.model_copy(update={"label": new_label, "blocks": new_sub_blocks})
            )
        elif isinstance(blk, DefinitionList):
            new_items = []
            for item in blk.items:
                term_inls = _replace_inlines(item.term, blk.id, replacements)
                defs_inls = [
                    _replace_inlines(d, blk.id, replacements) for d in item.definitions
                ]
                new_items.append(
                    item.model_copy(update={"term": term_inls, "definitions": defs_inls})
                )
            new_blocks.append(blk.model_copy(update={"items": new_items}))
        elif isinstance(blk, (ListBlock, IndexBlock)):
            new_items_list = [
                _replace_inlines(item_inls, blk.id, replacements) for item_inls in blk.items
            ]
            new_blocks.append(blk.model_copy(update={"items": new_items_list}))
        else:
            new_blocks.append(blk)

    return new_blocks


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

    # 1. Inspect Eligible Segments & Candidate Detection
    eligible_segments = list(iter_ocr_eligible_segments(bookir.blocks, mode))
    total_segments = len(eligible_segments)
    total_codepoints = sum(len(s.text) for s in eligible_segments)

    candidates = detect_ocr_candidates(
        blocks=bookir.blocks,
        mode=mode,
        ocr_recommended_block_ids=ocr_recommended_block_ids,
    )

    paths.semantic_dir.mkdir(parents=True, exist_ok=True)
    paths.semantic_visual_crops_dir.mkdir(parents=True, exist_ok=True)

    if not candidates:
        logger.info("No OCR correction candidates detected.")
        empty_audit = OCRCorrectionAuditFile(
            mode=mode,
            eligible_segment_count=total_segments,
            candidate_count=0,
            applied_count=0,
            rejected_count=0,
            budget_exceeded=False,
            total_codepoints=total_codepoints,
            changed_codepoints=0,
            audits=[],
        )
        paths.semantic_ocr_corrections_json.write_text(
            empty_audit.model_dump_json(indent=2), encoding="utf-8"
        )
        save_bookir(bookir, paths.ir_corrected_json)
        return bookir, []

    logger.info(
        "Detected %d OCR correction candidates for review in '%s' mode.",
        len(candidates),
        mode,
    )

    # 2. Setup Budget Tracker
    budget_tracker = EditBudgetTracker(
        mode=mode,
        total_segments=total_segments,
        total_codepoints=total_codepoints,
    )

    raster_cache = PageRasterCache(paths.semantic_visual_pages_dir, visual_source)
    evidence_lookup = {b.block_id: b for b in evidence.blocks}
    page_size_lookup: dict[int, tuple[int, int]] = {}
    for b in evidence.blocks:
        if (
            b.page_size
            and len(b.page_size) >= 2
            and b.page_size[0] > 0
            and b.page_size[1] > 0
        ):
            page_size_lookup.setdefault(
                b.page_idx,
                (int(b.page_size[0]), int(b.page_size[1])),
            )

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

        source_page_size: tuple[int, int] | None = None
        if (
            ev
            and ev.page_size
            and len(ev.page_size) >= 2
            and ev.page_size[0] > 0
            and ev.page_size[1] > 0
        ):
            source_page_size = (int(ev.page_size[0]), int(ev.page_size[1]))
        elif cand.page_idx in page_size_lookup:
            source_page_size = page_size_lookup[cand.page_idx]

        if source_page_size is None:
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
                    request_ids=[],
                    first_confidence=0.0,
                    visible_error_type="no_clear_error",
                    mode=mode,
                    status="rejected",
                    rejection_reasons=[
                        "Source page dimensions unavailable for coordinate mapping"
                    ],
                )
            )
            continue

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
                    request_ids=[],
                    first_confidence=0.0,
                    visible_error_type="no_clear_error",
                    mode=mode,
                    status="rejected",
                    rejection_reasons=[f"Failed to generate visual crop: {exc}"],
                )
            )
            continue

        # 4. Request Proposal from Vision Provider
        req_id = f"ocr-{cand.block_id}-{cand.segment_id}"
        user_prompt = OCR_PROPOSAL_USER_PROMPT.format(
            block_id=cand.block_id,
            segment_id=cand.segment_id,
            old_text_sha256=cand.old_text_sha256,
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
            batch, inf_res = provider.infer(req, response_model=OCRCorrectionBatch)
            record_provider_usage(
                paths,
                {
                    "request_id": req.request_id,
                    "provider": provider.name,
                    "model": provider.model,
                    "pass": "ocr_proposal",
                    "latency_ms": inf_res.latency_ms,
                    "usage": inf_res.usage.model_dump(),
                },
            )
        except Exception as exc:
            logger.warning("OCR inference failed for segment %s: %s", cand.segment_id, exc)
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
                    first_confidence=0.0,
                    visible_error_type="no_clear_error",
                    mode=mode,
                    status="rejected",
                    rejection_reasons=[f"OCR proposal provider inference failed: {exc}"],
                )
            )
            continue


        # Enforce candidate identity binding:
        # proposal.block_id == candidate.block_id
        # proposal.segment_id == candidate.segment_id
        # proposal.old_text_sha256 == candidate.old_text_sha256
        matching_proposals = [
            p
            for p in batch.proposals
            if p.block_id == cand.block_id
            and p.segment_id == cand.segment_id
            and p.old_text_sha256 == cand.old_text_sha256
        ]

        hash_mismatches = [
            p
            for p in batch.proposals
            if p.block_id == cand.block_id
            and p.segment_id == cand.segment_id
            and p.old_text_sha256 != cand.old_text_sha256
        ]

        if hash_mismatches:
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
                    first_confidence=hash_mismatches[0].confidence,
                    visible_error_type=hash_mismatches[0].visible_error_type,
                    mode=mode,
                    status="rejected",
                    rejection_reasons=["Old text SHA-256 hash mismatch"],
                )
            )
            continue

        if len(matching_proposals) == 0:
            # 0 matching proposals in batch
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
                    first_confidence=0.0,
                    visible_error_type="no_clear_error",
                    mode=mode,
                    status="rejected",
                    rejection_reasons=["No matching proposal in provider response for candidate"],
                )
            )
            continue

        if len(matching_proposals) > 1:
            # Duplicate / conflicting proposals for same candidate in same batch
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
                    first_confidence=matching_proposals[0].confidence,
                    visible_error_type="no_clear_error",
                    mode=mode,
                    status="rejected",
                    rejection_reasons=[
                        f"Conflict: received {len(matching_proposals)} "
                        "proposals for the same candidate"
                    ],
                )
            )
            continue

        prop = matching_proposals[0]

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

        # 5. Sensitive Confirmation Pass via Independent Transcription (Appendix K11, M9 hardening)
        is_sensitive = is_sensitive_change(
            cand.old_text, prop.proposed_text or "", is_code_or_preformatted=cand.is_code
        )
        needs_confirmation = is_sensitive or cand.is_code
        conf_ok = True
        conf_result: bool | None = None
        conf_conf: float | None = None
        conf_observed: str | None = None
        request_ids = [req_id]

        if needs_confirmation:
            conf_req_id = f"ocr-indep-{cand.block_id}-{cand.segment_id}"
            request_ids.append(conf_req_id)
            # Independent read prompt does NOT leak Pass 1 proposed text or current text
            conf_prompt = OCR_INDEPENDENT_READ_USER_PROMPT.format(
                block_id=cand.block_id,
                segment_id=cand.segment_id,
            )
            conf_req = StructuredInferenceRequest(
                request_id=conf_req_id,
                system_instruction=OCR_INDEPENDENT_READ_SYSTEM_INSTRUCTION,
                user_text=conf_prompt,
                response_model_name="OCRIndependentRead",
                response_schema=build_provider_schema(OCRIndependentRead),
                images=[ImageInput(path=crop_path, media_type="image/png", label="Segment Crop")],
            )
            try:
                indep_res, conf_inf_res = provider.infer(
                    conf_req, response_model=OCRIndependentRead
                )
                record_provider_usage(
                    paths,
                    {
                        "request_id": conf_req.request_id,
                        "provider": provider.name,
                        "model": provider.model,
                        "pass": "ocr_confirmation",
                        "latency_ms": conf_inf_res.latency_ms,
                        "usage": conf_inf_res.usage.model_dump(),
                    },
                )
                conf_conf = indep_res.confidence
                conf_observed = indep_res.observed_text

                # Strict confirmation checks:
                # 1. Identity binding
                id_match = (
                    indep_res.block_id == cand.block_id
                    and indep_res.segment_id == cand.segment_id
                )
                # 2. Visual evidence clear enough
                clear = bool(indep_res.clear_enough)
                # 3. Exact transcription agreement
                exact_match = (indep_res.observed_text == prop.proposed_text)
                # 4. Confidence >= 0.995 for both passes
                threshold_ok = (indep_res.confidence >= 0.995 and prop.confidence >= 0.995)

                conf_result = id_match and clear and exact_match and threshold_ok
                if not conf_result:
                    conf_ok = False
                    conf_reasons: list[str] = []
                    if not id_match:
                        conf_reasons.append(
                            "Independent read returned mismatched block_id or segment_id"
                        )
                    if not clear:
                        conf_reasons.append(
                            "Independent read reported visual evidence not clear enough"
                        )
                    if not exact_match:
                        conf_reasons.append(
                            f"Independent read disagreement: observed '{indep_res.observed_text}' "
                            f"!= proposed '{prop.proposed_text}'"
                        )
                    if not threshold_ok:
                        conf_reasons.append(
                            f"Confidence below sensitive threshold 0.995 "
                            f"(proposal: {prop.confidence}, independent: {indep_res.confidence})"
                        )

            except Exception as exc:
                logger.warning("Independent confirmation inference failed: %s", exc)
                conf_ok = False
                conf_reasons = [f"Independent confirmation call failed: {exc}"]

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
                        confirmation_result=False,
                        confirmation_observed_text=conf_observed,
                        visible_error_type=prop.visible_error_type,
                        mode=mode,
                        status="rejected",
                        rejection_reasons=conf_reasons,
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
                confirmation_result=conf_result if needs_confirmation else None,
                confirmation_observed_text=conf_observed,
                visible_error_type=prop.visible_error_type,
                mode=mode,
                status="applied",
            )
        )

    # 7. Materialize Corrected BookIR recursively
    new_blocks = apply_segment_replacements(
        blocks=bookir.blocks,
        replacements=applied_replacements,
        mode=mode,
    )
    corrected_ir = bookir.model_copy(update={"blocks": new_blocks})

    # 8. Save Authoritative OCRCorrectionAuditFile
    audit_file = OCRCorrectionAuditFile(
        mode=mode,
        eligible_segment_count=total_segments,
        candidate_count=len(candidates),
        applied_count=len(applied_replacements),
        rejected_count=len(audits) - len(applied_replacements),
        budget_exceeded=budget_tracker.budget_exceeded,
        total_codepoints=total_codepoints,
        changed_codepoints=budget_tracker.changed_codepoints,
        audits=audits,
    )
    paths.semantic_ocr_corrections_json.write_text(
        audit_file.model_dump_json(indent=2),
        encoding="utf-8",
    )
    save_bookir(corrected_ir, paths.ir_corrected_json)

    logger.info(
        "OCR correction complete: %d applied, %d rejected/suggested.",
        len(applied_replacements),
        len(audits) - len(applied_replacements),
    )
    return corrected_ir, audits

