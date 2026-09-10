"""List marker extraction, deduplication, and style inference (M11/Appendix M12-M16)."""

import re
from collections import Counter

from book2epub.ir.models import (
    Inline,
    ListBlock,
    SourceTextSegment,
    Text,
    replace_source_segment_text,
)

from .models import MarkerStyle

# Unordered marker pattern (including optional duplicated secondary marker, e.g. "• - ")
_UNORDERED_MARKER_PATTERN = re.compile(
    r"^[ \t]*([•●○◦▪■□‣・*+–—]|-(?!\d))([ \t]*([•●○◦▪■□‣・*+–—]|-(?!\d)))*[ \t]+"
)

# Ordered marker patterns
_ORDERED_DECIMAL_PATTERN = re.compile(
    r"^[ \t]*(\d{1,3}[\.\)]|\(\d{1,3}\)|[①-⑳]|[一二三四五六七八九十百]+[、\.])[ \t]+"
)
_ORDERED_ROMAN_PATTERN = re.compile(
    r"^[ \t]*([ivxlcdmIVXLCDM]{1,6}[\.\)]|\([ivxlcdmIVXLCDM]{1,6}\))[ \t]+"
)
_ORDERED_ALPHA_PATTERN = re.compile(
    r"^[ \t]*([a-zA-Z][\.\)]|\([a-zA-Z]\))[ \t]+"
)


def classify_single_marker(marker_str: str) -> MarkerStyle:
    """Classify a raw marker string into its typography family (Appendix M14)."""
    m = marker_str.strip()
    if not m:
        return "auto"

    # Unordered families
    if any(c in m for c in "•●・*+"):
        return "disc"
    if any(c in m for c in "○◦"):
        return "circle"
    if any(c in m for c in "▪■□"):
        return "square"
    if any(c in m for c in "-–—"):
        return "dash"

    # Roman numerals
    if _ORDERED_ROMAN_PATTERN.match(m + " "):
        return "roman"

    # Decimal numerals
    if _ORDERED_DECIMAL_PATTERN.match(m + " "):
        return "decimal"

    # Alphabetical letters
    if _ORDERED_ALPHA_PATTERN.match(m + " "):
        return "alpha"

    return "auto"


def infer_majority_marker_style(markers: list[str | None]) -> MarkerStyle:
    """Infer ListBlock.marker_style from majority recognized source-marker family."""
    styles: list[MarkerStyle] = []
    for m in markers:
        if m:
            st = classify_single_marker(m)
            if st != "auto":
                styles.append(st)

    if not styles:
        return "auto"

    counts = Counter(styles)
    top_style, top_count = counts.most_common(1)[0]
    # In case of tie between distinct non-auto styles, top_count check
    ties = [s for s, c in counts.items() if c == top_count]
    if len(ties) > 1:
        return "auto"
    return top_style


def extract_item_leading_marker(
    item_inlines: list[Inline],
) -> tuple[list[Inline], str | None]:
    """
    Inspect the first Text inline in an item.
    If a recognized leading list marker is present, remove exactly marker + immediate whitespace.
    Updates Text.text and trims first SourceTextSegment accordingly.
    Returns (updated_inlines, raw_marker_string).
    """
    if not item_inlines:
        return item_inlines, None

    first_inline = item_inlines[0]
    if not isinstance(first_inline, Text) or not first_inline.text:
        return item_inlines, None

    raw_text = first_inline.text
    match = None

    # Check unordered markers first (including compound e.g. "• - ")
    m_unord = _UNORDERED_MARKER_PATTERN.match(raw_text)
    if m_unord:
        match = m_unord
    else:
        # Check ordered Roman, Decimal, Alpha
        for pat in (_ORDERED_ROMAN_PATTERN, _ORDERED_DECIMAL_PATTERN, _ORDERED_ALPHA_PATTERN):
            m_ord = pat.match(raw_text)
            if m_ord:
                match = m_ord
                break

    if not match:
        return item_inlines, None

    matched_full = match.group(0)
    matched_marker = match.group(1).strip()
    # If compound marker (e.g. "• -"), extract full stripped marker symbol
    if len(matched_full.strip()) > len(matched_marker):
        matched_marker = matched_full.strip()

    remaining_text = raw_text[len(matched_full):]

    # Update first Text inline
    updated_inlines = list(item_inlines)
    updated_segments: list[SourceTextSegment] = []

    if first_inline.source_segments:
        # Trim from first segment
        prefix_to_trim = len(matched_full)
        for i, seg in enumerate(first_inline.source_segments):
            if prefix_to_trim > 0:
                if len(seg.text) <= prefix_to_trim:
                    prefix_to_trim -= len(seg.text)
                    # Dropped entire segment prefix
                    continue
                else:
                    new_seg_text = seg.text[prefix_to_trim:]
                    prefix_to_trim = 0
                    updated_segments.append(replace_source_segment_text(seg, new_seg_text))
            else:
                updated_segments.append(seg)

    new_text_inline = first_inline.model_copy(
        update={"text": remaining_text, "source_segments": updated_segments}
    )
    updated_inlines[0] = new_text_inline
    return updated_inlines, matched_marker


def normalize_list_block(block: ListBlock) -> tuple[ListBlock, int]:
    """
    Extract markers from items in ListBlock, populate source_markers,
    and infer marker_style if unset/auto.
    Returns (normalized_block, count_extracted).
    """
    new_items: list[list[Inline]] = []
    source_markers: list[str | None] = []
    extracted_count = 0

    for item in block.items:
        new_inlines, marker = extract_item_leading_marker(item)
        new_items.append(new_inlines)
        source_markers.append(marker)
        if marker is not None:
            extracted_count += 1

    inferred_style = infer_majority_marker_style(source_markers)
    final_style = block.marker_style if block.marker_style != "auto" else inferred_style

    normalized = block.model_copy(
        update={
            "items": new_items,
            "source_markers": source_markers,
            "marker_style": final_style,
        }
    )
    return normalized, extracted_count
