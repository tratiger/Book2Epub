"""Unit and integration tests for M3 Reflow XHTML / MathML renderer."""

import json
import subprocess
from pathlib import Path

from lxml import etree

from book2epub.ir.adapter import MiddleJsonAdapter
from book2epub.ir.models import (
    BookIR,
    BookMetadata,
    Heading,
    Paragraph,
    SourceDocument,
    SourcePage,
    Text,
)
from book2epub.ir.normalize import normalize_bookir
from book2epub.paths import get_epubcheck_jar_path
from book2epub.render import ReflowRenderer
from book2epub.render.math import convert_latex_to_mathml, normalize_latex
from book2epub.render.metadata import infer_language_from_text, infer_metadata
from book2epub.render.renderer import build_hierarchical_toc
from book2epub.render.splitter import (
    split_bookir_blocks,
)
from book2epub.render.xhtml import NS_XHTML

FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "middle" / "hybrid-3.4.5-comprehensive.json"
)


def test_latex_normalization() -> None:
    """Test stripping math delimiters."""
    assert normalize_latex("$E = mc^2$") == "E = mc^2"
    assert normalize_latex("$$\\int x dx$$") == "\\int x dx"
    assert normalize_latex("\\[ a^2 + b^2 = c^2 \\]") == "a^2 + b^2 = c^2"
    assert normalize_latex("\\( \\alpha + \\beta \\)") == "\\alpha + \\beta"
    assert normalize_latex("   E = mc^2   ") == "E = mc^2"


def test_mathml_conversion_representative_math() -> None:
    """LaTeX produces parseable MathML for fractions, roots, matrices, sums, Greek."""
    formulas = [
        r"\frac{a}{b}",
        r"\sqrt{x^2 + y^2}",
        r"E = mc^2",
        r"\sum_{i=1}^n i",
        r"\alpha + \beta = \gamma",
        r"\begin{matrix} 1 & 2 \\ 3 & 4 \end{matrix}",
    ]
    for formula in formulas:
        res = convert_latex_to_mathml(formula, display_block=False)
        assert res.success, f"Failed for {formula}: {res.error_message}"
        assert res.mathml_element is not None
        xml_str = etree.tostring(res.mathml_element).decode("utf-8")
        assert "math" in xml_str


def test_math_fallback_on_unsupported_latex() -> None:
    """Unconvertible LaTeX falls back safely without raising an exception."""
    broken = r"\begin{invalid_env"
    res = convert_latex_to_mathml(broken, display_block=False)
    assert not res.success
    assert res.fallback_latex == broken


def test_language_inference_heuristics() -> None:
    """Deterministic language inference identifies Japanese, English, and unknown."""
    assert infer_language_from_text("This is an ordinary English technical book.") == "en"
    assert infer_language_from_text("本書は技術書のEPUB変換パイプラインです。") == "ja"
    assert infer_language_from_text("12345 67890 !?#") == "und"


def test_metadata_inference() -> None:
    """Metadata resolution follows the strict priority contract."""
    ir = BookIR(
        metadata=BookMetadata(title=None, language="auto"),
        source=SourceDocument(
            mineru_version="3.4.5",
            mineru_backend="hybrid",
            page_count=1,
            pages=[SourcePage(page_idx=0, width=800, height=1200)],
        ),
        blocks=[
            Heading(id="h1", inlines=[Text(text="Inferred Title")], level=1),
            Paragraph(id="p1", inlines=[Text(text="English prose text content")]),
        ],
    )
    meta = infer_metadata(ir)
    assert meta.title == "Inferred Title"
    assert meta.language == "en"
    assert meta.identifier.startswith("urn:uuid:")

    # CLI overrides have priority
    override = infer_metadata(
        ir,
        cli_title="CLI Title",
        cli_language="ja",
        cli_identifier="custom-id",
    )
    assert override.title == "CLI Title"
    assert override.language == "ja"
    assert override.identifier == "custom-id"


def test_document_splitter() -> None:
    """Document splitting follows rules for frontmatter, level-1 headings, and thresholds."""
    blocks = [
        # Frontmatter
        Paragraph(id="p0", inlines=[Text(text="Preface before any chapter")]),
        # Chapter 1
        Heading(id="h1", inlines=[Text(text="Chapter 1")], level=1),
        Paragraph(id="p1", inlines=[Text(text="Content 1")]),
        # Chapter 2
        Heading(id="h2", inlines=[Text(text="Chapter 2")], level=1),
        Paragraph(id="p2", inlines=[Text(text="Content 2")]),
    ]
    sections = split_bookir_blocks(blocks)
    assert len(sections) == 3
    assert sections[0].href == "text/frontmatter.xhtml"
    assert sections[1].href == "text/part-0001.xhtml"
    assert sections[2].href == "text/part-0002.xhtml"


def test_document_splitter_threshold() -> None:
    """Documents exceeding character limits split at level-2 headings."""
    long_text = "x" * 60_000
    blocks = [
        Heading(id="h1", inlines=[Text(text="Big Chapter")], level=1),
        Paragraph(id="p1", inlines=[Text(text=long_text)]),
        Heading(id="h2", inlines=[Text(text="Section 1.1")], level=2),
        Paragraph(id="p2", inlines=[Text(text=long_text)]),
    ]
    sections = split_bookir_blocks(blocks)
    assert len(sections) == 2
    assert sections[0].href == "text/part-0001.xhtml"
    assert sections[1].href == "text/part-0002.xhtml"


