"""Comprehensive tests for M12 QA hardening (Tests A through P).

Covers:
- Test A: source 'abc' final 'abd' -> ledger fake PASS prohibited (text mismatch/corruption).
- Test B: Paragraph 'abc' -> Heading 'abc' -> retyped PASS.
- Test C: Table -> terminal Evidence-derived -> justified PASS.
- Test D: Fabricated text -> FAIL.
- Test E: Footnote loss -> FAIL.
- Test F: Cross-page paragraph merge trace -> PASS.
- Test G: Unexplained asset loss -> FAIL.
- Test H: Authoritative OCR writer artifact validated by QA reader -> PASS.
- Test I: OCR invariant violation -> strict release gate failure.
- Test J: Presentation violation (forbidden CSS/script/remote) -> strict release gate failure.
- Test K: Semantic code retype -> Code Reconciliation does not false-FAIL.
- Test L: Missing semantic block -> lost_error + strict release gate failure.
- Test M: Outline cycle detected -> FAIL.
- Test N: Outline non-monotonic order -> FAIL.
- Test O: Broken TOC target fragment -> FAIL.
- Test P: Table -> terminal -> visual reject -> Table matches Table across ledger, audit, and XHTML.
"""

import json
from pathlib import Path

import pytest

from book2epub.config import AppConfig, JobConfig, OCRCorrectionConfig, PresentationConfig
from book2epub.ir.models import (
    BookIR,
    Figure,
    Footnote,
    Heading,
    Paragraph,
    PreformattedBlock,
    SourceDocument,
    SourcePage,
    SourceTextSegment,
    Table,
    Text,
)
from book2epub.package.models import PackagingResult, ValidationReport
from book2epub.paths import create_job_paths
from book2epub.pipeline import run_conversion_m5
from book2epub.qa.checks import run_structural_checks
from book2epub.qa.models import PreservationLedgerEntry
from book2epub.qa.ocr import evaluate_ocr_qa
from book2epub.qa.presentation import evaluate_presentation_qa
from book2epub.qa.semantic import (
    build_preservation_ledger,
    evaluate_outline_qa,
    evaluate_preservation_qa,
)
from book2epub.render.models import (
    RenderManifest,
    RenderResult,
    TocEntry,
)
from book2epub.semantic.decisions import SemanticAuditRecord
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.models import (
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)
from book2epub.semantic.structure import BookOutline, OutlineNode
from book2epub.visual.models import OCRAuditRecord, OCRCorrectionAuditFile


def _create_dummy_ir(blocks: list) -> BookIR:
    return BookIR(
        schema_version="1.0",
        source=SourceDocument(
            sha256="src-hash",
            page_count=1,
            pages=[SourcePage(page_idx=0, width=600, height=800)],
        ),
        blocks=blocks,
    )


def _create_dummy_render_result(
    oebps_dir: Path, toc: list[TocEntry] | None = None, code_count: int = 0
) -> RenderResult:
    manifest = RenderManifest(
        title="Test Book",
        language="ja",
        identifier="urn:isbn:1234567890",
        toc=toc or [],
    )
    return RenderResult(
        oebps_dir=oebps_dir,
        manifest=manifest,
        source_page_count=1,
        xhtml_part_count=1,
        figure_count=0,
        chart_count=0,
        table_count=0,
        code_count=code_count,
        math_count=0,
        fallback_count=0,
        warning_count=0,
    )


def _create_dummy_packaging_result(epub_path: Path) -> PackagingResult:
    report = ValidationReport(
        is_valid=True,
        epubcheck_exit_code=0,
        fatal_count=0,
        error_count=0,
        warning_count=0,
        info_count=0,
    )
    return PackagingResult(
        epub_path=epub_path,
        file_size_bytes=100,
        source_page_count=1,
        xhtml_part_count=1,
        figure_count=0,
        chart_count=0,
        table_count=0,
        code_count=0,
        math_count=0,
        fallback_count=0,
        warning_count=0,
        validation_report=report,
    )


