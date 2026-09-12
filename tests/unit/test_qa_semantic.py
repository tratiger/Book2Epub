"""Unit tests for semantic QA evaluation and preservation ledger (Appendix N2-N4)."""

from book2epub.ir.models import (
    BookIR,
    CodeBlock,
    Heading,
    PageBoundary,
    Paragraph,
    PreformattedBlock,
    SourceDocument,
    SourcePage,
    SourceRef,
    SourceTextSegment,
    Text,
)
from book2epub.qa.semantic import (
    build_preservation_ledger,
    evaluate_semantic_transitions,
    validate_outline_qa,
)
from book2epub.semantic.decisions import SemanticAuditRecord
from book2epub.semantic.hashing import compute_content_sha256, compute_text_sha256
from book2epub.semantic.models import (
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)
from book2epub.semantic.structure import BookOutline, OutlineNode


def test_build_preservation_ledger_retyped_and_same_type() -> None:
    """Verify preservation ledger correctly classifies same type, retyped, and suppressed."""
    ev_blocks = [
        SemanticEvidenceBlock(
            block_id="b-tbl",
            page_idx=0,
            reading_order=0,
            source_type="table",
            content_sha256="hash1",
        ),
        SemanticEvidenceBlock(
            block_id="b-p",
            page_idx=0,
            reading_order=1,
            source_type="text",
            content_sha256="hash2",
        ),
        SemanticEvidenceBlock(
            block_id="b-header",
            page_idx=0,
            reading_order=2,
            source_type="header",
            content_sha256="hash3",
        ),
    ]
    evidence = SemanticEvidenceBook(
        job_id="test-job",
        source_middle_sha256="m-hash",
        raw_bookir_sha256="r-hash",
        blocks=ev_blocks,
    )

    # In final BookIR:
    # b-tbl was retyped to terminal_output (PreformattedBlock)
    # b-p remains paragraph
    # b-header was suppressed
    final_blocks = [
        PreformattedBlock(id="b-tbl", text="$ ls", subtype="terminal_output"),
        Paragraph(id="b-p", inlines=[Text(text="Hello")]),
    ]
    bookir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=final_blocks,
    )

    ledger = build_preservation_ledger(evidence, bookir)
    assert len(ledger) == 3

    entry_tbl = next(e for e in ledger if e.block_id == "b-tbl")
    assert entry_tbl.disposition == "preserved_retyped"
    assert entry_tbl.final_kind == "preformatted"

    entry_p = next(e for e in ledger if e.block_id == "b-p")
    assert entry_p.disposition == "preserved_same_type"
    assert entry_p.final_kind == "paragraph"

    entry_h = next(e for e in ledger if e.block_id == "b-header")
    assert entry_h.disposition == "suppressed_boilerplate"
    assert entry_h.final_kind == "none"


def test_preservation_accepts_audited_source_backed_paragraph_merge() -> None:
    seg1 = SourceTextSegment(
        segment_id="p1-s1",
        page_idx=0,
        block_id="p1",
        text="first",
        text_sha256=compute_text_sha256("first"),
    )
    seg2 = SourceTextSegment(
        segment_id="p2-s1",
        page_idx=1,
        block_id="p2",
        text="second",
        text_sha256=compute_text_sha256("second"),
    )
    merged = Paragraph(
        id="p1",
        sources=[
            SourceRef(page_idx=0, source_type="text"),
            SourceRef(page_idx=1, source_type="text"),
        ],
        inlines=[
            Text(text="first", source_segments=[seg1]),
            PageBoundary(page_idx=1),
            Text(text="second", source_segments=[seg2]),
        ],
    )
    evidence = SemanticEvidenceBook(
        source_middle_sha256="m",
        raw_bookir_sha256="r",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                page_idx=0,
                source_type="text",
                plain_text="first",
                content_sha256=compute_content_sha256(plain_text="first"),
            ),
            SemanticEvidenceBlock(
                block_id="p2",
                page_idx=1,
                source_type="text",
                plain_text="second",
                content_sha256=compute_content_sha256(plain_text="second"),
            ),
        ],
    )
    audit = SemanticAuditRecord(
        decision_id="pass-a-cont-p2",
        block_id="p2",
        source_kind="paragraph",
        proposed_target="paragraph_continuation",
        final_target="merged_continuation",
        confidence=0.95,
        provider="structure",
        model="structure",
        status="applied",
    )

    ledger = build_preservation_ledger(
        evidence,
        BookIR(
            source=SourceDocument(page_count=2),
            blocks=[merged],
        ),
        audits=[audit],
    )

    entry = next(item for item in ledger if item.source_block_id == "p1")
    assert "Text mismatch" not in (entry.reason or "")

    same_page_evidence = evidence.model_copy(
        update={
            "blocks": [
                evidence.blocks[0],
                evidence.blocks[1].model_copy(update={"page_idx": 0}),
            ]
        }
    )
    same_page_ledger = build_preservation_ledger(
        same_page_evidence,
        BookIR(source=SourceDocument(page_count=1), blocks=[merged]),
        audits=[audit],
    )
    same_page_entry = next(item for item in same_page_ledger if item.source_block_id == "p1")
    assert "Text mismatch" in (same_page_entry.reason or "")


