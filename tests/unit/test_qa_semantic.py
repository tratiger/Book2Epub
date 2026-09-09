"""Unit tests for semantic QA evaluation and preservation ledger (Appendix N2-N4)."""

from book2epub.ir.models import (
    BookIR,
    Heading,
    Paragraph,
    PreformattedBlock,
    SourceDocument,
    SourcePage,
    Text,
)
from book2epub.qa.semantic import (
    build_preservation_ledger,
    evaluate_semantic_transitions,
    validate_outline_qa,
)
from book2epub.semantic.decisions import SemanticAuditRecord
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
