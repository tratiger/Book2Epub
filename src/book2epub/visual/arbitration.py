"""Multimodal visual semantic arbitration (M9 Section 7-8, Appendix K3-K5)."""

import logging

from book2epub.config import JobConfig
from book2epub.ir.models import BookIR
from book2epub.paths import JobPaths
from book2epub.providers.base import StructuredProvider
from book2epub.providers.models import ImageInput, StructuredInferenceRequest
from book2epub.semantic.apply import (
    apply_semantic_decisions,
)
from book2epub.semantic.decisions import (
    SemanticAuditRecord,
)
from book2epub.semantic.models import SemanticDraftBook, SemanticEvidenceBook
from book2epub.semantic.reconcile import ReconciledSemanticDecision
from book2epub.semantic.schemas import build_provider_schema
from book2epub.visual.crop import map_and_crop
from book2epub.visual.models import VisualSemanticBatch
from book2epub.visual.raster import PageRasterCache
from book2epub.visual.source import VisualSource

logger = logging.getLogger(__name__)

VISUAL_ARBITRATION_SYSTEM_INSTRUCTION = """\
You are an expert technical book layout and typography analyst.
You are adjudicating the semantic classification of a document block using visual
evidence from the printed book.

Attached images (in order):
1. Target block crop (zoomed-in view of the block)
2. Current full page containing the block
3. (Optional) Preceding context page
4. (Optional) Succeeding context page

Instructions:
1. Examine visual evidence (font, borders, background shading, layout geometry, margins).
2. Determine whether the block should be classified as the proposed target, kept as original,
   or reclassified.
3. You may choose ONLY structural targets. Never produce or modify replacement prose.
4. Set decision to 'confirm_proposed', 'reject_keep_original', or 'replace_with_alternate'.
5. If visual text in the block contains OCR glyph errors that warrant text review,
   set ocr_review_recommended to true.
6. Provide high confidence only when visual evidence is distinct and unambiguous.
"""

VISUAL_ARBITRATION_USER_PROMPT = """\
Please adjudicate the following block based on the attached visual evidence:
Block ID: {block_id}
Original Document AI Type: {original_type}
Proposed Semantic Retype: {proposed_type}
Initial Confidence: {initial_confidence}
Evidence Codes: {evidence_codes}
Rationale: {rationale}
Allowed Targets: {allowed_targets}

Provide your structured visual adjudication decision conforming to the schema.
"""


def should_trigger_visual_review(
    audit: SemanticAuditRecord,
    vision_mode: str,
    auto_apply_threshold: float,
    review_floor: float,
) -> bool:
    """Determine whether an M8 audit record triggers multimodal visual review (M9 Section 7)."""
    if vision_mode == "off":
        return False

    # Check auto triggers
    is_conflict = audit.status in ("preserved_original_conflict", "conflict")
    is_queued = audit.status == "queued_visual_review"
    is_ambiguous = any("AMBIGUOUS" in c for c in audit.evidence_codes)
    is_table_retype = audit.source_kind == "table" and audit.proposed_target in (
        "terminal_output",
        "shell_command",
        "source_code",
        "log_output",
        "config_file",
        "generic_preformatted",
    )
    is_heading_retype = (
        audit.source_kind in ("heading", "paragraph")
        and audit.proposed_target in ("heading", "paragraph")
        and audit.confidence < 0.90
    )

    auto_trigger = (
        is_conflict
        or is_queued
        or is_ambiguous
        or is_table_retype
        or is_heading_retype
        or (review_floor <= audit.confidence < auto_apply_threshold)
    )

    if vision_mode == "auto":
        return auto_trigger
    elif vision_mode == "on":
        # Review all proposed changes plus all auto triggers
        return auto_trigger or (audit.proposed_target != audit.source_kind)

    return False