def test_a_text_mismatch_fails_preservation() -> None:
    """Test A: source 'abc' final 'abd' -> ledger text mismatch detected, FAILs preservation."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="b-1",
                page_idx=0,
                reading_order=0,
                source_type="paragraph",
                plain_text="abc",
                content_sha256=compute_text_sha256("abc"),
            )
        ],
    )
    final_ir = _create_dummy_ir([
        Paragraph(id="b-1", page_idx=0, reading_order=0, inlines=[Text(text="abd")])
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    assert len(ledger) == 1
    assert "Text mismatch" in (ledger[0].reason or "")

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert any(v.code == "TEXT_FABRICATION_OR_CORRUPTION" for v in violations)


def test_b_paragraph_to_heading_retyped_passes() -> None:
    """Test B: Paragraph 'abc' -> Heading 'abc' -> retyped PASS."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="b-1",
                page_idx=0,
                reading_order=0,
                source_type="paragraph",
                plain_text="abc",
                content_sha256=compute_text_sha256("abc"),
            )
        ],
    )
    final_ir = _create_dummy_ir([
        Heading(id="b-1", level=2, page_idx=0, reading_order=0, inlines=[Text(text="abc")])
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    assert len(ledger) == 1
    assert ledger[0].disposition == "retyped"
    assert "Text mismatch" not in (ledger[0].reason or "")

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert len(violations) == 0


def test_c_table_to_terminal_evidence_derived_passes() -> None:
    """Test C: Table -> terminal Evidence-derived -> justified PASS."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="b-tbl",
                page_idx=0,
                reading_order=0,
                source_type="table",
                preformatted_text="$ uname -a\nLinux",
                table_html="<table><tr><td>$ uname -a</td></tr></table>",
                content_sha256="hash-tbl",
            )
        ],
    )
    final_ir = _create_dummy_ir([
        PreformattedBlock(
            id="b-tbl",
            page_idx=0,
            reading_order=0,
            subtype="terminal_output",
            text="$ uname -a\nLinux",
        )
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    assert len(ledger) == 1
    assert ledger[0].disposition == "retyped"
    assert "Justified representation change" in (ledger[0].reason or "")

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert len(violations) == 0


def test_d_fabricated_text_fails_preservation() -> None:
    """Test D: Fabricated text in retyped block -> FAIL."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="b-tbl",
                page_idx=0,
                reading_order=0,
                source_type="table",
                preformatted_text="$ uname -a",
                table_html="<table><tr><td>$ uname -a</td></tr></table>",
                content_sha256="hash-tbl",
            )
        ],
    )
    final_ir = _create_dummy_ir([
        PreformattedBlock(
            id="b-tbl",
            page_idx=0,
            reading_order=0,
            subtype="terminal_output",
            text="totally fabricated text not in source",
        )
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    assert len(ledger) == 1
    assert "Fabricated text" in (ledger[0].reason or "")

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert any(v.code == "FABRICATED_REPRESENTATION_TEXT" for v in violations)


def test_e_footnote_loss_fails_preservation() -> None:
    """Test E: Source footnote missing in final BookIR -> FAIL."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="b-fn",
                page_idx=0,
                reading_order=0,
                source_type="footnote",
                footnote_text="[1] Crucial citation",
                content_sha256="fn-hash",
            )
        ],
    )
    final_ir = _create_dummy_ir([
        Paragraph(id="b-fn", page_idx=0, reading_order=0, inlines=[Text(text="regular text")])
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert any(v.code == "FOOTNOTE_LOSS" for v in violations)


def test_f_paragraph_merge_trace_passes() -> None:
    """Test F: Cross-page paragraph merge trace -> PASS without false-positive content loss."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p-1",
                page_idx=0,
                reading_order=0,
                source_type="paragraph",
                plain_text="This is sentence one. ",
                content_sha256="h1",
            ),
            SemanticEvidenceBlock(
                block_id="p-2",
                page_idx=1,
                reading_order=0,
                source_type="paragraph",
                plain_text="This is sentence two.",
                content_sha256="h2",
            ),
        ],
    )
    final_ir = _create_dummy_ir([
        Paragraph(
            id="p-1",
            page_idx=0,
            reading_order=0,
            inlines=[
                Text(
                    text="This is sentence one. This is sentence two.",
                    source_segments=[
                        SourceTextSegment(
                            segment_id="p-1-s0",
                            page_idx=0,
                            block_id="p-1",
                            text="This is sentence one. ",
                            text_sha256="h1",
                        ),
                        SourceTextSegment(
                            segment_id="p-2-s0",
                            page_idx=1,
                            block_id="p-2",
                            text="This is sentence two.",
                            text_sha256="h2",
                        ),
                    ],
                )
            ],
        )
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    entry_p2 = next(e for e in ledger if e.source_block_id == "p-2")
    assert entry_p2.disposition == "paragraph_merged"
    assert entry_p2.final_block_ids == ["p-1"]

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert not any(v.code == "CONTENT_LOSS" for v in violations)


def test_g_unexplained_asset_loss_fails() -> None:
    """Test G: Unexplained figure asset disappearance -> FAIL."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="fig-1",
                page_idx=0,
                reading_order=0,
                source_type="figure",
                asset_ids=["img_001.png"],
                content_sha256="h-fig",
            )
        ],
    )
    final_ir = _create_dummy_ir([
        Figure(id="fig-1", page_idx=0, reading_order=0, asset_id="")
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert any("ASSET_LOSS" in v.code for v in violations)


def test_h_authoritative_ocr_writer_artifact_passes(tmp_path: Path) -> None:
    """Test H: Authoritative OCRCorrectionAuditFile validated by QA reader -> PASS."""
    audit_file = tmp_path / "ocr_corrections.json"
    record = OCRAuditRecord(
        block_id="b-code",
        segment_id="seg-1",
        page_idx=0,
        bbox=[10.0, 20.0, 100.0, 40.0],
        old_text="wh1le (true)",
        old_sha256=compute_text_sha256("wh1le (true)"),
        new_text="while (true)",
        new_sha256=compute_text_sha256("while (true)"),
        provider="mock",
        model="mock",
        first_confidence=0.996,
        confirmation_confidence=0.996,
        confirmation_result=True,
        confirmation_observed_text="while (true)",
        visible_error_type="character_substitution",
        mode="safe",
        status="applied",
    )
    audit_data = OCRCorrectionAuditFile(
        mode="safe",
        candidate_count=1,
        applied_count=1,
        rejected_count=0,
        changed_codepoints=1,
        audits=[record],
    )
    audit_file.write_text(audit_data.model_dump_json(indent=2), encoding="utf-8")

    metrics, violations = evaluate_ocr_qa(audit_file, cfg_mode="safe")
    assert metrics.ocr_applied_count == 1
    assert len(violations) == 0


def test_i_ocr_violation_strict_failure(tmp_path: Path) -> None:
    """Test I: OCR invariant violation (hash mismatch) triggers strict release gate failure."""
    work_dir = tmp_path / "work"
    paths = create_job_paths(work_dir)
    paths.semantic_dir.mkdir(parents=True, exist_ok=True)
    paths.qa_dir.mkdir(parents=True, exist_ok=True)

    record = OCRAuditRecord(
        block_id="b-code",
        segment_id="seg-1",
        page_idx=0,
        bbox=[10.0, 20.0, 100.0, 40.0],
        old_text="while",
        old_sha256="corrupted_hash",
        new_text="while",
        new_sha256=compute_text_sha256("while"),
        provider="mock",
        model="mock",
        first_confidence=0.9,
        visible_error_type="character_substitution",
        mode="safe",
        status="applied",
    )
    audit_data = OCRCorrectionAuditFile(
        mode="safe",
        candidate_count=1,
        applied_count=1,
        rejected_count=0,
        changed_codepoints=0,
        audits=[record],
    )
    paths.semantic_ocr_corrections_json.write_text(
        audit_data.model_dump_json(indent=2), encoding="utf-8"
    )

    raw_middle = tmp_path / "middle.json"
    raw_middle.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")
    book_ir = _create_dummy_ir([])

    render_result = _create_dummy_render_result(paths.render_oebps_dir)
    packaging_result = _create_dummy_packaging_result(tmp_path / "out.epub")
    cfg = JobConfig(
        app=AppConfig(strict=True),
        ocr_correction=OCRCorrectionConfig(mode="safe"),
    )

    with pytest.raises(RuntimeError, match="Strict QA release gate failed"):
        run_conversion_m5(
            paths=paths,
            raw_middle_path=raw_middle,
            book_ir=book_ir,
            render_result=render_result,
            packaging_result=packaging_result,
            cfg=cfg,
        )


def test_j_presentation_violation_strict_failure(tmp_path: Path) -> None:
    """Test J: Presentation violation (forbidden CSS position:absolute) fails strict gate."""
    work_dir = tmp_path / "work"
    paths = create_job_paths(work_dir)
    paths.qa_dir.mkdir(parents=True, exist_ok=True)
    paths.render_oebps_dir.mkdir(parents=True, exist_ok=True)
    (paths.render_oebps_dir / "styles").mkdir(parents=True, exist_ok=True)
    (paths.render_oebps_dir / "text").mkdir(parents=True, exist_ok=True)

    (paths.render_oebps_dir / "styles" / "book.css").write_text(
        "p { position: absolute; }", encoding="utf-8"
    )
    (paths.render_oebps_dir / "text" / "p1.xhtml").write_text(
        "<?xml version='1.0'?><html xmlns='http://www.w3.org/1999/xhtml'><body><p>Hi</p></body></html>",
        encoding="utf-8",
    )

    raw_middle = tmp_path / "middle.json"
    raw_middle.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")
    book_ir = _create_dummy_ir([])

    render_result = _create_dummy_render_result(paths.render_oebps_dir)
    packaging_result = _create_dummy_packaging_result(tmp_path / "out.epub")
    cfg = JobConfig(
        app=AppConfig(strict=True),
        presentation=PresentationConfig(mode="enhanced"),
    )

    with pytest.raises(RuntimeError, match="Strict QA release gate failed"):
        run_conversion_m5(
            paths=paths,
            raw_middle_path=raw_middle,
            book_ir=book_ir,
            render_result=render_result,
            packaging_result=packaging_result,
            cfg=cfg,
        )


def test_k_semantic_code_retype_reconciliation_passes() -> None:
    """Test K: Semantic table -> code retype is reconciled in Code Reconciliation Check."""
    raw_middle_data = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {"type": "table", "lines": [{"spans": [{"type": "text", "content": "$ ls"}]}]}
                ],
            }
        ]
    }
    book_ir = _create_dummy_ir([
        PreformattedBlock(
            id="b-1", page_idx=0, reading_order=0, subtype="terminal_output", text="$ ls"
        )
    ])
    ledger = [
        PreservationLedgerEntry(
            source_block_id="b-1",
            source_kind="table",
            source_content_sha256="hash",
            final_block_ids=["b-1"],
            final_kinds=["preformatted"],
            final_content_sha256s=["hash"],
            disposition="retyped",
            reason="Retyped to terminal_output",
        )
    ]
    render_result = _create_dummy_render_result(Path("oebps"), code_count=1)

    results, _ = run_structural_checks(
        raw_middle_data=raw_middle_data,
        book_ir=book_ir,
        render_result=render_result,
        packaging_result=_create_dummy_packaging_result(Path("out.epub")),
        preservation_ledger=ledger,
    )
    code_check = next(c for c in results if c.name == "Code Reconciliation Check")
    assert code_check.passed


def test_l_missing_semantic_block_lost_error_strict_fails(tmp_path: Path) -> None:
    """Test L: Missing source evidence block marked lost_error triggers strict failure."""
    work_dir = tmp_path / "work"
    paths = create_job_paths(work_dir)
    paths.semantic_dir.mkdir(parents=True, exist_ok=True)
    paths.qa_dir.mkdir(parents=True, exist_ok=True)

    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="b-lost",
                page_idx=0,
                reading_order=0,
                source_type="paragraph",
                plain_text="I will be lost",
                content_sha256="lost-hash",
            )
        ],
    )
    paths.semantic_evidence_json.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")

    raw_middle = tmp_path / "middle.json"
    raw_middle.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")
    book_ir = _create_dummy_ir([])

    render_result = _create_dummy_render_result(paths.render_oebps_dir)
    packaging_result = _create_dummy_packaging_result(tmp_path / "out.epub")
    cfg = JobConfig(app=AppConfig(strict=True))

    with pytest.raises(RuntimeError, match="Strict QA release gate failed"):
        run_conversion_m5(
            paths=paths,
            raw_middle_path=raw_middle,
            book_ir=book_ir,
            render_result=render_result,
            packaging_result=packaging_result,
            cfg=cfg,
        )


def test_m_outline_cycle_detected() -> None:
    """Test M: BookOutline cycle detected -> FAIL."""
    n1 = OutlineNode(
        node_id="n1",
        title="Node 1",
        level=1,
        heading_block_id="h1",
        first_block_id="h1",
        parent_node_id="n2",
    )
    n2 = OutlineNode(
        node_id="n2",
        title="Node 2",
        level=2,
        heading_block_id="h2",
        first_block_id="h2",
        parent_node_id="n1",
    )
    outline = BookOutline(
        schema_version="1.0",
        nodes={"n1": n1, "n2": n2},
    )
    book_ir = _create_dummy_ir([
        Heading(id="h1", level=1, page_idx=0, reading_order=0, inlines=[Text(text="Node 1")]),
        Heading(id="h2", level=2, page_idx=0, reading_order=1, inlines=[Text(text="Node 2")]),
    ])
    _, violations = evaluate_outline_qa(outline, book_ir)
    assert any("OUTLINE_CYCLE" in v.code for v in violations)


def test_n_outline_non_monotonic_order() -> None:
    """Test N: Outline nodes appearing non-monotonically in document order -> FAIL."""
    n1 = OutlineNode(
        node_id="n1", title="First", level=1, heading_block_id="h2", first_block_id="h2"
    )
    n2 = OutlineNode(
        node_id="n2", title="Second", level=1, heading_block_id="h1", first_block_id="h1"
    )
    outline = BookOutline(
        schema_version="1.0",
        nodes={"n1": n1, "n2": n2},
    )
    book_ir = _create_dummy_ir([
        Heading(id="h1", level=1, page_idx=0, reading_order=0, inlines=[Text(text="Second")]),
        Heading(id="h2", level=1, page_idx=0, reading_order=10, inlines=[Text(text="First")]),
    ])
    _, violations = evaluate_outline_qa(outline, book_ir)
    assert any(v.code == "OUTLINE_NON_MONOTONIC" for v in violations)


def test_o_broken_toc_target_fragment(tmp_path: Path) -> None:
    """Test O: Broken TOC target fragment in XHTML -> FAIL."""
    oebps_dir = tmp_path / "OEBPS"
    text_dir = oebps_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    (text_dir / "chapter1.xhtml").write_text(
        "<?xml version='1.0'?><html xmlns='http://www.w3.org/1999/xhtml'><body>"
        "<h1 id='real-target'>Title</h1></body></html>",
        encoding="utf-8",
    )

    toc_entries = [
        TocEntry(title="Broken Entry", href="text/chapter1.xhtml#nonexistent-target", level=1)
    ]
    n1 = OutlineNode(
        node_id="n1", title="Title", level=1, heading_block_id="h1", first_block_id="h1"
    )
    outline = BookOutline(
        schema_version="1.0",
        nodes={"n1": n1},
    )
    book_ir = _create_dummy_ir([
        Heading(id="h1", level=1, page_idx=0, reading_order=0, inlines=[Text(text="Title")])
    ])

    _, violations = evaluate_outline_qa(
        outline, book_ir, oebps_dir=oebps_dir, toc_entries=toc_entries
    )
    assert any(v.code == "BROKEN_TOC_TARGET" for v in violations)


def test_p_table_terminal_visual_reject_restores_table() -> None:
    """Test P: Table -> terminal -> visual reject preserves Table across ledger and BookIR."""
    table_html = "<table><tr><th>Col</th></tr><tr><td>Val</td></tr></table>"
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="tbl-1",
                page_idx=0,
                reading_order=0,
                source_type="table",
                table_html=table_html,
                content_sha256=compute_text_sha256(table_html),
            )
        ],
    )
    audits = [
        SemanticAuditRecord(
            decision_id="dec-1",
            block_id="tbl-1",
            source_kind="table",
            proposed_target="terminal_output",
            final_target="table",
            confidence=0.5,
            provider="mock",
            model="mock",
            status="preserved_original_conflict",
            evidence_codes=["VISUAL_ADJUDICATION_REJECTED"],
            rejection_reason="Visual review confirmed genuine tabular layout",
        )
    ]
    final_ir = _create_dummy_ir([
        Table(id="tbl-1", page_idx=0, reading_order=0, html=table_html)
    ])

    ledger = build_preservation_ledger(evidence, final_ir, audits=audits)
    assert len(ledger) == 1
    assert ledger[0].disposition == "unchanged"
    assert ledger[0].final_kinds == ["table"]
    assert ledger[0].semantic_decision_ids == ["dec-1"]

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert len(violations) == 0


def test_q_paragraph_merge_without_provenance_fails() -> None:
    """Test Q: Substring match without SourceTextSegment provenance must NOT pass as merged."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p-1",
                page_idx=0,
                reading_order=0,
                source_type="paragraph",
                plain_text="Sentence one. ",
                content_sha256="h1",
            ),
            SemanticEvidenceBlock(
                block_id="p-2",
                page_idx=1,
                reading_order=0,
                source_type="paragraph",
                plain_text="Sentence two.",
                content_sha256="h2",
            ),
        ],
    )
    # Paragraph p-1 happens to contain substring 'Sentence two.', but lacks provenance for p-2
    final_ir = _create_dummy_ir([
        Paragraph(
            id="p-1",
            page_idx=0,
            reading_order=0,
            inlines=[
                Text(
                    text="Sentence one. Sentence two.",
                    source_segments=[
                        SourceTextSegment(
                            segment_id="p-1-s0",
                            page_idx=0,
                            block_id="p-1",
                            text="Sentence one. ",
                            text_sha256="h1",
                        )
                    ],
                )
            ],
        )
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    entry_p2 = next(e for e in ledger if e.source_block_id == "p-2")
    assert entry_p2.disposition == "lost_error"

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert any(v.code == "CONTENT_LOSS" and v.block_id == "p-2" for v in violations)


def test_r_image_not_superseded_by_unrelated_table() -> None:
    """Test R: Unrelated image is not falsely marked superseded because a Table exists."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="img-1",
                page_idx=0,
                reading_order=0,
                source_type="image",
                asset_ids=["unrelated_chart.png"],
                content_sha256="h-img",
            )
        ],
    )
    # A table exists, but has no relation to img-1
    final_ir = _create_dummy_ir([
        Table(
            id="tbl-1",
            page_idx=0,
            reading_order=0,
            html="<table><tr><td>Data</td></tr></table>",
            fallback_asset_id=None,
        )
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    entry_img = next(e for e in ledger if e.source_block_id == "img-1")
    assert entry_img.disposition == "lost_error"

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert any(v.code == "CONTENT_LOSS" and v.block_id == "img-1" for v in violations)


def test_s_per_block_footnote_loss_detected_when_other_footnote_exists() -> None:
    """Test S: Per-block footnote loss is caught even if another block has a footnote."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p-1",
                page_idx=0,
                reading_order=0,
                source_type="paragraph",
                footnote_text="Footnote for P1",
                content_sha256="h1",
            ),
            SemanticEvidenceBlock(
                block_id="p-2",
                page_idx=0,
                reading_order=1,
                source_type="paragraph",
                footnote_text="Footnote for P2",
                content_sha256="h2",
            ),
        ],
    )
    # P1 lost its footnote, but P2 retained its footnote
    final_ir = _create_dummy_ir([
        Paragraph(id="p-1", page_idx=0, reading_order=0, inlines=[Text(text="P1 text")]),
        Paragraph(
            id="p-2",
            page_idx=0,
            reading_order=1,
            inlines=[Text(text="P2 text")],
        ),
        Footnote(
            id="p-2-fn",
            page_idx=0,
            reading_order=2,
            inlines=[Text(text="Footnote for P2")],
            sources=[],
        ),
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    # Must flag FOOTNOTE_LOSS specifically for p-1
    assert any(v.code == "FOOTNOTE_LOSS" and v.block_id == "p-1" for v in violations)


def test_t_per_block_caption_loss_detected() -> None:
    """Test T: Caption loss is detected when evidence had caption and final block does not."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="tbl-1",
                page_idx=0,
                reading_order=0,
                source_type="table",
                table_html="<table><tr><td>A</td></tr></table>",
                caption_text="Table 1: Important Results",
                content_sha256="h-tbl",
            )
        ],
    )
    final_ir = _create_dummy_ir([
        Table(
            id="tbl-1",
            page_idx=0,
            reading_order=0,
            html="<table><tr><td>A</td></tr></table>",
            caption=[],  # Caption lost
        )
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert any(v.code == "CAPTION_LOSS" and v.block_id == "tbl-1" for v in violations)


def test_u_latin_whitespace_removal_fails_preservation() -> None:
    """Test U: Latin whitespace removal ('foo bar' -> 'foobar') is rejected as corruption."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p-1",
                page_idx=0,
                reading_order=0,
                source_type="paragraph",
                plain_text="foo bar",
                content_sha256=compute_text_sha256("foo bar"),
            )
        ],
    )
    final_ir = _create_dummy_ir([
        Paragraph(id="p-1", page_idx=0, reading_order=0, inlines=[Text(text="foobar")])
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    assert "Text mismatch" in (ledger[0].reason or "")

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert any(v.code == "TEXT_FABRICATION_OR_CORRUPTION" for v in violations)


def test_v_cjk_whitespace_removal_passes_preservation() -> None:
    """Test V: CJK spacing differences ('日 本 語' -> '日本語') pass preservation."""
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p-1",
                page_idx=0,
                reading_order=0,
                source_type="paragraph",
                plain_text="日 本 語",
                content_sha256=compute_text_sha256("日 本 語"),
            )
        ],
    )
    final_ir = _create_dummy_ir([
        Paragraph(id="p-1", page_idx=0, reading_order=0, inlines=[Text(text="日本語")])
    ])

    ledger = build_preservation_ledger(evidence, final_ir)
    assert "Text mismatch" not in (ledger[0].reason or "")

    violations = evaluate_preservation_qa(ledger, evidence, final_ir)
    assert not any(v.code == "TEXT_FABRICATION_OR_CORRUPTION" for v in violations)


