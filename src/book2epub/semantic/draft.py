from typing import Literal

from book2epub.semantic.models import (
    DraftBlock,
    DraftGeometry,
    SemanticDraftBook,
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)

PREVIEW_MAX_CHARS = 4_000
PREVIEW_HEAD_CHARS = 2_000
PREVIEW_TAIL_CHARS = 2_000


def _truncate_preview(text: str | None) -> tuple[str | None, bool]:
    """
    Deterministically truncate preview strings to 4,000 codepoints (preserve first 2,000
    and last 2,000 if truncating) and report if truncation occurred (M6 spec Section 7).
    """
    if not text:
        return None, False
    if len(text) <= PREVIEW_MAX_CHARS:
        return text, False
    head = text[:PREVIEW_HEAD_CHARS]
    tail = text[-PREVIEW_TAIL_CHARS:]
    return f"{head}\n...[truncated]...\n{tail}", True


def _compute_draft_geometry(ev_block: SemanticEvidenceBlock) -> DraftGeometry:
    """Compute normalized geometry summary for draft block."""
    page_w = ev_block.page_size[0] if len(ev_block.page_size) >= 1 else 0.0
    page_h = ev_block.page_size[1] if len(ev_block.page_size) >= 2 else 0.0

    line_count = len(ev_block.line_segments)
    span_count = sum(len(line.segments) for line in ev_block.line_segments)

    if not ev_block.bbox or page_w <= 0.0 or page_h <= 0.0:
        return DraftGeometry(
            line_count=line_count,
            span_count=span_count,
        )

    x0, y0, x1, y1 = ev_block.bbox
    w = max(0.0, x1 - x0)
    h = max(0.0, y1 - y0)
    w_ratio = min(1.0, max(0.0, w / page_w))
    h_ratio = min(1.0, max(0.0, h / page_h))

    cx = (x0 + x1) / 2.0
    rel_cx = cx / page_w
    alignment: Literal["left", "center", "right"]
    if rel_cx < 0.4:
        alignment = "left"
    elif rel_cx > 0.6:
        alignment = "right"
    else:
        alignment = "center"

    is_full_width = w_ratio >= 0.85

    return DraftGeometry(
        bbox_width_ratio=round(w_ratio, 3),
        bbox_height_ratio=round(h_ratio, 3),
        alignment_hint=alignment,
        is_full_width=is_full_width,
        line_count=line_count,
        span_count=span_count,
    )


def build_semantic_draft(
    evidence_book: SemanticEvidenceBook,
    book_id: str = "book",
) -> SemanticDraftBook:
    """
    Build a compact model-facing SemanticDraftBook from SemanticEvidenceBook
    (M6 spec Section 7, Appendix H4).
    """
    draft_blocks: list[DraftBlock] = []

    for ev in evidence_book.blocks:
        plain_prev, trunc_plain = _truncate_preview(ev.plain_text)
        pre_prev, trunc_pre = _truncate_preview(ev.preformatted_text)
        cap_prev, _ = _truncate_preview(ev.caption_text)

        is_truncated = trunc_plain or trunc_pre

        # Normalized bbox [x0/w, y0/h, x1/w, y1/h] if page size available
        bbox_norm = None
        if ev.bbox and len(ev.page_size) >= 2 and ev.page_size[0] > 0 and ev.page_size[1] > 0:
            pw, ph = ev.page_size[0], ev.page_size[1]
            bbox_norm = [
                round(ev.bbox[0] / pw, 4),
                round(ev.bbox[1] / ph, 4),
                round(ev.bbox[2] / pw, 4),
                round(ev.bbox[3] / ph, 4),
            ]

        # Table summary
        table_summary = None
        if ev.table_html:
            table_summary = f"Structured table with {ev.table_html.count('<tr')} rows"

        draft_b = DraftBlock(
            block_id=ev.block_id,
            order_index=ev.order_index,
            page_idx=ev.page_idx,
            pages=ev.page_indices,
            source_type=ev.source_type,
            mineru_type=ev.source_type,
            current_kind=ev.current_kind,
            current_subtype=ev.current_subtype,
            plain_text=plain_prev,
            text_preview=plain_prev,
            preformatted_preview=pre_prev,
            table_summary=table_summary,
            has_table_html=ev.table_html_available,
            bbox_normalized=bbox_norm,
            caption_text=ev.caption_text,
            caption_preview=cap_prev,
            footnote_text=ev.footnote_text,
            allowed_targets=ev.allowed_targets,
            flags=ev.flags,
            geometry=_compute_draft_geometry(ev),
            content_sha256=ev.content_sha256,
            preview_truncated=is_truncated,
        )
        draft_blocks.append(draft_b)

    return SemanticDraftBook(
        book_id=book_id,
        blocks=draft_blocks,
    )