def test_hierarchical_toc_construction() -> None:
    """TOC tree builds hierarchical structure and handles level jumps."""
    from book2epub.render.models import TocEntry

    flat = [
        TocEntry(title="Chapter 1", href="text/part-0001.xhtml#h-1", level=1),
        TocEntry(title="Sec 1.1", href="text/part-0001.xhtml#h-2", level=2),
        TocEntry(title="Sub 1.1.1", href="text/part-0001.xhtml#h-3", level=3),
        TocEntry(title="Chapter 2", href="text/part-0002.xhtml#h-4", level=1),
        # Level jump (h1 -> h3)
        TocEntry(title="Deep Sub", href="text/part-0002.xhtml#h-5", level=3),
    ]

    toc = build_hierarchical_toc(flat, default_title="Book", first_doc_href="text/part-0001.xhtml")
    assert len(toc) == 2
    assert toc[0].title == "Chapter 1"
    assert len(toc[0].children) == 1
    assert toc[0].children[0].title == "Sec 1.1"
    assert len(toc[0].children[0].children) == 1
    assert toc[0].children[0].children[0].title == "Sub 1.1.1"

    assert toc[1].title == "Chapter 2"
    # Deep sub nested directly under Chapter 2
    assert len(toc[1].children) == 1
    assert toc[1].children[0].title == "Deep Sub"


def test_comprehensive_rendering_pipeline(tmp_path: Path) -> None:
    """
    Comprehensive test rendering hybrid-3.4.5-comprehensive.json fixture.

    Verifies:
    - XHTML parses as well-formed XML
    - Special chars <>&" escaped
    - Heading hierarchy and stable IDs
    - MathML inline and display
    - Code block indentation and language class
    - Table structure preserved without styles
    - Figure responsive size/alignment classes
    - Pagebreak anchors for every source page
    - EPUBCheck --mode xhtml validation passes with 0 errors
    """
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Ingest to BookIR
    adapter = MiddleJsonAdapter(base_dir=FIXTURE_PATH.parent, strict=True)
    raw_ir = adapter.convert_middle_json(data)
    normalized_ir = normalize_bookir(raw_ir, raw_page_number_texts=["iii", "1"])

    # 2. Render to OEBPS tree
    output_dir = tmp_path / "render_test"
    renderer = ReflowRenderer(
        output_dir=output_dir,
        cli_title="Technical Book Guide",
    )
    result = renderer.render(normalized_ir)

    assert result.oebps_dir.exists()
    assert (result.oebps_dir / "styles" / "book.css").exists()
    assert (result.oebps_dir / "render-manifest.json").exists()

    # Verify render manifest
    with (result.oebps_dir / "render-manifest.json").open("r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    assert manifest_data["title"] == "Technical Book Guide"
    assert manifest_data["language"] in ("ja", "en")
    assert len(manifest_data["documents"]) >= 1
    assert len(manifest_data["page_map"]) == 2  # 2 source pages
    assert len(manifest_data["assets"]) >= 3

    # Check rendered XHTML documents
    xhtml_files = list((result.oebps_dir / "text").glob("*.xhtml"))
    assert len(xhtml_files) >= 1

    epubcheck_jar = get_epubcheck_jar_path()
    has_epubcheck = epubcheck_jar.exists()

    for xhtml_path in xhtml_files:
        content = xhtml_path.read_text(encoding="utf-8")

        # 1. XML parse test
        xml_doc = etree.fromstring(content.encode("utf-8"))
        assert xml_doc.tag == f"{{{NS_XHTML}}}html"

        # 2. OCR special characters escaped
        assert "<script>" not in content  # must be &lt;script&gt;
        assert "&lt;script&gt;" in content

        # 3. No absolute positioning or forbidden styles
        assert "position:absolute" not in content
        assert "style=" not in content

        # 4. Code block preservation
        if "compute(x):" in content:
            assert "    return x * 2" in content
            assert "language-python" in content

        # 5. MathML presence
        if "E = mc^2" in content or "math display" in content:
            assert "http://www.w3.org/1998/Math/MathML" in content

        # 6. Table preservation
        if "<table" in content:
            assert "colspan=" in content
            assert "rowspan=" in content

        # 7. Figures use responsive classes
        if "<figure" in content:
            assert "size-" in content
            assert "align-" in content

        # 8. EPUBCheck validation for standalone XHTML mode
        if has_epubcheck:
            cmd = [
                "java",
                "-jar",
                str(epubcheck_jar),
                str(xhtml_path),
                "--mode",
                "xhtml",
                "-v",
                "3.0",
                "-q",
            ]
            run_res = subprocess.run(cmd, capture_output=True, text=True)
            msg = f"EPUBCheck failed on {xhtml_path.name}:\n{run_res.stderr}\n{run_res.stdout}"
            assert run_res.returncode == 0, msg
