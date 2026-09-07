"""Unit tests for QA diagnostics, structural quality checks, and deterministic packaging."""

import hashlib
import json
from pathlib import Path

from book2epub.config import JobConfig
from book2epub.ir.models import (
    BookIR,
    BookMetadata,
    CodeBlock,
    DisplayMath,
    Heading,
    SourceDocument,
    SourcePage,
    SourceRef,
    Table,
    Text,
)
from book2epub.package.models import PackagingResult, ValidationReport
from book2epub.qa.checks import run_structural_checks
from book2epub.qa.report import generate_qa_report
from book2epub.qa.stage import StageState, load_stage_record, record_stage_status
from book2epub.render.models import RenderedDocument, RenderManifest, RenderResult


def test_structural_checks_reconciliation() -> None:
    # 1. Mock source middle data with 1 heading, 1 code, 1 table, 1 equation
    raw_middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "type": "title",
                        "level": 1,
                        "lines": [{"spans": [{"type": "text", "content": "Intro"}]}],
                    },
                    {
                        "type": "code",
                        "lines": [{"spans": [{"type": "text", "content": "x = 1"}]}],
                    },
                    {
                        "type": "table",
                        "lines": [{"spans": [{"type": "text", "content": "table text"}]}],
                    },
                    {
                        "type": "equation_interline",
                        "lines": [{"spans": [{"type": "text", "content": "E=mc^2"}]}],
                    },
                ],
            }
        ]
    }

    # 2. Mock BookIR matching the source
    ir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        metadata=BookMetadata(title="Test Book"),
        blocks=[
            Heading(
                id="h1",
                sources=[SourceRef(page_idx=0, source_type="title")],
                inlines=[Text(text="Intro")],
                level=1,
            ),
            CodeBlock(
                id="c1",
                sources=[SourceRef(page_idx=0, source_type="code")],
                text="x = 1",
            ),
            Table(
                id="t1",
                sources=[SourceRef(page_idx=0, source_type="table")],
                html="<table><tr><td>cell</td></tr></table>",
            ),
            DisplayMath(
                id="m1",
                sources=[SourceRef(page_idx=0, source_type="equation_interline")],
                latex="E=mc^2",
            ),
        ],
    )

    manifest = RenderManifest(
        title="Test Book",
        language="en",
        identifier="urn:uuid:1234",
        documents=[RenderedDocument(href="text/part-0001.xhtml", id="part-0001", title="Intro")],
        styles=[],
        assets=[],
        toc=[],
        page_map=[],
    )

    render_res = RenderResult(
        oebps_dir=Path("/tmp"),
        manifest=manifest,
        source_page_count=1,
        xhtml_part_count=1,
        figure_count=0,
        chart_count=0,
        table_count=1,
        code_count=1,
        math_count=1,
        fallback_count=0,
        warning_count=0,
    )

    val_report = ValidationReport(
        is_valid=True,
        epubcheck_exit_code=0,
        fatal_count=0,
        error_count=0,
        warning_count=0,
        info_count=0,
    )

    packaging_res = PackagingResult(
        epub_path=Path("/tmp/book.epub"),
        file_size_bytes=1000,
        source_page_count=1,
        xhtml_part_count=1,
        figure_count=0,
        chart_count=0,
        table_count=1,
        code_count=1,
        math_count=1,
        fallback_count=0,
        warning_count=0,
        validation_report=val_report,
    )

    checks, metrics = run_structural_checks(
        raw_middle_data=raw_middle,
        book_ir=ir,
        render_result=render_res,
        packaging_result=packaging_res,
    )

    # Assert all checks passed
    assert len(checks) == 5
    for c in checks:
        assert c.passed is True, f"Check {c.name} failed: {c.details}"

    # Assert metrics
    assert metrics.block_coverage == 1.0
    assert metrics.math_semantic_rate == 1.0
    assert metrics.table_semantic_rate == 1.0
    assert metrics.code_text_rate == 1.0
    assert metrics.epubcheck_error_count == 0