def run_visual_arbitration(
    bookir: BookIR,
    evidence: SemanticEvidenceBook,
    draft: SemanticDraftBook,
    audits: list[SemanticAuditRecord],
    cfg: JobConfig,
    paths: JobPaths,
    visual_source: VisualSource,
    provider: StructuredProvider,
) -> tuple[BookIR, list[SemanticAuditRecord], set[str]]:
    """
    Execute multimodal visual arbitration for triggered semantic blocks (M9 Section 7-8).
    Returns (updated_ir, updated_audits, ocr_recommended_block_ids).
    """
    if cfg.semantic.vision == "off" or not visual_source.has_visual:
        return bookir, audits, set()

    evidence_lookup = {b.block_id: b for b in evidence.blocks}
    block_lookup = {b.id: b for b in bookir.blocks}

    raster_cache = PageRasterCache(paths.semantic_visual_pages_dir, visual_source)
    crops_dir = paths.semantic_visual_crops_dir

    ocr_recommended_block_ids: set[str] = set()
    updated_audits: list[SemanticAuditRecord] = []
    override_decisions: dict[str, ReconciledSemanticDecision] = {}

    for audit in audits:
        if not should_trigger_visual_review(
            audit=audit,
            vision_mode=cfg.semantic.vision,
            auto_apply_threshold=cfg.semantic.auto_apply_threshold,
            review_floor=cfg.semantic.review_floor,
        ):
            updated_audits.append(audit)
            continue

        ev = evidence_lookup.get(audit.block_id)
        blk = block_lookup.get(audit.block_id)
        if not ev or not blk or not ev.bbox:
            updated_audits.append(audit)
            continue

        page_idx = ev.page_idx
        source_page_size = (
            (int(ev.page_size[0]), int(ev.page_size[1]))
            if ev.page_size and len(ev.page_size) >= 2 and ev.page_size[0] > 0
            else (600, 800)
        )

        # 1. Rasterize current page
        try:
            curr_page_path, curr_page_img = raster_cache.get_page_image(page_idx, max_edge=1800)
            crop_path, _ = map_and_crop(
                page_img=curr_page_img,
                bbox=ev.bbox,
                source_page_size=source_page_size,
                crops_dir=crops_dir,
                crop_name=audit.block_id,
            )
        except Exception as exc:
            logger.warning("Failed to render visual evidence for block %s: %s", audit.block_id, exc)
            updated_audits.append(audit)
            continue

        # 2. Build image input list (crop, current page, previous, next)
        images: list[ImageInput] = [
            ImageInput(path=crop_path, media_type="image/png", label="Target Block Crop"),
            ImageInput(path=curr_page_path, media_type="image/jpeg", label="Current Full Page"),
        ]

        if page_idx > 0:
            try:
                prev_path, _ = raster_cache.get_page_image(page_idx - 1, max_edge=1200)
                images.append(
                    ImageInput(
                        path=prev_path, media_type="image/jpeg", label="Preceding Context Page"
                    )
                )
            except Exception:
                pass

        try:
            next_path, _ = raster_cache.get_page_image(page_idx + 1, max_edge=1200)
            images.append(
                ImageInput(path=next_path, media_type="image/jpeg", label="Succeeding Context Page")
            )
        except Exception:
            pass

        # Limit to 4 images max (M9 Section 5)
        images = images[:4]

        # 3. Create Structured Inference Request
        user_text = VISUAL_ARBITRATION_USER_PROMPT.format(
            block_id=audit.block_id,
            original_type=audit.source_kind,
            proposed_type=audit.proposed_target,
            initial_confidence=f"{audit.confidence:.2f}",
            evidence_codes=", ".join(audit.evidence_codes),
            rationale=audit.rejection_reason or "Adjudication of semantic classification",
            allowed_targets=", ".join(ev.allowed_targets),
        )

        req = StructuredInferenceRequest(
            request_id=f"visual-{audit.block_id}",
            system_instruction=VISUAL_ARBITRATION_SYSTEM_INSTRUCTION,
            user_text=user_text,
            response_model_name="VisualSemanticBatch",
            response_schema=build_provider_schema(VisualSemanticBatch),
            images=images,
        )

        try:
            batch, res = provider.infer(req, response_model=VisualSemanticBatch)
        except Exception as exc:
            logger.warning("Visual provider inference failed for %s: %s", audit.block_id, exc)
            updated_audits.append(audit)
            continue

        if not batch.decisions:
            updated_audits.append(audit)
            continue

        vis_dec = batch.decisions[0]
        if vis_dec.ocr_review_recommended:
            ocr_recommended_block_ids.add(audit.block_id)

        # 4. Adjudication application logic (Appendix K5, M9 Section 8)
        # Visual decision overrides M8 queued/conflicting decision if confidence >= 0.85
        # High confidence (>= 0.90) can override text decision
        chosen_target = vis_dec.target or vis_dec.target_type or audit.proposed_target
        if vis_dec.decision == "reject_keep_original":
            chosen_target = audit.source_kind

        applied_status = audit.status
        final_target = audit.final_target

        if vis_dec.confidence >= 0.85 and chosen_target in ev.allowed_targets:
            if chosen_target == audit.source_kind:
                applied_status = "preserved_original_conflict"
                final_target = audit.source_kind
            else:
                applied_status = "visual_override_applied"
                final_target = chosen_target
                override_decisions[audit.block_id] = ReconciledSemanticDecision(
                    block_id=audit.block_id,
                    target=chosen_target,
                    heading_level=vis_dec.heading_level,
                    confidence=vis_dec.confidence,
                    evidence_codes=[str(c) for c in vis_dec.visual_evidence_codes]
                    + vis_dec.evidence_codes,
                    chunk_ids=[req.request_id],
                )
        elif vis_dec.confidence < 0.85:
            applied_status = "preserved_original_conflict"
            final_target = audit.source_kind

        updated_audit = audit.model_copy(
            update={
                "final_target": final_target,
                "confidence": vis_dec.confidence,
                "status": applied_status,
                "provider": f"{provider.name}-visual",
                "model": provider.model,
                "evidence_codes": audit.evidence_codes
                + [str(c) for c in vis_dec.visual_evidence_codes],
                "rejection_reason": vis_dec.rationale,
            }
        )
        updated_audits.append(updated_audit)

    # 5. Apply any overrides to bookir
    new_blocks = bookir.blocks
    if override_decisions:
        new_blocks, _ = apply_semantic_decisions(
            blocks=bookir.blocks,
            decisions=override_decisions,
            evidence_lookup=evidence_lookup,
            auto_apply_threshold=0.85,
            single_vote_threshold=0.85,
        )

    updated_ir = bookir.model_copy(update={"blocks": new_blocks})
    return updated_ir, updated_audits, ocr_recommended_block_ids
