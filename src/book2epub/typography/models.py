"""Data models for Japanese typography, whitespace reconstruction, and list normalization
(M11/Appendix M).
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class CharClass(StrEnum):
    """Character classification for typography and boundary spacing rules (Appendix M3)."""

    CJK_HAN_KANA = "cjk_han_kana"
    LATIN_ASCII_WORD = "latin_ascii_word"
    DIGIT = "digit"
    OPEN_JP_PUNCT = "open_jp_punct"
    CLOSE_JP_PUNCT = "close_jp_punct"
    OPEN_ASCII_PUNCT = "open_ascii_punct"
    CLOSE_ASCII_PUNCT = "close_ascii_punct"
    WHITESPACE = "whitespace"
    OTHER = "other"


class BoundaryType(StrEnum):
    """Boundary class between adjacent text segments (Appendix M2, M6)."""

    START = "start"
    SAME_LINE = "same_line"
    NEW_LINE = "new_line"
    PAGE_CONTINUATION = "page_continuation"
    UNKNOWN = "unknown"


MarkerStyle = Literal[
    "auto",
    "disc",
    "circle",
    "square",
    "dash",
    "decimal",
    "alpha",
    "roman",
]


class TypographyChangeRecord(BaseModel):
    """Auditable record of a typography normalization edit (capped at 80 codepoints)."""

    block_id: str
    change_type: str
    before_excerpt: str
    after_excerpt: str


class NormalizationReport(BaseModel):
    """Normalization report written to presentation/normalization-report.json (Appendix M17)."""

    source_segment_reconstructions: int = 0
    spaces_inserted_same_line_bbox: int = 0
    spaces_removed_vs_legacy_join: int = 0
    new_line_spaces_inserted: int = 0
    dehyphenations: int = 0
    leading_print_indents_normalized: int = 0
    list_markers_extracted: int = 0
    marker_style_distribution: dict[str, int] = Field(default_factory=dict)
    fallback_text_nodes_without_segments: int = 0
    changes: list[TypographyChangeRecord] = Field(default_factory=list)

    def record_change(
        self,
        block_id: str,
        change_type: str,
        before: str,
        after: str,
        max_len: int = 80,
    ) -> None:
        """Add bounded change excerpt to changes list."""
        b_sub = before[:max_len] + ("..." if len(before) > max_len else "")
        a_sub = after[:max_len] + ("..." if len(after) > max_len else "")
        self.changes.append(
            TypographyChangeRecord(
                block_id=block_id,
                change_type=change_type,
                before_excerpt=b_sub,
                after_excerpt=a_sub,
            )
        )
