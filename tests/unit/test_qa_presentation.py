"""Unit tests for presentation QA, CSS invariants, and duplicate list markers (Appendix N6)."""

from pathlib import Path

from book2epub.qa.presentation import evaluate_presentation_qa
from book2epub.render.models import RenderManifest


def test_presentation_qa_clean_epub(tmp_path: Path) -> None:
    """Verify clean EPUB passes presentation QA with 0 violations."""
    oebps = tmp_path / "OEBPS"
    styles_dir = oebps / "styles"
    styles_dir.mkdir(parents=True)
    (styles_dir / "book.css").write_text("body { font-family: serif; }", encoding="utf-8")

    text_dir = oebps / "text"
    text_dir.mkdir(parents=True)
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<body>\n"
        "<ul><li>Item text</li></ul>\n"
        "</body></html>"
    )
    (text_dir / "part-0001.xhtml").write_text(xhtml, encoding="utf-8")

    manifest = RenderManifest(
        title="Test",
        language="ja",
        identifier="urn:uuid:test-123",
        style_profile_hash="hash123",
        presentation_mode="enhanced",
        component_counts={"heading": 1, "paragraph": 2},
    )

    metrics, violations = evaluate_presentation_qa(
        oebps_dir=oebps,
        manifest=manifest,
        mode="enhanced",
    )
    assert len(violations) == 0
    assert metrics.list_duplicate_marker_count == 0
    assert metrics.style_profile_hash == "hash123"
    assert metrics.component_counts["heading"] == 1


def test_presentation_qa_detects_forbidden_rules(tmp_path: Path) -> None:
    """Verify presentation QA catches position: absolute, script tags, and duplicate markers."""
    oebps = tmp_path / "OEBPS"
    styles_dir = oebps / "styles"
    styles_dir.mkdir(parents=True)
    (styles_dir / "book.css").write_text("div { position: absolute; }", encoding="utf-8")

    text_dir = oebps / "text"
    text_dir.mkdir(parents=True)
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "<head><script>alert('bad');</script></head>\n"
        "<body>\n"
        "<ul><li>• - duplicated item</li></ul>\n"
        "</body></html>"
    )
    (text_dir / "part-0001.xhtml").write_text(xhtml, encoding="utf-8")

    metrics, violations = evaluate_presentation_qa(
        oebps_dir=oebps,
        mode="enhanced",
    )
    assert any("position: absolute" in v for v in violations)
    assert any("<script>" in v for v in violations)
    assert any("Duplicate list marker" in v for v in violations)
    assert metrics.list_duplicate_marker_count == 1
