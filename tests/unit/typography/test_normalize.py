"""Unit tests for full BookIR typography and whitespace normalization (M11)."""

from pathlib import Path

from book2epub.ir.models import (
    BookIR,
    CodeBlock,
    DisplayMath,
    Hyperlink,
    Paragraph,
    PreformattedBlock,
    SourceDocument,
    SourcePage,
    SourceTextSegment,
    Table,
    Text,
)
from book2epub.presentation.defaults import DEFAULT_ENHANCED_PROFILE
from book2epub.typography.normalize import typography_normalize_bookir
from book2epub.typography.report import save_normalization_report


def _make_text_with_segments(
    old_joined: str,
    segments_texts: list[str],
    boundaries: list[str] | None = None,
) -> Text:
    if boundaries is None:
        boundaries = ["start"] + ["new_line"] * (len(segments_texts) - 1)

    segs = [
        SourceTextSegment(
            segment_id=f"seg-{i}",
            page_idx=0,
            block_id="b-1",
            text=t,
            boundary_before=b,  # type: ignore[arg-type]
            text_sha256=f"hash-{i}",
        )
        for i, (t, b) in enumerate(zip(segments_texts, boundaries, strict=False))
    ]
    return Text(text=old_joined, source_segments=segs)


def test_typography_normalize_paragraph_reconstruction() -> None:
    """Verify paragraph visible text is reconstructed from source segments without artificial
    spaces.
    """
    # Legacy join had inserted space: "これは Linux"
    text_inline = _make_text_with_segments(
        old_joined="これは Linux",
        segments_texts=["これは", "Linux"],
        boundaries=["start", "new_line"],
    )
    p = Paragraph(id="p-1", inlines=[text_inline])
    bookir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=[p],
    )

    norm_ir, report = typography_normalize_bookir(bookir, profile=DEFAULT_ENHANCED_PROFILE)
    norm_p = norm_ir.blocks[0]
    assert isinstance(norm_p, Paragraph)
    assert norm_p.inlines[0].text == "これはLinux"
    assert report.source_segment_reconstructions == 1
    assert report.spaces_removed_vs_legacy_join == 1


def test_japanese_leading_print_indent_normalization() -> None:
    """Verify leading U+3000 is normalized when profile first_line_indent != 'none'."""
    # Profile with first_line_indent="indent_1em"
    body_with_indent = DEFAULT_ENHANCED_PROFILE.body.model_copy(
        update={"first_line_indent": "indent_1em"}
    )
    profile_with_indent = DEFAULT_ENHANCED_PROFILE.model_copy(update={"body": body_with_indent})
    text_inline = Text(text="\u3000これは段落の先頭です。内側の\u3000空白は残す。")
    p = Paragraph(id="p-indent", inlines=[text_inline])
    bookir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=[p],
    )

    norm_ir, report = typography_normalize_bookir(bookir, profile=profile_with_indent)
    norm_p = norm_ir.blocks[0]
    assert isinstance(norm_p, Paragraph)
    # Leading U+3000 stripped
    assert norm_p.inlines[0].text.startswith("これは段落の先頭です。")
    # Internal U+3000 preserved
    assert "内側の\u3000空白は残す。" in norm_p.inlines[0].text
    assert report.leading_print_indents_normalized == 1

    # Profile with first_line_indent="none" -> leading U+3000 preserved
    body_no_indent = DEFAULT_ENHANCED_PROFILE.body.model_copy(
        update={"first_line_indent": "none"}
    )
    profile_no_indent = DEFAULT_ENHANCED_PROFILE.model_copy(update={"body": body_no_indent})
    norm_ir_no, report_no = typography_normalize_bookir(bookir, profile=profile_no_indent)
    norm_p_no = norm_ir_no.blocks[0]
    assert isinstance(norm_p_no, Paragraph)
    assert norm_p_no.inlines[0].text.startswith("\u3000これは")
    assert report_no.leading_print_indents_normalized == 0


def test_typography_exclusions_strictly_respected() -> None:
    """Verify CodeBlock, PreformattedBlock, DisplayMath, Table, and Link URLs are not mutated."""
    code = CodeBlock(id="c-1", text="  def hello():\n    return 'world'\n", language="python")
    term = PreformattedBlock(id="t-1", text="$ ls -la\ntotal 0\n", subtype="terminal_output")
    math = DisplayMath(id="m-1", latex="\\int_{0}^{\\infty} e^{-x^2} dx")
    tbl = Table(id="tbl-1", html="<table><tr><td>cell 1</td></tr></table>")
    link = Hyperlink(
        url="https://example.com/api?v=1&q=test",
        children=[Text(text="API documentation")],
    )
    p_link = Paragraph(id="p-link", inlines=[link])

    bookir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=[code, term, math, tbl, p_link],
    )

    norm_ir, _ = typography_normalize_bookir(bookir, profile=DEFAULT_ENHANCED_PROFILE)
    assert norm_ir.blocks[0].text == code.text  # type: ignore[attr-defined]
    assert norm_ir.blocks[1].text == term.text  # type: ignore[attr-defined]
    assert norm_ir.blocks[2].latex == math.latex  # type: ignore[attr-defined]
    assert norm_ir.blocks[3].html == tbl.html  # type: ignore[attr-defined]

    p_res = norm_ir.blocks[4]
    assert isinstance(p_res, Paragraph)
    link_res = p_res.inlines[0]
    assert isinstance(link_res, Hyperlink)
    assert link_res.url == "https://example.com/api?v=1&q=test"


def test_fallback_when_no_source_segments() -> None:
    """Verify Text node without source_segments is safely preserved and counted as fallback."""
    text_plain = Text(text="Authored or synthesized text without segments.")
    p = Paragraph(id="p-fallback", inlines=[text_plain])
    bookir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=[p],
    )

    norm_ir, report = typography_normalize_bookir(bookir, profile=DEFAULT_ENHANCED_PROFILE)
    assert norm_ir.blocks[0].inlines[0].text == "Authored or synthesized text without segments."  # type: ignore[attr-defined]
    assert report.fallback_text_nodes_without_segments == 1
    assert report.source_segment_reconstructions == 0


def test_save_normalization_report(tmp_path: Path) -> None:
    """Verify report saves to JSON with valid schema."""
    text_inline = _make_text_with_segments(
        old_joined="これは Linux",
        segments_texts=["これは", "Linux"],
        boundaries=["start", "new_line"],
    )
    p = Paragraph(id="p-1", inlines=[text_inline])
    bookir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=[p],
    )
    _, report = typography_normalize_bookir(bookir, profile=DEFAULT_ENHANCED_PROFILE)

    out_file = tmp_path / "presentation" / "normalization-report.json"
    save_normalization_report(report, out_file)
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert '"source_segment_reconstructions": 1' in content
    assert '"spaces_removed_vs_legacy_join": 1' in content
