"""Normalization layer: cross-page joins, page labels, layout hints, and heading leveling."""

import logging
import re
from typing import Literal

from book2epub.ir.models import (
    Block,
    BookIR,
    Chart,
    Figure,
    Heading,
    IRWarning,
    LayoutHint,
    PageBoundary,
    PageBreak,
    Paragraph,
    Table,
    Text,
)
from book2epub.ir.page_labels import compute_validated_page_labels

logger = logging.getLogger(__name__)

SENTENCE_TERMINALS = {".", "!", "?", "。", "！", "？", "」", "』"}
CHAPTER_REGEX = re.compile(
    r"^(?:chapter\s+\d+|ch\.\s*\d+|第\s*[0-9一二三四五六七八九十百千]+\s*章|\d+(?:\.\d+)*\s+)",
    re.IGNORECASE,
)
DOTTED_HEADING_REGEX = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)*)\s+")


def infer_heading_level(heading_text: str) -> int | None:
    """Deterministically infer heading level from title text patterns."""
    text = heading_text.strip()
    if CHAPTER_REGEX.match(text):
        return 1

    m = DOTTED_HEADING_REGEX.match(text)
    if m:
        parts = m.group(1).split(".")
        return min(6, len(parts))

    return None


def compute_layout_hint(block: Block, page_width: float) -> LayoutHint | None:
    """
    Compute relative layout intent from bounding box and page width.

    Width classes:
      - small: r <= 0.36
      - medium: 0.36 < r <= 0.72
      - large: r > 0.72

    Alignment:
      - center: |d| <= 0.07
      - left: d < -0.07
      - right: d > 0.07
    """
    if not block.sources or not block.sources[0].bbox:
        return None

    bbox = block.sources[0].bbox
    if page_width <= 0:
        return None

    w = bbox.width
    r = w / page_width

    size_class: Literal["small", "medium", "large"]
    if r <= 0.36:
        size_class = "small"
    elif r <= 0.72:
        size_class = "medium"
    else:
        size_class = "large"

    # Alignment class
    cx = (bbox.x0 + bbox.x1) / 2.0
    d = (cx - page_width / 2.0) / page_width

    alignment: Literal["left", "center", "right"]
    if abs(d) <= 0.07:
        alignment = "center"
    elif d < -0.07:
        alignment = "left"
    else:
        alignment = "right"

    return LayoutHint(
        width_ratio=round(r, 4),
        size_class=size_class,
        alignment=alignment,
        source_bbox=bbox,
    )


def should_merge_paragraphs(
    p1: Paragraph,
    p2: Paragraph,
    page_width: float,
) -> bool:
    """
    Check if two adjacent paragraphs across a page boundary should be merged.

    Enforces all conditions from M2:
    - neither ends in sentence terminal (. ! ? 。 ！ ？ 」 』) or colon
    - next begins with lowercase Latin or continuation punctuation
    - left/right bbox edges differ by <= 8% of page width
    """
    if not p1.inlines or not p2.inlines:
        return False

    first_text = ""
    for inline in p1.inlines:
        if isinstance(inline, Text):
            first_text += inline.text
    first_text = first_text.strip()

    second_text = ""
    for inline in p2.inlines:
        if isinstance(inline, Text):
            second_text += inline.text
    second_text = second_text.strip()

    if not first_text or not second_text:
        return False

    # Check terminal
    if first_text[-1] in SENTENCE_TERMINALS or first_text.endswith(":"):
        return False

    # Check start of second
    c2 = second_text[0]
    is_continuation = c2.islower() and c2.isascii() or c2 in (",", "、", "，")
    if not is_continuation and not first_text.endswith("-"):
        return False

    # Check bbox alignment
    b1 = p1.sources[0].bbox if p1.sources and p1.sources[0].bbox else None
    b2 = p2.sources[0].bbox if p2.sources and p2.sources[0].bbox else None

    if b1 and b2 and page_width > 0:
        left_diff = abs(b1.x0 - b2.x0) / page_width
        right_diff = abs(b1.x1 - b2.x1) / page_width
        if left_diff > 0.08 or right_diff > 0.08:
            return False

    return True


