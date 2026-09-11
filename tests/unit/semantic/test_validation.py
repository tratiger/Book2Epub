"""Unit tests for provider response scope validation (M8 hardening).

Tests H: out-of-scope block_id rejection
Tests I: wrong chunk_id detection (exact match contract)
Tests K: duplicate decision in same batch detection & filtering
Tests L: paragraph_continuation_of scope validation & sanitization
Tests M: related_block_ids scope validation & sanitization
"""

import pytest

from book2epub.semantic.book_state import (
    BookStateObservationBatch,
    NumberingConventionExample,
    NumberingConventionObservation,
)
from book2epub.semantic.chunking import SemanticChunkInput
from book2epub.semantic.decisions import (
    SemanticBlockDecision,
    SemanticDecision,
    SemanticDecisionBatch,
    SemanticRelationDecision,
)
from book2epub.semantic.models import DraftBlock
from book2epub.semantic.structure import StructureDecision, StructureDecisionBatch
from book2epub.semantic.validation import (
    ScopeValidationError,
    filter_out_of_scope_semantic_decisions,
    filter_out_of_scope_structure_decisions,
    validate_book_state_observation_scope,
    validate_semantic_batch_scope,
    validate_structure_batch_scope,
)


def _make_draft_block(block_id: str, kind: str = "paragraph") -> DraftBlock:
    return DraftBlock(
        block_id=block_id,
        current_kind=kind,
        source_type="text",
        text_preview="Sample text",
        content_sha256="abc123",
    )


def _make_chunk(chunk_id: str, block_ids: list[str]) -> SemanticChunkInput:
    return SemanticChunkInput(
        chunk_id=chunk_id,
        block_ids=block_ids,
        blocks=[_make_draft_block(bid) for bid in block_ids],
        overlap_block_ids=[],
    )


def test_numbering_observation_is_scoped_and_does_not_drop_decisions() -> None:
    chunk = SemanticChunkInput(
        chunk_id="sem-numbering",
        block_ids=["fig-1"],
        blocks=[
            DraftBlock(
                block_id="fig-1",
                current_kind="figure",
                caption_text="図1.3 構成",
                text_preview="figure",
            )
        ],
    )
    batch = SemanticDecisionBatch(
        chunk_id=chunk.chunk_id,
        decisions=[
            SemanticDecision(
                block_id="fig-1",
                target="figure",
                confidence=0.9,
                evidence_codes=[],
            )
        ],
        observations=[
            BookStateObservationBatch(
                chunk_id=chunk.chunk_id,
                numbering_conventions=[
                    NumberingConventionObservation(
                        kind="figure",
                        family="chapter-dot",
                        examples=[
                            NumberingConventionExample(block_id="fig-1", label="図1.3")
                        ],
                        confidence=0.9,
                    )
                ],
            )
        ],
    )

    assert validate_book_state_observation_scope(batch.observations[0], chunk) == []
    filtered = filter_out_of_scope_semantic_decisions(batch, chunk)
    assert len(filtered.decisions) == 1
    assert len(filtered.observations) == 1


def test_numbering_observation_rejects_bad_block_and_hallucinated_label() -> None:
    chunk = SemanticChunkInput(
        chunk_id="sem-numbering-bad",
        block_ids=["fig-1"],
        blocks=[
            DraftBlock(
                block_id="fig-1",
                current_kind="figure",
                caption_text="図1.3 構成",
            )
        ],
    )
    observation = BookStateObservationBatch(
        chunk_id=chunk.chunk_id,
        numbering_conventions=[
            NumberingConventionObservation(
                kind="figure",
                family="chapter-dot",
                        examples=[NumberingConventionExample(block_id="ghost", label="図9.9")],
                        example_labels=["図8.8"],
                        confidence=0.9,
            )
        ],
    )

    violations = validate_book_state_observation_scope(observation, chunk)
    assert any("ghost" in violation for violation in violations)
    assert any("図8.8" in violation for violation in violations)


