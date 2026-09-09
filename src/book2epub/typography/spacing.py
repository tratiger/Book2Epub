"""Deterministic spacing rules and whitespace reconstruction (M11/Appendix M4-M7)."""

import re
import statistics

from book2epub.ir.models import SourceTextSegment

from .dehyphenation import try_dehyphenate
from .japanese import (
    classify_char,
    is_cjk_char,
    is_close_punct,
    is_open_punct,
)
from .models import BoundaryType, CharClass

_MULTIPLE_SPACES_PATTERN = re.compile(r"[ ]{2,}")


def collapse_intra_segment_spaces(text: str) -> tuple[str, int]:
    """
    Collapse 2+ consecutive ordinary ASCII spaces down to 1 in prose text.
    Preserves non-breaking spaces (U+00A0) and ideographic spaces (U+3000).
    Returns (collapsed_text, count_of_collapsed_runs).
    """
    matches = list(_MULTIPLE_SPACES_PATTERN.finditer(text))
    if not matches:
        return text, 0
    collapsed = _MULTIPLE_SPACES_PATTERN.sub(" ", text)
    return collapsed, len(matches)


def count_nonspace_chars(text: str) -> int:
    """Return count of non-whitespace characters."""
    return sum(1 for ch in text if not ch.isspace())


def decide_inter_segment_separator(
    seg_a: SourceTextSegment,
    seg_b: SourceTextSegment,
    boundary: BoundaryType,
) -> tuple[str, str, str, bool, str]:
    """
    Decide separator and boundary text adjustments between adjacent segments.

    Returns:
    (adjusted_text_a, separator, adjusted_text_b, is_dehyphenation, reason)
    """
    text_a = seg_a.text
    text_b = seg_b.text

    # 1. Newline / Page continuation: Latin dehyphenation check (M8)
    if boundary in (BoundaryType.NEW_LINE, BoundaryType.PAGE_CONTINUATION):
        dehyphen_a, dehyphen_b, did_dehyphen = try_dehyphenate(text_a, text_b)
        if did_dehyphen:
            return dehyphen_a, "", dehyphen_b, True, "dehyphenation"

    # 2. Explicit source whitespace check (M4)
    has_explicit_space = (
        text_a.endswith(" ")
        or text_a.endswith("\t")
        or text_b.startswith(" ")
        or text_b.startswith("\t")
    )
    trimmed_a = text_a.rstrip(" \t")
    trimmed_b = text_b.lstrip(" \t")

    last_char = trimmed_a[-1] if trimmed_a else ""
    first_char = trimmed_b[0] if trimmed_b else ""

    if has_explicit_space:
        # Punctuation suppresses preceding/succeeding space (M4, M7)
        if is_close_punct(first_char) or is_open_punct(last_char):
            return trimmed_a, "", trimmed_b, False, "explicit_space_suppressed_by_punct"
        return trimmed_a, " ", trimmed_b, False, "explicit_source_space"

    # 3. Same-line bbox gap inference (M5)
    if boundary == BoundaryType.SAME_LINE:
        if (
            seg_a.bbox is not None
            and seg_b.bbox is not None
            and seg_a.bbox.width > 0
            and seg_b.bbox.width > 0
        ):
            gap = seg_b.bbox.x0 - seg_a.bbox.x1
            chars_a = max(1, count_nonspace_chars(text_a))
            chars_b = max(1, count_nonspace_chars(text_b))
            char_w_a = seg_a.bbox.width / chars_a
            char_w_b = seg_b.bbox.width / chars_b
            valid_widths = [w for w in (char_w_a, char_w_b) if w > 0]
            if valid_widths:
                est_char_w = statistics.median(valid_widths)
                if gap > 0.55 * est_char_w:
                    if is_close_punct(first_char) or is_open_punct(last_char):
                        return trimmed_a, "", trimmed_b, False, "same_line_bbox_gap_punct"
                    return trimmed_a, " ", trimmed_b, False, "same_line_bbox_gap"
                if gap >= -0.2 * est_char_w:
                    return trimmed_a, "", trimmed_b, False, "same_line_bbox_no_gap"

    # 4. Language & punctuation boundary rules (M6, M7)
    if not last_char or not first_char:
        return trimmed_a, "", trimmed_b, False, "empty_boundary"

    # Punctuation rules
    if is_close_punct(first_char):
        return trimmed_a, "", trimmed_b, False, "close_punct"
    if is_open_punct(last_char):
        return trimmed_a, "", trimmed_b, False, "open_punct"

    # ASCII punctuation after sentence/phrase boundary followed by Latin word at newline
    if (
        boundary in (BoundaryType.NEW_LINE, BoundaryType.PAGE_CONTINUATION)
        and last_char in (",", ";", ":", ".", "!", "?")
        and classify_char(first_char) == CharClass.LATIN_ASCII_WORD
    ):
        return trimmed_a, " ", trimmed_b, False, "ascii_sentence_punct_newline"

    # CJK boundary matrix (M6)
    last_is_cjk = is_cjk_char(last_char)
    first_is_cjk = is_cjk_char(first_char)

    if last_is_cjk and first_is_cjk:
        return trimmed_a, "", trimmed_b, False, "cjk_cjk"

    last_class = classify_char(last_char)
    first_class = classify_char(first_char)

    # CJK + Latin/Digit or Latin/Digit + CJK -> no space
    if (last_is_cjk and first_class in (CharClass.LATIN_ASCII_WORD, CharClass.DIGIT)) or (
        last_class in (CharClass.LATIN_ASCII_WORD, CharClass.DIGIT) and first_is_cjk
    ):
        return trimmed_a, "", trimmed_b, False, "cjk_latin_no_space"

    # Latin word + Latin word -> one space (M6)
    if (
        last_class == CharClass.LATIN_ASCII_WORD
        and first_class == CharClass.LATIN_ASCII_WORD
    ):
        return trimmed_a, " ", trimmed_b, False, "latin_latin_space"

    return trimmed_a, "", trimmed_b, False, "default_no_space"
