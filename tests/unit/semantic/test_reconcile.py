"""Unit tests for decision reconciliation across chunk overlap (M8 Section 7, Appendix I6)."""

from book2epub.semantic.decisions import SemanticDecision, SemanticDecisionBatch
from book2epub.semantic.reconcile import (
    reconcile_semantic_batches,
    reconcile_structure_batches,
)
from book2epub.semantic.structure import StructureDecision, StructureDecisionBatch


def test_reconcile_semantic_agreement() -> None:
    batch1 = SemanticDecisionBatch(
        chunk_id="chk-1",
        decisions=[
            SemanticDecision(
                block_id="b1",
                target="terminal_output",
                confidence=0.90,
                evidence_codes=["SHELL_PROMPT_PATTERN"],
            )
        ],
    )
    batch2 = SemanticDecisionBatch(
        chunk_id="chk-2",
        decisions=[
            SemanticDecision(
                block_id="b1",
                target="terminal_output",
                confidence=0.94,
                evidence_codes=["PRECEDING_TEXT_REFERENCE"],
            )
        ],
    )

    reconciled, conflicts = reconcile_semantic_batches([batch1, batch2], overlap_block_ids={"b1"})
    assert len(conflicts) == 0
    assert "b1" in reconciled
    rec = reconciled["b1"]
    assert rec.target == "terminal_output"
    assert rec.confidence == 0.92  # Arithmetic mean
    assert set(rec.evidence_codes) == {"SHELL_PROMPT_PATTERN", "PRECEDING_TEXT_REFERENCE"}
    assert rec.is_conflict is False
    assert rec.single_vote is False


def test_reconcile_semantic_single_vote_in_overlap() -> None:
    # b2 is in overlap, but only chunk 1 gave a decision
    batch1 = SemanticDecisionBatch(
        chunk_id="chk-1",
        decisions=[
            SemanticDecision(
                block_id="b2",
                target="shell_command",
                confidence=0.88,
                evidence_codes=["SHELL_PROMPT_PATTERN"],
            )
        ],
    )
    batch2 = SemanticDecisionBatch(
        chunk_id="chk-2",
        decisions=[],
    )

    reconciled, conflicts = reconcile_semantic_batches([batch1, batch2], overlap_block_ids={"b2"})
    assert len(conflicts) == 0
    rec = reconciled["b2"]
    assert rec.single_vote is True
    assert rec.confidence == 0.88


def test_reconcile_semantic_conflict_preserves_original() -> None:
    # Chunk 1 says terminal_output, Chunk 2 says table with higher confidence
    batch1 = SemanticDecisionBatch(
        chunk_id="chk-1",
        decisions=[
            SemanticDecision(
                block_id="b3",
                target="terminal_output",
                confidence=0.85,
                evidence_codes=["SHELL_PROMPT_PATTERN"],
            )
        ],
    )
    batch2 = SemanticDecisionBatch(
        chunk_id="chk-2",
        decisions=[
            SemanticDecision(
                block_id="b3",
                target="table",
                confidence=0.98,  # Higher confidence MUST NOT auto-win!
                evidence_codes=["TABULAR_HEADER_PATTERN"],
            )
        ],
    )

    reconciled, conflicts = reconcile_semantic_batches([batch1, batch2], overlap_block_ids={"b3"})
    assert len(conflicts) == 1
    assert conflicts[0].block_id == "b3"
    rec = reconciled["b3"]
    assert rec.is_conflict is True
    assert rec.target == "keep_original"


def test_reconcile_structure_agreement_and_conflict() -> None:
    batch1 = StructureDecisionBatch(
        chunk_id="chk-1",
        decisions=[
            StructureDecision(
                block_id="h1",
                is_heading=True,
                heading_level=2,
                confidence=0.92,
                evidence_codes=["NUMBERING_PATTERN"],
            ),
            StructureDecision(
                block_id="h2",
                is_heading=True,
                heading_level=2,
                confidence=0.90,
                evidence_codes=["NUMBERING_PATTERN"],
            ),
        ],
    )
    batch2 = StructureDecisionBatch(
        chunk_id="chk-2",
        decisions=[
            StructureDecision(
                block_id="h1",
                is_heading=True,
                heading_level=2,
                confidence=0.96,
                evidence_codes=["BOOK_HIERARCHY_CONSISTENCY"],
            ),
            StructureDecision(
                block_id="h2",
                is_heading=True,
                heading_level=3,  # Level conflict!
                confidence=0.88,
                evidence_codes=["NUMBERING_PATTERN"],
            ),
        ],
    )

    reconciled, conflicts = reconcile_structure_batches(
        [batch1, batch2], overlap_block_ids={"h1", "h2"}
    )
    assert reconciled["h1"].is_conflict is False
    assert reconciled["h1"].heading_level == 2
    assert reconciled["h1"].confidence == 0.94

    assert len(conflicts) == 1
    assert reconciled["h2"].is_conflict is True
