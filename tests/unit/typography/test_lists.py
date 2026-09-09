"""Unit tests for list marker extraction, deduplication, and style inference
(M11/Appendix M12-M16).
"""

from book2epub.ir.models import ListBlock, Paragraph, Text
from book2epub.typography.lists import (
    classify_single_marker,
    extract_item_leading_marker,
    infer_majority_marker_style,
    normalize_list_block,
)


def test_extract_unordered_markers() -> None:
    """Verify unordered markers are extracted from item start and remaining text preserved."""
    # 1. Dash marker
    inlines_dash = [Text(text="- install package")]
    new_inlines, marker = extract_item_leading_marker(inlines_dash)
    assert marker == "-"
    assert isinstance(new_inlines[0], Text)
    assert new_inlines[0].text == "install package"

    # 2. Bullet marker
    inlines_bullet = [Text(text="• configuration options")]
    new_inlines, marker = extract_item_leading_marker(inlines_bullet)
    assert marker == "•"
    assert new_inlines[0].text == "configuration options"

    # 3. Compound duplicate marker: "• - item"
    inlines_dup = [Text(text="• - duplicated marker item")]
    new_inlines, marker = extract_item_leading_marker(inlines_dup)
    assert marker in ("• -", "•")
    assert new_inlines[0].text == "duplicated marker item"

    # 4. Internal hyphen preserved: "pre-commit hook"
    inlines_internal = [Text(text="- pre-commit hook")]
    new_inlines, marker = extract_item_leading_marker(inlines_internal)
    assert marker == "-"
    assert new_inlines[0].text == "pre-commit hook"


def test_extract_ordered_markers() -> None:
    """Verify ordered markers are extracted from item start."""
    # 1. Parenthesized number: "(1) First item"
    inlines_num = [Text(text="(1) First item")]
    new_inlines, marker = extract_item_leading_marker(inlines_num)
    assert marker == "(1)"
    assert new_inlines[0].text == "First item"

    # 2. Dotted number: "1. Step one"
    inlines_dot = [Text(text="1. Step one")]
    new_inlines, marker = extract_item_leading_marker(inlines_dot)
    assert marker == "1."
    assert new_inlines[0].text == "Step one"

    # 3. Japanese circled number: "① 第一項目"
    inlines_c = [Text(text="① 第一項目")]
    new_inlines, marker = extract_item_leading_marker(inlines_c)
    assert marker == "①"
    assert new_inlines[0].text == "第一項目"


def test_normalize_list_block_and_style_inference() -> None:
    """Verify ListBlock items have markers extracted and majority marker style inferred."""
    block = ListBlock(
        id="lst-1",
        items=[
            [Text(text="- First item")],
            [Text(text="- Second item")],
            [Text(text="Third item without marker")],
        ],
    )
    norm_block, count = normalize_list_block(block)
    assert count == 2
    assert norm_block.source_markers == ["-", "-", None]
    assert norm_block.marker_style == "dash"
    assert norm_block.items[0][0].text == "First item"
    assert norm_block.items[1][0].text == "Second item"
    assert norm_block.items[2][0].text == "Third item without marker"


def test_marker_style_mapping() -> None:
    """Verify marker classification maps to correct finite enum tokens."""
    assert classify_single_marker("•") == "disc"
    assert classify_single_marker("●") == "disc"
    assert classify_single_marker("・") == "disc"
    assert classify_single_marker("○") == "circle"
    assert classify_single_marker("▪") == "square"
    assert classify_single_marker("-") == "dash"
    assert classify_single_marker("–") == "dash"
    assert classify_single_marker("1.") == "decimal"
    assert classify_single_marker("(2)") == "decimal"
    assert classify_single_marker("a.") == "alpha"
    assert classify_single_marker("(b)") == "alpha"
    assert classify_single_marker("iv.") == "roman"

    # Majority inference
    assert infer_majority_marker_style(["-", "-", "•"]) == "dash"
    assert infer_majority_marker_style(["1.", "2.", "3."]) == "decimal"
    assert infer_majority_marker_style([]) == "auto"


def test_ordinary_paragraph_negative_number_untouched() -> None:
    """Verify ordinary Paragraph starting with '-1 is negative' is untouched."""
    p = Paragraph(id="p-1", inlines=[Text(text="-1 is a negative number")])
    # extract_item_leading_marker requires list item context and whitespace after marker
    inlines, marker = extract_item_leading_marker(p.inlines)
    assert marker is None
    assert inlines[0].text == "-1 is a negative number"
