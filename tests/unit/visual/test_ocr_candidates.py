"""Unit tests for OCR candidate detection and conservative gating (M9 Section 10)."""

from book2epub.ir.models import (
    BBox,
    CodeBlock,
    DisplayMath,
    InlineMath,
    Paragraph,
    SourceRef,
    SourceTextSegment,
    Table,
    Text,
)
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.visual.ocr_candidates import detect_ocr_candidates


def _make_para(block_id: str, text: str, page_idx: int = 0) -> Paragraph:
    seg = SourceTextSegment(
        segment_id=f"{block_id}-s0",
        block_id=block_id,
        page_idx=page_idx,
        text=text,
        text_sha256=compute_text_sha256(text),
        bbox=BBox(x0=10, y0=10, x1=100, y1=30),
    )
    inl = Text(text=text, source_segments=[seg])
    return Paragraph(id=block_id, inlines=[inl])


def test_ocr_candidates_mode_off_returns_zero() -> None:
    """When OCR mode is 'off', candidate detection must return zero candidates."""
    corrupt_para = _make_para("p1", "Corrupt text with \ufffd symbol")
    cands = detect_ocr_candidates([corrupt_para], mode="off")
    assert cands == []


def test_ocr_candidates_safe_mode_detects_prose_anomalies() -> None:
    """Safe mode detects unicode replacement and Japanese kana-digit confusion."""
    p1 = _make_para("p1", "正常な文章")
    p2 = _make_para("p2", "テキスト破損 \ufffd 発見")
    p3 = _make_para("p3", "すべ1のファイルを保存する")  # '1' instead of 'て'

    cands = detect_ocr_candidates([p1, p2, p3], mode="safe")
    cand_ids = [c.block_id for c in cands]

    assert "p1" not in cand_ids
    assert "p2" in cand_ids
    assert "p3" in cand_ids


def test_ocr_candidates_excludes_math_and_table() -> None:
    """Math and table blocks must NEVER produce OCR candidates (Appendix K6)."""
    # Corrupt math
    math_blk = DisplayMath(
        id="m1",
        latex=r"f(x) = \int \ufffd dx",
    )
    # Paragraph with inline math
    inl_math = InlineMath(latex=r"\alpha \ufffd \beta")
    para_math = Paragraph(id="p-math", inlines=[inl_math])
    # Corrupt table
    table_blk = Table(
        id="t1",
        html="<table><tr><td>\ufffd error</td></tr></table>",
    )

    cands = detect_ocr_candidates([math_blk, para_math, table_blk], mode="safe")
    assert cands == []


def test_ocr_candidates_safe_excludes_code_but_all_includes_code() -> None:
    """Safe mode excludes CodeBlock body; 'all' mode includes it."""
    code_blk = CodeBlock(
        id="c1",
        text="fn main() {\n  let retum = 1;\n}",
        sources=[SourceRef(page_idx=0, bbox=BBox(x0=0, y0=0, x1=50, y1=50), source_type="code")],
    )

    # In safe mode, code is excluded
    safe_cands = detect_ocr_candidates([code_blk], mode="safe")
    assert safe_cands == []

    # In all mode, code is included
    all_cands = detect_ocr_candidates([code_blk], mode="all")
    assert len(all_cands) == 1
    assert all_cands[0].block_id == "c1"
    assert all_cands[0].is_code is True


def test_ocr_candidates_per_page_cap() -> None:
    """Per-page cap restricts maximum candidates to 3 per page (Appendix K7)."""
    blocks = [
        _make_para(f"p-bad-{i}", f"Error \ufffd number {i}", page_idx=0)
        for i in range(10)
    ]
    cands = detect_ocr_candidates(blocks, mode="safe", max_per_page=3)
    assert len(cands) == 3
