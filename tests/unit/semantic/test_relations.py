"""Production-path relation reconciliation and materialization tests."""

from book2epub.ir.models import (
    BookIR,
    Callout,
    Chart,
    ExampleBlock,
    Figure,
    Heading,
    Paragraph,
    SourceDocument,
    SourceRef,
    SourceTextSegment,
    Text,
)
from book2epub.qa.semantic import build_preservation_ledger
from book2epub.semantic.apply import apply_semantic_relations
from book2epub.semantic.decisions import (
    SemanticDecisionBatch,
    SemanticRelationAuditRecord,
    SemanticRelationDecision,
)
from book2epub.semantic.models import SemanticEvidenceBlock, SemanticEvidenceBook
from book2epub.semantic.reconcile import ReconciledSemanticDecision
from book2epub.semantic.relations import (
    ReconciledRelation,
    reconcile_relation_batches,
)


def _source(page_idx: int, source_type: str = "text") -> SourceRef:
    return SourceRef(page_idx=page_idx, source_type=source_type)


def _paragraph(block_id: str, text: str, page_idx: int = 0) -> Paragraph:
    return Paragraph(
        id=block_id,
        sources=[_source(page_idx)],
        inlines=[Text(text=text)],
    )


def _relation(
    relation_type: str,
    source_ids: list[str],
    target_id: str | None,
    confidence: float = 0.95,
) -> ReconciledRelation:
    return ReconciledRelation(
        relation_type=relation_type,  # type: ignore[arg-type]
        source_block_ids=source_ids,
        target_block_id=target_id,
        confidence=confidence,
    )


def test_figure_and_chart_caption_attach_and_remove_standalone_source() -> None:
    caption = _paragraph("caption", "Figure 1: Architecture")
    figure = Figure(id="figure", sources=[_source(0)], asset_id="asset-1")
    chart_caption = _paragraph("chart-caption", "Chart 1: Results")
    chart = Chart(id="chart", sources=[_source(1)], asset_id="asset-2")

    updated, audits = apply_semantic_relations(
        [caption, figure, chart_caption, chart],
        [
            _relation("caption_of", ["caption"], "figure"),
            _relation("caption_of", ["chart-caption"], "chart"),
        ],
    )

    assert [block.id for block in updated] == ["figure", "chart"]
    assert updated[0].caption[0].model_dump() == caption.inlines[0].model_dump()  # type: ignore[attr-defined]
    assert updated[1].caption[0].model_dump() == chart_caption.inlines[0].model_dump()  # type: ignore[attr-defined]
    assert [audit.status for audit in audits] == ["applied", "applied"]


def test_caption_more_than_one_page_away_is_rejected() -> None:
    caption = _paragraph("caption", "Figure 1", page_idx=0)
    figure = Figure(id="figure", sources=[_source(2)], asset_id="asset")
    updated, audits = apply_semantic_relations(
        [caption, figure], [_relation("caption_of", ["caption"], "figure")]
    )
    assert [block.id for block in updated] == ["caption", "figure"]
    assert audits[0].status == "rejected"


def test_footnote_attach_preserves_source_segment_provenance() -> None:
    segment = SourceTextSegment(
        segment_id="fn-segment",
        page_idx=0,
        block_id="footnote",
        text="See source.",
        text_sha256="source-hash",
    )
    footnote = Paragraph(
        id="footnote",
        sources=[_source(0)],
        inlines=[Text(text="See source.", source_segments=[segment])],
    )
    figure = Figure(id="figure", sources=[_source(0)], asset_id="asset")
    updated, audits = apply_semantic_relations(
        [footnote, figure], [_relation("footnote_of", ["footnote"], "figure")]
    )
    assert audits[0].status == "applied"
    assert len(updated) == 1
    attached = updated[0].footnotes[0]
    assert isinstance(attached, Text)
    assert attached.source_segments[0].segment_id == "fn-segment"
    assert attached.source_segments[0].text_sha256 == "source-hash"


def test_callout_contiguous_group_gets_deterministic_wrapper_and_keeps_children() -> None:
    first = _paragraph("p1", "Warning:", page_idx=0)
    second = _paragraph("p2", "Do not delete the cache.", page_idx=0)
    decision = ReconciledSemanticDecision(
        block_id="p1",
        target="callout_warning",
        heading_level=None,
        confidence=0.95,
    )
    updated, audits = apply_semantic_relations(
        [first, second],
        [_relation("member_of_callout", ["p1", "p2"], None)],
        semantic_decisions={"p1": decision},
    )
    assert audits[0].status == "applied"
    assert len(updated) == 1
    assert isinstance(updated[0], Callout)
    assert updated[0].subtype == "warning"
    assert [child.id for child in updated[0].blocks] == ["p1", "p2"]
    assert updated[0].id.startswith("relation-member_of_callout-")


