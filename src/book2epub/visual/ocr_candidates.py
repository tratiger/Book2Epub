"""OCR correction candidate detection and conservative gating (M9 Section 10, Appendix K7)."""

import logging
import re
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel

from book2epub.ir.models import (
    Aside,
    Block,
    BlockQuote,
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
    Table,
    Text,
)
from book2epub.semantic.hashing import compute_text_sha256

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


ContentRole = Literal[
    "prose",
    "caption",
    "footnote",
    "code_body",
    "preformatted_body",
    "math",
    "table",
    "unknown",
]


class EligibleSegment(BaseModel):
    """An OCR-eligible text segment in the BookIR tree."""

    block_id: str
    segment_id: str
    page_idx: int
    bbox: list[float] | None = None
    text: str
    text_sha256: str
    is_code: bool = False
    is_synthetic: bool = False
    source_span_type: str | None = None
    content_role: ContentRole = "prose"


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
    content_role: ContentRole = "prose"


def iter_ocr_eligible_segments(
    blocks: list[Block],
    mode: Literal["off", "safe", "all"],
) -> Iterator[EligibleSegment]:
    """
    Recursively traverse BookIR blocks and yield all text segments eligible for OCR review.
    Excludes Math (DisplayMath, InlineMath) and Table HTML.
    Supports nested prose: Paragraph, Heading, ListItem, Callout, Aside, Footnote,
    Captions, DefinitionList, Example/Exercise, BlockQuote, etc.
    """
    if mode == "off":
        return

    def _traverse_inlines(
        inlines: list[Inline],
        block_id: str,
        is_caption: bool = False,
        is_footnote: bool = False,
    ) -> Iterator[EligibleSegment]:
        role: ContentRole = "caption" if is_caption else ("footnote" if is_footnote else "prose")
        for inl in inlines:
            if isinstance(inl, Text):
                for seg in inl.source_segments:
                    seg_bbox = (
                        [seg.bbox.x0, seg.bbox.y0, seg.bbox.x1, seg.bbox.y1]
                        if seg.bbox
                        else None
                    )
                    yield EligibleSegment(
                        block_id=block_id,
                        segment_id=seg.segment_id,
                        page_idx=seg.page_idx,
                        bbox=seg_bbox,
                        text=seg.text,
                        text_sha256=seg.text_sha256,
                        is_code=False,
                        is_synthetic=False,
                        source_span_type="caption" if is_caption else (
                            "footnote" if is_footnote else seg.source_span_type
                        ),
                        content_role=role,
                    )
            elif isinstance(inl, Hyperlink):
                yield from _traverse_inlines(
                    inl.children,
                    block_id,
                    is_caption=is_caption,
                    is_footnote=is_footnote,
                )
            # InlineMath, LineBreak, PageBoundary are strictly skipped

    def _traverse_blocks(blks: list[Block]) -> Iterator[EligibleSegment]:
        for blk in blks:
            if isinstance(blk, DisplayMath):
                # Math source text is strictly immutable in M6-M12
                continue

            if isinstance(blk, Table):
                # Table HTML is strictly immutable; captions and footnotes may be reviewed
                yield from _traverse_inlines(blk.caption, blk.id, is_caption=True)
                yield from _traverse_inlines(blk.footnotes, blk.id, is_footnote=True)
                continue

            if isinstance(blk, (Figure, Chart)):
                yield from _traverse_inlines(blk.caption, blk.id, is_caption=True)
                yield from _traverse_inlines(blk.footnotes, blk.id, is_footnote=True)
                continue

            if isinstance(blk, Footnote):
                yield from _traverse_inlines(blk.inlines, blk.id, is_footnote=True)
                continue

            if isinstance(blk, (Paragraph, Heading, Aside)):
                yield from _traverse_inlines(blk.inlines, blk.id)
                continue

            if isinstance(blk, (CodeBlock, PreformattedBlock)):
                yield from _traverse_inlines(blk.caption, blk.id, is_caption=True)
                yield from _traverse_inlines(blk.footnotes, blk.id, is_footnote=True)
                if mode == "all":
                    text = getattr(blk, "text", "")
                    if text:
                        sources = blk.sources
                        page = sources[0].page_idx if sources else 0
                        src_box = sources[0].bbox if sources and sources[0].bbox else None
                        code_bbox = (
                            [src_box.x0, src_box.y0, src_box.x1, src_box.y1]
                            if src_box
                            else None
                        )
                        c_role: ContentRole = (
                            "code_body" if isinstance(blk, CodeBlock) else "preformatted_body"
                        )
                        yield EligibleSegment(
                            block_id=blk.id,
                            segment_id=f"{blk.id}-seg-0",
                            page_idx=page,
                            bbox=code_bbox,
                            text=text,
                            text_sha256=compute_text_sha256(text),
                            is_code=True,
                            is_synthetic=True,
                            source_span_type="code",
                            content_role=c_role,
                        )
                continue

            if isinstance(blk, Callout):
                yield from _traverse_inlines(blk.title, blk.id, is_caption=True)
                yield from _traverse_blocks(blk.blocks)
                continue

            if isinstance(blk, BlockQuote):
                yield from _traverse_inlines(blk.attribution, blk.id, is_caption=True)
                yield from _traverse_blocks(blk.blocks)
                continue

            if isinstance(blk, (ExampleBlock, ExerciseBlock)):
                yield from _traverse_inlines(blk.label, blk.id, is_caption=True)
                yield from _traverse_blocks(blk.blocks)
                continue

            if isinstance(blk, DefinitionList):
                for item in blk.items:
                    yield from _traverse_inlines(item.term, blk.id)
                    for d in item.definitions:
                        yield from _traverse_inlines(d, blk.id)
                continue

            if isinstance(blk, (ListBlock, IndexBlock)):
                for item_inlines in blk.items:
                    yield from _traverse_inlines(item_inlines, blk.id)
                continue

    yield from _traverse_blocks(blocks)


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
    ocr_recommended_block_ids: set[str] | None = None,
    explicit_candidate_keys: set[tuple[str, str]] | None = None,
    max_per_page: int = 3,
) -> list[OCRCandidate]:
    """
    Detect OCR candidate segments from BookIR blocks without modifying text.
    Enforces mode filtering, exclusions, and per-page / book-level caps.
    Maps visual recommendations on prose blocks to their real SourceTextSegments.
    """
    if mode == "off":
        return []

    recommended_blocks = ocr_recommended_block_ids or set()
    explicit_keys = explicit_candidate_keys or set()

    candidates_by_page: dict[int, list[OCRCandidate]] = {}
    eligible_segments = list(iter_ocr_eligible_segments(blocks, mode))
    total_segments = len(eligible_segments)

    for seg in eligible_segments:
        # Segment is explicitly flagged if its block was recommended by visual review
        # or if its (block_id, segment_id) was specified in explicit_keys
        explicit = (seg.block_id in recommended_blocks) or (
            (seg.block_id, seg.segment_id) in explicit_keys
        )
        reason = _scan_segment_for_ocr_anomaly(
            seg.text, is_code=seg.is_code, explicitly_flagged=explicit
        )
        if reason:
            cand = OCRCandidate(
                block_id=seg.block_id,
                segment_id=seg.segment_id,
                page_idx=seg.page_idx,
                bbox=seg.bbox,
                old_text=seg.text,
                old_text_sha256=seg.text_sha256,
                is_code=seg.is_code,
                reason=reason,
                content_role=seg.content_role,
            )
            candidates_by_page.setdefault(seg.page_idx, []).append(cand)

    # Apply per-page caps (max 3 candidates per page per Appendix K7)
    selected_candidates: list[OCRCandidate] = []
    for page in sorted(candidates_by_page.keys()):
        page_cands = candidates_by_page[page]
        selected_candidates.extend(page_cands[:max_per_page])

    # Apply book-level candidate cap (0.5% in safe, 1.0% in all)
    cap_ratio = 0.005 if mode == "safe" else 0.01
    max_book_cands = max(5, int(total_segments * cap_ratio)) if total_segments > 0 else 5
    return selected_candidates[:max_book_cands]