def test_w_remote_url_in_book_css_fails_presentation_qa(tmp_path: Path) -> None:
    """Test W: Remote resource reference in book.css fails presentation QA."""
    styles_dir = tmp_path / "styles"
    styles_dir.mkdir(parents=True, exist_ok=True)
    css_file = styles_dir / "book.css"
    css_file.write_text(
        "@import url('https://fonts.googleapis.com/css2?family=Roboto');\nbody { margin: 0; }",
        encoding="utf-8",
    )

    metrics, violations = evaluate_presentation_qa(oebps_dir=tmp_path)
    assert any("forbidden remote resource reference" in v for v in violations)


def test_x_atomic_epub_promotion_failure_does_not_replace_output(tmp_path: Path) -> None:
    """Test X: Strict release gate failure prevents atomic promotion of EPUB."""
    from unittest.mock import patch

    work_dir = tmp_path / "work"
    paths = create_job_paths(work_dir)
    paths.semantic_dir.mkdir(parents=True, exist_ok=True)
    paths.qa_dir.mkdir(parents=True, exist_ok=True)
    paths.render_oebps_dir.mkdir(parents=True, exist_ok=True)

    target_epub = tmp_path / "final_book.epub"
    target_epub.write_bytes(b"ORIGINAL_VALID_CONTENT")

    raw_middle = tmp_path / "middle.json"
    raw_middle.write_text(json.dumps({"pdf_info": []}), encoding="utf-8")
    book_ir = _create_dummy_ir([])

    render_result = _create_dummy_render_result(paths.render_oebps_dir)
    cfg = JobConfig(app=AppConfig(strict=True))

    from book2epub.pipeline import run_pipeline

    # Mock M1, M2, M3, M4 to create tmp epub and run M5
    gate_err = RuntimeError("Strict QA release gate failed")
    with patch("book2epub.pipeline.run_conversion_m1", return_value=(paths, raw_middle)), \
         patch("book2epub.pipeline.run_conversion_m2", return_value=(paths, book_ir)), \
         patch("book2epub.pipeline.run_conversion_m3", return_value=render_result), \
         patch("book2epub.pipeline.run_conversion_m4") as mock_m4, \
         patch("book2epub.pipeline.run_conversion_m5", side_effect=gate_err):

        def fake_m4(res, out_epub, p, c):
            out_epub.write_bytes(b"CANDIDATE_EPUB")
            return _create_dummy_packaging_result(out_epub)

        mock_m4.side_effect = fake_m4

        with pytest.raises(RuntimeError, match="Strict QA release gate failed"):
            run_pipeline(tmp_path / "pages", target_epub, cfg)

    # Verify original epub was NOT replaced
    assert target_epub.read_bytes() == b"ORIGINAL_VALID_CONTENT"
    # Verify temporary file was cleaned up
    tmp_epub = target_epub.with_suffix(".epub.tmp")
    assert not tmp_epub.exists()