def test_preservation_compares_code_body_separately_from_caption() -> None:
    caption = r"\$ ls -l outline.01"
    body = "-rwxr-x--- 1 molay users 1064 Jun 29 00:39 outline.01"
    evidence = SemanticEvidenceBook(
        source_middle_sha256="m",
        raw_bookir_sha256="r",
        blocks=[
            SemanticEvidenceBlock(
                block_id="code-1",
                source_type="code",
                plain_text=f"{caption}\n{body}",
                preformatted_text=f"{caption}\n{body}",
                caption_text=caption,
                content_sha256=compute_content_sha256(
                    plain_text=f"{caption}\n{body}",
                    preformatted_text=f"{caption}\n{body}",
                    caption_text=caption,
                ),
            )
        ],
    )
    code = CodeBlock(id="code-1", text=body, caption=[Text(text=caption)])

    ledger = build_preservation_ledger(
        evidence,
        BookIR(source=SourceDocument(page_count=1), blocks=[code]),
    )

    assert "Text mismatch" not in (ledger[0].reason or "")


def test_evaluate_semantic_transitions() -> None:
    """Verify semantic change rate, auto-apply rate, and transitions matrix."""
    audits = [
        SemanticAuditRecord(
            decision_id="d1",
            block_id="b1",
            source_kind="table",
            proposed_target="preformatted",
            final_target="preformatted",
            confidence=0.95,
            provider="mock",
            model="mock",
            status="applied",
        ),
        SemanticAuditRecord(
            decision_id="d2",
            block_id="b2",
            source_kind="paragraph",
            proposed_target="paragraph",
            final_target="paragraph",
            confidence=0.99,
            provider="mock",
            model="mock",
            status="applied",
        ),
        SemanticAuditRecord(
            decision_id="d3",
            block_id="b3",
            source_kind="heading",
            proposed_target="heading",
            final_target="heading",
            confidence=0.60,
            provider="mock",
            model="mock",
            status="preserved_original_conflict",
        ),
    ]
    bookir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=[Heading(id="h1", level=1, inlines=[Text(text="H1")])],
    )

    metrics = evaluate_semantic_transitions(None, bookir, audits)
    assert metrics.semantic_review_rate == 1.0
    assert metrics.semantic_auto_apply_rate == round(2 / 3, 4)
    assert metrics.semantic_conflict_rate == round(1 / 3, 4)
    assert metrics.type_transitions == {"table -> preformatted": 1}


def test_validate_outline_qa() -> None:
    """Verify outline validation checks that heading IDs exist in BookIR."""
    h1 = Heading(id="h-1", level=1, inlines=[Text(text="Chapter 1")])
    bookir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=[h1],
    )

    # Valid outline
    valid_outline = BookOutline(
        nodes={
            "n-1": OutlineNode(
                node_id="n-1",
                heading_block_id="h-1",
                level=1,
                first_block_id="h-1",
                title="Chapter 1",
            )
        }
    )
    ok, warns = validate_outline_qa(valid_outline, bookir)
    assert ok
    assert len(warns) == 0

    # Invalid outline referencing non-existent heading
    invalid_outline = BookOutline(
        nodes={
            "n-missing": OutlineNode(
                node_id="n-missing",
                heading_block_id="h-missing",
                level=1,
                first_block_id="h-missing",
                title="Missing",
            )
        }
    )
    bad_ok, bad_warns = validate_outline_qa(invalid_outline, bookir)
    assert not bad_ok
    assert len(bad_warns) == 1
    assert "h-missing" in bad_warns[0]
