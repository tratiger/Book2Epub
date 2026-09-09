"""OCR correction candidate detection and conservative gating (M9 Section 10, Appendix K7)."""

import logging
import re
from typing import Literal

from pydantic import BaseModel

from book2epub.ir.models import (
    Block,
    CodeBlock,
    DisplayMath,
    Heading,
    InlineMath,
    Paragraph,
    PreformattedBlock,
    Table,
    Text,
)

logger = logging.getLogger(__name__)

# Heuristic patterns for OCR corruption
SUSPICIOUS_CHARS_PATTERN = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")
# Isolated alphanumeric digit inside Japanese kana (e.g., 'すべ1', 'フ7イル')
JAPANESE_DIGIT_CONFUSION_PATTERN = re.compile(
    r"([\u3040-\u309f\u30a0-\u30ff][017][\u3040-\u309f\u30a0-\u30ff])"
)
# Obvious letter-digit confusion in English words
COMMON_GLYPH_CONFUSIONS = re.compile(
    r"\b([a-zA-Z]+[01][a-zA-Z]+|retum)\b"
)


class OCRCandidate(BaseModel):
    """Candidate source segment identified for multimodal OCR review."""

    block_id: str
    segment_id: str
    page_idx: int
    bbox: list[float] | None = None
    old_text: str
    old_text_sha256: str
    is_code: bool = False
    reason: str


def _scan_segment_for_ocr_anomaly(
    text: str,
    is_code: bool,
    explicitly_flagged: bool,
) -> str | None:
    """Detect if a text segment contains OCR corruption signals."""
    if explicitly_flagged:
        return "EXPLICIT_VISUAL_REVIEW_RECOMMENDED"

    if SUSPICIOUS_CHARS_PATTERN.search(text):
        return "UNICODE_REPLACEMENT_OR_CONTROL_CHAR"

    if JAPANESE_DIGIT_CONFUSION_PATTERN.search(text):
        return "JAPANESE_KANA_DIGIT_CONFUSION"

    if COMMON_GLYPH_CONFUSIONS.search(text):
        return "ALPHANUMERIC_GLYPH_CONFUSION"

    return None


def detect_ocr_candidates(
    blocks: list[Block],
    mode: Literal["off", "safe", "all"],
    explicit_candidate_keys: set[tuple[str, str]] | None = None,
    max_per_page: int = 3,
) -> list[OCRCandidate]:
    """
    Detect OCR candidate segments from BookIR blocks without modifying text.
    Enforces mode filtering, exclusions, and per-page / book-level caps.
    """
    if mode == "off":
        return []

    explicit_keys = explicit_candidate_keys or set()
    candidates_by_page: dict[int, list[OCRCandidate]] = {}
    total_segments = 0

    for blk in blocks:
        # Exclude math and tables
        if isinstance(blk, (DisplayMath, Table)):
            continue

        is_code = isinstance(blk, (CodeBlock, PreformattedBlock))
        if is_code and mode == "safe":
            continue

        # Inspect inlines in Paragraph and Heading
        if isinstance(blk, (Paragraph, Heading)):
            for inl in blk.inlines:
                if isinstance(inl, InlineMath):
                    continue
                if isinstance(inl, Text):
                    for seg in inl.source_segments:
                        total_segments += 1
                        page = seg.page_idx
                        key = (blk.id, seg.segment_id)
                        explicit = key in explicit_keys
                        reason = _scan_segment_for_ocr_anomaly(
                            seg.text, is_code=False, explicitly_flagged=explicit
                        )
                        if reason:
                            seg_bbox_list = (
                                [seg.bbox.x0, seg.bbox.y0, seg.bbox.x1, seg.bbox.y1]
                                if seg.bbox
                                else None
                            )
                            cand = OCRCandidate(
                                block_id=blk.id,
                                segment_id=seg.segment_id,
                                page_idx=page,
                                bbox=seg_bbox_list,
                                old_text=seg.text,
                                old_text_sha256=seg.text_sha256,
                                is_code=False,
                                reason=reason,
                            )
                            candidates_by_page.setdefault(page, []).append(cand)

        elif is_code and mode == "all":
            # Inspect segments in CodeBlock / PreformattedBlock
            sources = blk.sources
            page = sources[0].page_idx if sources else 0
            # If code block has source_segments attached (or top-level lines)
            # Create candidate if anomaly is detected
            text = getattr(blk, "text", "")
            if text:
                total_segments += 1
                seg_id = f"{blk.id}-seg-0"
                key = (blk.id, seg_id)
                explicit = key in explicit_keys
                reason = _scan_segment_for_ocr_anomaly(
                    text, is_code=True, explicitly_flagged=explicit
                )
                if reason:
                    from book2epub.semantic.hashing import compute_text_sha256

                    src_box = sources[0].bbox if sources and sources[0].bbox else None
                    code_bbox_list = (
                        [src_box.x0, src_box.y0, src_box.x1, src_box.y1] if src_box else None
                    )
                    cand = OCRCandidate(
                        block_id=blk.id,
                        segment_id=seg_id,
                        page_idx=page,
                        bbox=code_bbox_list,
                        old_text=text,
                        old_text_sha256=compute_text_sha256(text),
                        is_code=True,
                        reason=reason,
                    )
                    candidates_by_page.setdefault(page, []).append(cand)

    # Apply per-page caps (max 3 candidates per page per Appendix K7)
    selected_candidates: list[OCRCandidate] = []
    for page in sorted(candidates_by_page.keys()):
        page_cands = candidates_by_page[page]
        selected_candidates.extend(page_cands[:max_per_page])

    # Apply book-level candidate cap (0.5% in safe, 1.0% in all)
    cap_ratio = 0.005 if mode == "safe" else 0.01
    max_book_cands = max(5, int(total_segments * cap_ratio)) if total_segments > 0 else 5
    return selected_candidates[:max_book_cands]