def test_numbering_family_must_match_source_label() -> None:
    chunk = SemanticChunkInput(
        chunk_id="sem-numbering-family",
        block_ids=["fig-1"],
        blocks=[
            DraftBlock(
                block_id="fig-1",
                current_kind="figure",
                caption_text="図1.3 構成",
            )
        ],
    )
    observation = BookStateObservationBatch(
        chunk_id=chunk.chunk_id,
        numbering_conventions=[
            NumberingConventionObservation(
                kind="figure",
                family="global",
                examples=[NumberingConventionExample(block_id="fig-1", label="図1.3")],
                confidence=0.9,
            )
        ],
    )

    assert any(
        "does not match source label" in violation
        for violation in validate_book_state_observation_scope(observation, chunk)
    )


def test_example_numbering_uses_plain_text_fallback_for_label_grounding() -> None:
    chunk = SemanticChunkInput(
        chunk_id="sem-example-label",
        block_ids=["example-1"],
        blocks=[
            DraftBlock(
                block_id="example-1",
                current_kind="example",
                plain_text="例4 サンプル",
            )
        ],
    )
    observation = BookStateObservationBatch(
        chunk_id=chunk.chunk_id,
        numbering_conventions=[
            NumberingConventionObservation(
                kind="example",
                family="global",
                examples=[NumberingConventionExample(block_id="example-1", label="例4")],
                confidence=0.9,
            )
        ],
    )

    assert validate_book_state_observation_scope(observation, chunk) == []


# ---------------------------------------------------------------------------
# Test H: Out-of-scope block_id filtering
# ---------------------------------------------------------------------------


