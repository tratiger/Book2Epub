"""Segment boundary classification for whitespace reconstruction (M11/Appendix M2)."""

from book2epub.ir.models import SourceTextSegment

from .models import BoundaryType

_BOUNDARY_MAP = {
    "start": BoundaryType.START,
    "same_line": BoundaryType.SAME_LINE,
    "new_line": BoundaryType.NEW_LINE,
    "page_continuation": BoundaryType.PAGE_CONTINUATION,
    "unknown": BoundaryType.UNKNOWN,
}


def classify_boundary(
    seg_a: SourceTextSegment | None,
    seg_b: SourceTextSegment,
) -> BoundaryType:
    """
    Classify the boundary transition before seg_b.
    Uses seg_b.boundary_before metadata first, falling back to line_index/bbox evidence.
    """
    if seg_a is None:
        return BoundaryType.START

    meta_bound = getattr(seg_b, "boundary_before", None)
    if meta_bound in _BOUNDARY_MAP and meta_bound != "unknown":
        return _BOUNDARY_MAP[meta_bound]

    # Cross-page boundary
    if seg_b.page_idx != seg_a.page_idx:
        return BoundaryType.PAGE_CONTINUATION

    # Same page line_index comparison
    if seg_a.line_index is not None and seg_b.line_index is not None:
        if seg_a.line_index == seg_b.line_index:
            return BoundaryType.SAME_LINE
        return BoundaryType.NEW_LINE

    # Bounding box vertical comparison fallback
    if seg_a.bbox and seg_b.bbox:
        # If B is clearly lower than A (allowing minor baseline jitter)
        y_diff = seg_b.bbox.center_y - seg_a.bbox.center_y
        line_height = max(seg_a.bbox.height, seg_b.bbox.height, 10.0)
        if abs(y_diff) > 0.5 * line_height:
            return BoundaryType.NEW_LINE
        return BoundaryType.SAME_LINE

    return BoundaryType.UNKNOWN