def test_qa_report_generation(tmp_path: Path) -> None:
    raw_middle = {"pdf_info": [{"page_idx": 0, "para_blocks": []}]}
    ir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        metadata=BookMetadata(title="Test"),
        blocks=[],
    )

    manifest = RenderManifest(
        title="Test",
        language="en",
        identifier="urn:uuid:1234",
        documents=[],
        styles=[],
        assets=[],
        toc=[],
        page_map=[],
    )

    render_res = RenderResult(
        oebps_dir=tmp_path,
        manifest=manifest,
        source_page_count=1,
        xhtml_part_count=1,
        figure_count=0,
        chart_count=0,
        table_count=0,
        code_count=0,
        math_count=0,
        fallback_count=0,
        warning_count=0,
    )

    val_report = ValidationReport(
        is_valid=True,
        epubcheck_exit_code=0,
        fatal_count=0,
        error_count=0,
        warning_count=0,
        info_count=0,
    )

    packaging_res = PackagingResult(
        epub_path=tmp_path / "book.epub",
        file_size_bytes=500,
        source_page_count=1,
        xhtml_part_count=1,
        figure_count=0,
        chart_count=0,
        table_count=0,
        code_count=0,
        math_count=0,
        fallback_count=0,
        warning_count=0,
        validation_report=val_report,
    )

    json_path = tmp_path / "qa" / "report.json"
    html_path = tmp_path / "qa" / "report.html"

    generate_qa_report(
        job_id="job-test-01",
        raw_middle_data=raw_middle,
        book_ir=ir,
        render_result=render_res,
        packaging_result=packaging_res,
        cfg=JobConfig(),
        report_json_path=json_path,
        report_html_path=html_path,
    )

    assert json_path.is_file()
    assert html_path.is_file()

    # Verify JSON content
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["job_id"] == "job-test-01"
    assert "metrics" in data

    # Verify HTML content
    html_text = html_path.read_text(encoding="utf-8")
    assert "Book2Epub QA Diagnostic Report" in html_text
    assert "job-test-01" in html_text


def test_reproducible_packaging_determinism(tmp_path: Path) -> None:
    """Two packaging runs with reproducible=True must produce bit-for-bit identical archives."""
    from book2epub.package.container import generate_container_xml
    from book2epub.package.zip import MIMETYPE_BYTES, create_epub_zip

    staging = tmp_path / "staging_repro"
    staging.mkdir()
    (staging / "mimetype").write_bytes(MIMETYPE_BYTES)
    (staging / "META-INF").mkdir()
    (staging / "META-INF" / "container.xml").write_text(generate_container_xml(), encoding="utf-8")
    (staging / "OEBPS").mkdir()
    (staging / "OEBPS" / "content.xhtml").write_text("<html/>", encoding="utf-8")

    out1 = tmp_path / "repro1.epub"
    out2 = tmp_path / "repro2.epub"

    create_epub_zip(staging, out1, reproducible=True)
    create_epub_zip(staging, out2, reproducible=True)

    hash1 = hashlib.sha256(out1.read_bytes()).hexdigest()
    hash2 = hashlib.sha256(out2.read_bytes()).hexdigest()

    assert hash1 == hash2, "Reproducible packaging produced different hashes"


def test_stage_record_tracking(tmp_path: Path) -> None:
    stage_file = tmp_path / "stage.json"
    record_stage_status(
        stage_file=stage_file,
        stage_name="render",
        state=StageState.COMPLETE,
        input_hash="abc123hash",
        details={"parts": 5},
    )

    assert stage_file.is_file()
    loaded = load_stage_record(stage_file)
    assert loaded is not None
    assert loaded.stage == "render"
    assert loaded.state == StageState.COMPLETE
    assert loaded.input_hash == "abc123hash"
    assert loaded.details["parts"] == 5
