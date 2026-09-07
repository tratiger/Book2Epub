"""Unit tests for BookIR models, adapter, normalization, and serialization."""

import json
from pathlib import Path

from book2epub.ir.adapter import MiddleJsonAdapter
from book2epub.ir.models import (
    Chart,
    CodeBlock,
    DisplayMath,
    Figure,
    PageBoundary,
    Paragraph,
    Table,
    UnknownBlock,
)
from book2epub.ir.normalize import normalize_bookir
from book2epub.ir.serializer import (
    extract_plain_text_from_block,
    load_bookir,
    save_bookir,
)
from book2epub.ir.text_join import TextJoinStats, join_prose_texts


def test_text_join_rules() -> None:
    # 1. CJK to CJK: no space
    cjk_res = join_prose_texts(["こんにちは", "世界"])
    assert cjk_res == "こんにちは世界"

    # 2. Latin to Latin: one space
    latin_res = join_prose_texts(["Hello", "world", "from", "Book2Epub"])
    assert latin_res == "Hello world from Book2Epub"

    # 3. Dehyphenation: inter- + esting -> interesting
    stats = TextJoinStats()
    hyphen_res = join_prose_texts(["This is an inter-", "esting text."], stats=stats)
    assert hyphen_res == "This is an interesting text."
    assert stats.dehyphenation_count == 1

    # 4. Preserve hyphen if not lowercase latin continuation
    keep_hyphen = join_prose_texts(["pre-", "1990 era"])
    assert keep_hyphen == "pre- 1990 era"


def test_comprehensive_middle_json_conversion() -> None:
    fixture_path = (
        Path(__file__).parent.parent / "fixtures" / "middle" / "hybrid-3.4.5-comprehensive.json"
    )
    with fixture_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    adapter = MiddleJsonAdapter(base_dir=fixture_path.parent, strict=True)
    raw_ir = adapter.convert_middle_json(data)

    # 1. Assert basic structure
    assert raw_ir.source.mineru_version == "3.4.5"
    assert raw_ir.source.mineru_backend == "hybrid"
    assert raw_ir.source.page_count == 2
    assert len(raw_ir.assets) >= 3

    # Check that provenance is preserved on all blocks
    for blk in raw_ir.blocks:
        assert len(blk.sources) > 0
        assert blk.sources[0].page_idx in (0, 1)

    # Check specific block types
    types = [b.kind for b in raw_ir.blocks]
    assert "heading" in types
    assert "paragraph" in types
    assert "code" in types
    assert "figure" in types
    assert "chart" in types
    assert "table" in types
    assert "display_math" in types
    assert "list" in types
    assert "index" in types
    assert "aside" in types
    assert "footnote" in types
    assert "unknown" in types

    # Check code block content and whitespace
    code_blocks = [b for b in raw_ir.blocks if isinstance(b, CodeBlock)]
    assert len(code_blocks) == 2
    py_code = next(b for b in code_blocks if b.subtype == "code")
    assert py_code.language == "python"
    assert "    return x * 2" in py_code.text

    algo_code = next(b for b in code_blocks if b.subtype == "algorithm")
    assert "Algorithm 1: Binary Search" in algo_code.text

    # Check math LaTeX
    math_blocks = [b for b in raw_ir.blocks if isinstance(b, DisplayMath)]
    assert len(math_blocks) == 1
    assert "\\int_0^\\infty" in math_blocks[0].latex

    # Check table sanitization
    table_blocks = [b for b in raw_ir.blocks if isinstance(b, Table)]
    assert len(table_blocks) == 1
    assert "colspan" in table_blocks[0].html
    assert "rowspan" in table_blocks[0].html
    assert "style=" not in table_blocks[0].html
    assert "data-latex" in table_blocks[0].html

    # Check unknown block warning
    unknown_blocks = [b for b in raw_ir.blocks if isinstance(b, UnknownBlock)]
    assert len(unknown_blocks) == 1
    assert unknown_blocks[0].source_type == "unrecognized_banner"

    # Now run normalization
    normalized_ir = normalize_bookir(
        raw_ir,
        raw_page_number_texts=["iii", "1"],
    )

    # Check page labels
    assert normalized_ir.source.pages[0].printed_label == "iii"
    assert normalized_ir.source.pages[1].printed_label == "1"

    # Check cross-page paragraph merge
    # The paragraph starting on page 0 and continuing on page 1 should be merged
    merged_paras = [
        b
        for b in normalized_ir.blocks
        if isinstance(b, Paragraph) and any(isinstance(i, PageBoundary) for i in b.inlines)
    ]
    assert len(merged_paras) == 1
    merged_p = merged_paras[0]
    plain_text = extract_plain_text_from_block(merged_p)
    assert "This sentence begins on the first page and continues smoothly" in plain_text
    assert "onto the second page without interruption" in plain_text

    # Check LayoutHint on figure/chart/table
    for blk in normalized_ir.blocks:
        if isinstance(blk, (Figure, Chart, Table)):
            assert blk.layout_hint is not None
            assert blk.layout_hint.size_class in ("small", "medium", "large")
            assert blk.layout_hint.alignment in ("left", "center", "right")


def test_bookir_roundtrip_serialization(tmp_path: Path) -> None:
    fixture_path = (
        Path(__file__).parent.parent / "fixtures" / "middle" / "hybrid-3.4.5-comprehensive.json"
    )
    with fixture_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    adapter = MiddleJsonAdapter(base_dir=fixture_path.parent, strict=True)
    raw_ir = adapter.convert_middle_json(data)
    normalized_ir = normalize_bookir(raw_ir, raw_page_number_texts=["iii", "1"])

    out_file = tmp_path / "bookir.normalized.json"
    save_bookir(normalized_ir, out_file)
    assert out_file.is_file()

    loaded_ir = load_bookir(out_file)
    assert len(loaded_ir.blocks) == len(normalized_ir.blocks)
    assert loaded_ir.source.page_count == normalized_ir.source.page_count
    assert loaded_ir.source.pages[0].printed_label == "iii"