def test_structure_batch_filters_out_of_scope_block_ids() -> None:
    """Test H: StructureDecisionBatch decisions with block_ids not in the chunk
    must be filtered out, not silently applied."""
    chunk = _make_chunk("sem-0001-aabbcc", ["blk-001", "blk-002"])

    batch = StructureDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0001-aabbcc",  # Exact match
        decisions=[
            StructureDecision(
                block_id="blk-001",
                is_heading=True,
                heading_level=1,
                confidence=0.95,
                evidence_codes=[],
                rationale="",
            ),
            StructureDecision(
                block_id="blk-003",  # Out of scope!
                is_heading=False,
                heading_level=None,
                confidence=0.90,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    violations = validate_structure_batch_scope(batch, chunk)
    assert len(violations) == 1
    assert "blk-003" in violations[0]

    filtered = filter_out_of_scope_structure_decisions(batch, chunk)
    assert len(filtered.decisions) == 1
    assert filtered.decisions[0].block_id == "blk-001"


def test_semantic_batch_filters_out_of_scope_block_ids() -> None:
    """Test H: SemanticDecisionBatch decisions with block_ids not in the chunk
    must be filtered out."""
    chunk = _make_chunk("sem-0002-xxyyzz", ["blk-010", "blk-011"])

    batch = SemanticDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0002-xxyyzz",  # Exact match
        decisions=[
            SemanticDecision(
                block_id="blk-010",
                target="terminal_output",
                confidence=0.92,
                evidence_codes=[],
                rationale="",
            ),
            SemanticDecision(
                block_id="blk-999",  # Out of scope
                target="callout_note",
                confidence=0.88,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    violations = validate_semantic_batch_scope(batch, chunk)
    assert len(violations) == 1
    assert "blk-999" in violations[0]

    filtered = filter_out_of_scope_semantic_decisions(batch, chunk)
    assert len(filtered.decisions) == 1
    assert filtered.decisions[0].block_id == "blk-010"


def test_overlap_block_ids_are_in_scope() -> None:
    """Blocks in chunk.overlap_block_ids are valid targets for decisions."""
    chunk = SemanticChunkInput(
        chunk_id="sem-0003-overlap",
        block_ids=["blk-020", "blk-021"],
        blocks=[_make_draft_block("blk-020"), _make_draft_block("blk-021")],
        overlap_block_ids=["blk-019"],  # Overlap from prior chunk
    )

    batch = SemanticDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0003-overlap",
        decisions=[
            SemanticDecision(
                block_id="blk-019",  # Overlap block — valid
                target="keep",
                confidence=0.99,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    violations = validate_semantic_batch_scope(batch, chunk)
    assert violations == [], "Overlap block_ids must be accepted as in-scope"


# ---------------------------------------------------------------------------
# Test I: Exact chunk_id detection
# ---------------------------------------------------------------------------


def test_structure_batch_wrong_chunk_id_raises() -> None:
    """Test I: StructureDecisionBatch chunk_id must match chunk.chunk_id exactly."""
    chunk = _make_chunk("sem-0004-real", ["blk-030"])

    batch = StructureDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-9999-wrong",  # Wrong chunk_id
        decisions=[
            StructureDecision(
                block_id="blk-030",
                is_heading=True,
                heading_level=2,
                confidence=0.90,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    with pytest.raises(ScopeValidationError, match="chunk_id"):
        validate_structure_batch_scope(batch, chunk)


def test_structure_batch_request_id_as_chunk_id_raises() -> None:
    """Test I (contract enforcement): request_id (e.g. sem-0004-real-pass-a)
    is NOT acceptable as chunk_id; chunk_id must be the document chunk ID."""
    chunk = _make_chunk("sem-0004-real", ["blk-030"])

    batch = StructureDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0004-real-pass-a",  # request_id, not chunk_id!
        decisions=[
            StructureDecision(
                block_id="blk-030",
                is_heading=True,
                heading_level=2,
                confidence=0.90,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    with pytest.raises(ScopeValidationError, match="chunk_id"):
        validate_structure_batch_scope(batch, chunk)


def test_semantic_batch_wrong_chunk_id_raises() -> None:
    """Test I: SemanticDecisionBatch chunk_id must match chunk.chunk_id exactly."""
    chunk = _make_chunk("sem-0005-real", ["blk-040"])

    batch = SemanticDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0006-other-chunk",
        decisions=[
            SemanticDecision(
                block_id="blk-040",
                target="paragraph",
                confidence=0.88,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    with pytest.raises(ScopeValidationError, match="chunk_id"):
        validate_semantic_batch_scope(batch, chunk)


def test_batch_chunk_id_exact_match_succeeds() -> None:
    """Exact match of batch.chunk_id == chunk.chunk_id succeeds."""
    chunk = _make_chunk("sem-0007-chunk", ["blk-060"])

    batch = SemanticDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0007-chunk",
        decisions=[
            SemanticDecision(
                block_id="blk-060",
                target="keep",
                confidence=0.99,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    violations = validate_semantic_batch_scope(batch, chunk)
    assert violations == []


# ---------------------------------------------------------------------------
# Test K: Duplicate block_id within same batch
# ---------------------------------------------------------------------------


def test_duplicate_decision_in_structure_batch_detected_and_filtered() -> None:
    """Test K: If a provider returns multiple decisions for the same block_id
    within a single batch, it must be detected and filtered out as a conflict."""
    chunk = _make_chunk("sem-0008-dup", ["blk-070", "blk-071"])

    batch = StructureDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0008-dup",
        decisions=[
            StructureDecision(
                block_id="blk-070",
                is_heading=True,
                heading_level=1,
                confidence=0.90,
                evidence_codes=[],
                rationale="First vote",
            ),
            StructureDecision(
                block_id="blk-070",  # Duplicate!
                is_heading=False,
                heading_level=None,
                confidence=0.85,
                evidence_codes=[],
                rationale="Second conflicting vote",
            ),
            StructureDecision(
                block_id="blk-071",  # Legitimate single decision
                is_heading=True,
                heading_level=2,
                confidence=0.95,
                evidence_codes=[],
                rationale="Clean vote",
            ),
        ],
    )

    violations = validate_structure_batch_scope(batch, chunk)
    assert any("Duplicate" in v for v in violations)

    filtered = filter_out_of_scope_structure_decisions(batch, chunk)
    # The duplicate block_id blk-070 must be filtered out; blk-071 retained
    assert len(filtered.decisions) == 1
    assert filtered.decisions[0].block_id == "blk-071"


def test_duplicate_decision_in_semantic_batch_detected_and_filtered() -> None:
    """Test K: Duplicate decisions for the same block_id in SemanticDecisionBatch
    must be detected and filtered."""
    chunk = _make_chunk("sem-0009-dup", ["blk-080"])

    batch = SemanticDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0009-dup",
        decisions=[
            SemanticDecision(
                block_id="blk-080",
                target="terminal_output",
                confidence=0.90,
                evidence_codes=[],
                rationale="First vote",
            ),
            SemanticDecision(
                block_id="blk-080",  # Duplicate!
                target="shell_command",
                confidence=0.85,
                evidence_codes=[],
                rationale="Second vote",
            ),
        ],
    )

    violations = validate_semantic_batch_scope(batch, chunk)
    assert any("Duplicate" in v for v in violations)

    filtered = filter_out_of_scope_semantic_decisions(batch, chunk)
    assert len(filtered.decisions) == 0


# ---------------------------------------------------------------------------
# Test L: paragraph_continuation_of scope validation & sanitization
# ---------------------------------------------------------------------------


def test_paragraph_continuation_of_out_of_scope_detected_and_sanitized() -> None:
    """Test L: StructureDecision with out-of-scope paragraph_continuation_of
    must be flagged and sanitized (continuation target removed)."""
    chunk = _make_chunk("sem-0010-cont", ["blk-090", "blk-091"])

    batch = StructureDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0010-cont",
        decisions=[
            StructureDecision(
                block_id="blk-091",
                is_heading=False,
                heading_level=None,
                paragraph_continuation_of="blk-foreign",  # Not in chunk!
                confidence=0.92,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    violations = validate_structure_batch_scope(batch, chunk)
    assert len(violations) == 1
    assert "paragraph_continuation_of='blk-foreign'" in violations[0]

    filtered = filter_out_of_scope_structure_decisions(batch, chunk)
    assert len(filtered.decisions) == 1
    assert filtered.decisions[0].paragraph_continuation_of is None


# ---------------------------------------------------------------------------
# Test M: related_block_ids scope validation & sanitization
# ---------------------------------------------------------------------------


def test_related_block_ids_out_of_scope_detected_and_sanitized() -> None:
    """Test M: SemanticDecision with out-of-scope related_block_ids
    must be flagged and the foreign IDs stripped."""
    chunk = _make_chunk("sem-0011-rel", ["blk-100", "blk-101"])

    batch = SemanticDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0011-rel",
        decisions=[
            SemanticDecision(
                block_id="blk-100",
                target="callout_note",
                confidence=0.90,
                evidence_codes=[],
                related_block_ids=["blk-101", "blk-ghost"],  # blk-ghost is out of scope
                rationale="",
            ),
        ],
    )

    violations = validate_semantic_batch_scope(batch, chunk)
    assert len(violations) == 1
    assert "related_block_id='blk-ghost'" in violations[0]

    filtered = filter_out_of_scope_semantic_decisions(batch, chunk)
    assert len(filtered.decisions) == 1
    assert filtered.decisions[0].related_block_ids == ["blk-101"]


def test_relation_scope_rejects_unknown_source_and_target() -> None:
    chunk = _make_chunk("sem-relation-scope", ["blk-100"])
    batch = SemanticDecisionBatch(
        chunk_id=chunk.chunk_id,
        relations=[
            SemanticRelationDecision(
                relation_type="caption_of",
                source_block_ids=["ghost"],
                target_block_id="blk-foreign",
                confidence=0.95,
            )
        ],
    )

    violations = validate_semantic_batch_scope(batch, chunk)
    assert any("ghost" in violation for violation in violations)
    assert any("blk-foreign" in violation for violation in violations)
    filtered = filter_out_of_scope_semantic_decisions(batch, chunk)
    assert filtered.relations == []


def test_semantic_cardinality_is_bounded_by_chunk_scope() -> None:
    chunk = _make_chunk("sem-cardinality", ["blk-1", "blk-2"])
    batch = SemanticDecisionBatch(
        chunk_id=chunk.chunk_id,
        decisions=[
            SemanticBlockDecision(
                block_id="blk-1",
                operation="keep",
                confidence=0.9,
            )
            for _ in range(3)
        ],
    )

    violations = validate_semantic_batch_scope(batch, chunk)

    assert any("exceeds chunk scope cardinality" in violation for violation in violations)
