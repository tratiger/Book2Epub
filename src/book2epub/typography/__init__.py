"""Japanese typography, whitespace reconstruction, and list normalization package (M11)."""

from .boundaries import classify_boundary
from .dehyphenation import try_dehyphenate
from .japanese import classify_char, is_cjk_char, is_close_punct, is_open_punct
from .lists import (
    extract_item_leading_marker,
    infer_majority_marker_style,
    normalize_list_block,
)
from .models import (
    BoundaryType,
    CharClass,
    MarkerStyle,
    NormalizationReport,
    TypographyChangeRecord,
)
from .normalize import typography_normalize_bookir
from .report import save_normalization_report
from .spacing import collapse_intra_segment_spaces, decide_inter_segment_separator

__all__ = [
    "BoundaryType",
    "CharClass",
    "MarkerStyle",
    "NormalizationReport",
    "TypographyChangeRecord",
    "classify_boundary",
    "classify_char",
    "collapse_intra_segment_spaces",
    "decide_inter_segment_separator",
    "extract_item_leading_marker",
    "infer_majority_marker_style",
    "is_cjk_char",
    "is_close_punct",
    "is_open_punct",
    "normalize_list_block",
    "save_normalization_report",
    "try_dehyphenate",
    "typography_normalize_bookir",
]