def test_callout_group_crossing_heading_is_rejected() -> None:
    first = _paragraph("p1", "Note", page_idx=0)
    heading = Heading(id="heading", sources=[_source(0)], inlines=[Text(text="Next")])
    second = _paragraph("p2", "Details", page_idx=0)
    updated, audits = apply_semantic_relations(
        [first, heading, second],
        [_relation("member_of_callout", ["p1", "p2"], None)],
        semantic_decisions={
            "p1": ReconciledSemanticDecision(
                block_id="p1",
                target="callout_note",
                heading_level=None,
                confidence=0.95,
            )
        },
    )
    assert [block.id for block in updated] == ["p1", "heading", "p2"]
    assert audits[0].status == "rejected"


def test_example_group_materializes_wrapper_with_original_children() -> None:
    first = _paragraph("e1", "Input", page_idx=0)
    second = _paragraph("e2", "Output", page_idx=0)
    updated, audits = apply_semantic_relations(
        [first, second], [_relation("member_of_example", ["e1", "e2"], None)]
    )
    assert audits[0].status == "applied"
    assert isinstance(updated[0], ExampleBlock)
    assert [child.id for child in updated[0].blocks] == ["e1", "e2"]


def test_same_caption_to_two_targets_is_conflict_not_high_confidence_winner() -> None:
    batch = SemanticDecisionBatch(
        chunk_id="chunk-1",
        relations=[
            SemanticRelationDecision(
                relation_type="caption_of",
                source_block_ids=["caption"],
                target_block_id="figure-1",
                confidence=0.90,
            ),
            SemanticRelationDecision(
                relation_type="caption_of",
                source_block_ids=["caption"],
                target_block_id="figure-2",
                confidence=0.99,
            ),
        ],
    )
    reconciled, conflicts = reconcile_relation_batches([batch])
    assert len(conflicts) == 1
    assert all(relation.is_conflict for relation in reconciled.values())


def test_unknown_relation_block_is_rejected_and_audited() -> None:
    figure = Figure(id="figure", sources=[_source(0)], asset_id="asset")
    updated, audits = apply_semantic_relations(
        [figure], [_relation("caption_of", ["ghost"], "figure")]
    )
    assert [block.id for block in updated] == ["figure"]
    assert audits[0].status == "rejected"
    assert "ghost" in (audits[0].rejection_reason or "")


def test_paragraph_continuation_requires_adjacent_page_boundary() -> None:
    first = _paragraph("p1", "first", page_idx=0)
    second = _paragraph("p2", "second", page_idx=1)
    updated, audits = apply_semantic_relations(
        [first, second], [_relation("paragraph_continuation", ["p1"], "p2")]
    )
    assert len(updated) == 1
    assert updated[0].id == "p1"
    assert audits[0].status == "applied"


def test_applied_caption_relation_is_accounted_for_by_preservation_ledger() -> None:
    caption = _paragraph("caption", "Figure 1: System")
    figure = Figure(id="figure", sources=[_source(0)], asset_id="asset")
    updated, relation_audits = apply_semantic_relations(
        [caption, figure], [_relation("caption_of", ["caption"], "figure")]
    )
    bookir = BookIR(source=SourceDocument(page_count=1), blocks=updated)
    evidence = SemanticEvidenceBook(
        source_middle_sha256="middle",
        raw_bookir_sha256="raw",
        blocks=[
            SemanticEvidenceBlock(
                block_id="caption",
                source_type="text",
                plain_text="Figure 1: System",
            ),
            SemanticEvidenceBlock(block_id="figure", source_type="figure"),
        ],
    )
    relation_audit = SemanticRelationAuditRecord.model_validate(
        relation_audits[0].model_dump()
    )
    ledger = build_preservation_ledger(
        evidence,
        bookir,
        relation_audits=[relation_audit],
    )
    caption_entry = next(entry for entry in ledger if entry.source_block_id == "caption")
    assert caption_entry.disposition == "moved_into_relation"
    assert caption_entry.final_block_ids == ["figure"]