def normalize_bookir(
    bookir: BookIR,
    raw_page_number_texts: list[str | None] | None = None,
) -> BookIR:
    """
    Apply semantic normalization passes to BookIR:
    1. Validate page labels and update SourcePage metadata.
    2. Infer heading levels when missing.
    3. Calculate LayoutHints for figures, charts, tables.
    4. Insert PageBreaks and perform conservative cross-page paragraph merges with PageBoundary.
    """
    pages_by_idx = {p.page_idx: p for p in bookir.source.pages}

    # 1. Page labels
    if raw_page_number_texts:
        validated = compute_validated_page_labels(raw_page_number_texts)
        for idx, (label, conf) in enumerate(validated):
            if idx in pages_by_idx:
                pages_by_idx[idx].printed_label = label
                pages_by_idx[idx].printed_label_confidence = conf

    # 2. Heading levels and LayoutHints
    for block in bookir.blocks:
        if isinstance(block, Heading) and block.level is None:
            heading_text = " ".join(i.text for i in block.inlines if isinstance(i, Text))
            inferred = infer_heading_level(heading_text)
            if inferred is not None:
                block.level = inferred
            else:
                bookir.warnings.append(
                    IRWarning(
                        code="HEADING_LEVEL_UNKNOWN",
                        message=(
                            f"Heading '{heading_text[:40]}' has unknown level; "
                            "renderer will default to h2."
                        ),
                        page_idx=block.sources[0].page_idx if block.sources else None,
                    )
                )

        if isinstance(block, (Figure, Chart, Table)):
            pidx = block.sources[0].page_idx if block.sources else 0
            page = pages_by_idx.get(pidx)
            pw = page.width if page else 1000.0
            block.layout_hint = compute_layout_hint(block, pw)

    # 3. PageBreaks and Cross-page merges
    # Group blocks by page_idx
    blocks_by_page: dict[int, list[Block]] = {}
    for block in bookir.blocks:
        pidx = block.sources[0].page_idx if block.sources else 0
        blocks_by_page.setdefault(pidx, []).append(block)

    normalized_blocks: list[Block] = []
    sorted_page_indices = sorted(pages_by_idx.keys())

    for i, pidx in enumerate(sorted_page_indices):
        page_blocks = blocks_by_page.get(pidx, [])
        page = pages_by_idx[pidx]
        pb_label = page.printed_label or f"scan-{pidx + 1}"

        if i == 0:
            # First page opener: add initial PageBreak
            normalized_blocks.append(
                PageBreak(id=f"page-{pidx:05d}", page_idx=pidx, label=pb_label)
            )
            normalized_blocks.extend(page_blocks)
            continue

        # Check for cross-page paragraph merge between last block of previous and first of current
        last_prev = normalized_blocks[-1] if normalized_blocks else None
        first_curr = page_blocks[0] if page_blocks else None

        merged = False
        if isinstance(last_prev, Paragraph) and isinstance(first_curr, Paragraph):
            if should_merge_paragraphs(last_prev, first_curr, page.width):
                # Perform merge
                boundary = PageBoundary(page_idx=pidx, label=pb_label)
                merged_inlines = last_prev.inlines + [boundary] + first_curr.inlines
                last_prev.inlines = merged_inlines
                last_prev.sources.extend(first_curr.sources)
                # Remaining page blocks (excluding the merged first one)
                normalized_blocks.extend(page_blocks[1:])
                merged = True

        if not merged:
            normalized_blocks.append(
                PageBreak(id=f"page-{pidx:05d}", page_idx=pidx, label=pb_label)
            )
            normalized_blocks.extend(page_blocks)

    bookir.blocks = normalized_blocks
    return bookir
