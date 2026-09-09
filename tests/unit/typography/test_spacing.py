"""Unit tests for whitespace reconstruction, bbox gap inference, and dehyphenation
(M11/Appendix M4-M8).
"""

from book2epub.ir.models import BBox, SourceTextSegment
from book2epub.typography.dehyphenation import try_dehyphenate
from book2epub.typography.models import BoundaryType
from book2epub.typography.spacing import (
    collapse_intra_segment_spaces,
    decide_inter_segment_separator,
)


def _make_seg(
    text: str,
    bbox: BBox | None = None,
    boundary_before: str = "new_line",
    page_idx: int = 0,
) -> SourceTextSegment:
    return SourceTextSegment(
        segment_id="seg-1",
        page_idx=page_idx,
        block_id="b-1",
        text=text,
        bbox=bbox,
        boundary_before=boundary_before,  # type: ignore[arg-type]
        text_sha256="dummy",
    )


def test_japanese_latin_newline_spacing() -> None:
    """Verify Japanese-Latin and CJK-CJK newlines have no space, while Latin-Latin has a space."""
    # 1. "これは" + newline + "Linux" -> "これはLinux"
    s1 = _make_seg("これは")
    s2 = _make_seg("Linux")
    a, sep, b, dehy, _ = decide_inter_segment_separator(s1, s2, BoundaryType.NEW_LINE)
    assert a == "これは"
    assert sep == ""
    assert b == "Linux"
    assert not dehy

    # 2. "Linux" + newline + "カーネル" -> "Linuxカーネル"
    s3 = _make_seg("Linux")
    s4 = _make_seg("カーネル")
    a, sep, b, dehy, _ = decide_inter_segment_separator(s3, s4, BoundaryType.NEW_LINE)
    assert a == "Linux"
    assert sep == ""
    assert b == "カーネル"
    assert not dehy

    # 3. "Unix" + newline + "system" -> "Unix system"
    s5 = _make_seg("Unix")
    s6 = _make_seg("system")
    a, sep, b, dehy, _ = decide_inter_segment_separator(s5, s6, BoundaryType.NEW_LINE)
    assert a == "Unix"
    assert sep == " "
    assert b == "system"
    assert not dehy

    # 4. "日本語" + newline + "文章" -> "日本語文章"
    s7 = _make_seg("日本語")
    s8 = _make_seg("文章")
    a, sep, b, dehy, _ = decide_inter_segment_separator(s7, s8, BoundaryType.NEW_LINE)
    assert a == "日本語"
    assert sep == ""
    assert b == "文章"


def test_punctuation_spacing() -> None:
    """Verify punctuation suppresses artificial whitespace."""
    # "これは" + "。" -> "これは。"
    s1 = _make_seg("これは")
    s2 = _make_seg("。")
    _, sep, _, _, _ = decide_inter_segment_separator(s1, s2, BoundaryType.NEW_LINE)
    assert sep == ""

    # "「" + "Linux" -> "「Linux"
    s3 = _make_seg("「")
    s4 = _make_seg("Linux")
    _, sep, _, _, _ = decide_inter_segment_separator(s3, s4, BoundaryType.NEW_LINE)
    assert sep == ""

    # "Linux" + "」" -> "Linux」"
    s5 = _make_seg("Linux")
    s6 = _make_seg("」")
    _, sep, _, _, _ = decide_inter_segment_separator(s5, s6, BoundaryType.NEW_LINE)
    assert sep == ""


def test_same_line_bbox_gap_inference() -> None:
    """Verify gap > 0.55 * estimated_char_width inserts space, otherwise empty."""
    # Segment A: 5 chars, width=50pt -> char_width=10pt
    bbox_a = BBox(x0=100.0, y0=200.0, x1=150.0, y1=220.0)
    seg_a = _make_seg("Hello", bbox=bbox_a, boundary_before="same_line")

    # Wide gap: gap = 160 - 150 = 10pt > 0.55 * 10 = 5.5pt -> space
    bbox_b_wide = BBox(x0=160.0, y0=200.0, x1=210.0, y1=220.0)
    seg_b_wide = _make_seg("world", bbox=bbox_b_wide, boundary_before="same_line")
    _, sep, _, _, reason = decide_inter_segment_separator(
        seg_a, seg_b_wide, BoundaryType.SAME_LINE
    )
    assert sep == " "
    assert reason == "same_line_bbox_gap"

    # Narrow gap: gap = 152 - 150 = 2pt <= 5.5pt -> no space
    bbox_b_tight = BBox(x0=152.0, y0=200.0, x1=202.0, y1=220.0)
    seg_b_tight = _make_seg("world", bbox=bbox_b_tight, boundary_before="same_line")
    _, sep_tight, _, _, reason_tight = decide_inter_segment_separator(
        seg_a, seg_b_tight, BoundaryType.SAME_LINE
    )
    assert sep_tight == ""
    assert reason_tight == "same_line_bbox_no_gap"


def test_explicit_source_space() -> None:
    """Verify explicit whitespace in source segments is preserved as one space in prose."""
    s1 = _make_seg("Linux ")
    s2 = _make_seg("kernel")
    a, sep, b, _, reason = decide_inter_segment_separator(s1, s2, BoundaryType.NEW_LINE)
    assert a == "Linux"
    assert sep == " "
    assert b == "kernel"
    assert reason == "explicit_source_space"


def test_latin_dehyphenation() -> None:
    """Verify safe dehyphenation at newline/page continuation."""
    # Positive: "inter-" + "esting" -> "interesting"
    a, b, ok = try_dehyphenate("inter-", "esting")
    assert ok
    assert a == "inter"
    assert b == "esting"

    # Negative 1: UTF- + 8 (right is digit)
    _, _, ok1 = try_dehyphenate("UTF-", "8")
    assert not ok1

    # Negative 2: pre- + 1990 (right is digit)
    _, _, ok2 = try_dehyphenate("pre-", "1990")
    assert not ok2

    # Negative 3: foo- + Bar (right is uppercase)
    _, _, ok3 = try_dehyphenate("foo-", "Bar")
    assert not ok3

    # Negative 4: URL / path
    _, _, ok4 = try_dehyphenate("https://site.org/foo-", "bar")
    assert not ok4


def test_collapse_intra_segment_spaces() -> None:
    """Verify 2+ ordinary spaces are collapsed to 1, while NBSP is preserved."""
    collapsed, count = collapse_intra_segment_spaces("This   has    multiple  spaces.")
    assert collapsed == "This has multiple spaces."
    assert count == 3

    # Non-breaking space preserved
    nbsp_text = "Price:\u00a0100"
    res, c2 = collapse_intra_segment_spaces(nbsp_text)
    assert res == nbsp_text
    assert c2 == 0
