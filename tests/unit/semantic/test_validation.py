"""Unit tests for provider response scope validation (M8 hardening).

Tests H: out-of-scope block_id rejection
Tests I: wrong chunk_id detection
"""

import pytest

from book2epub.semantic.chunking import SemanticChunkInput
from book2epub.semantic.decisions import SemanticDecision, SemanticDecisionBatch
from book2epub.semantic.models import DraftBlock
from book2epub.semantic.structure import StructureDecision, StructureDecisionBatch
from book2epub.semantic.validation import (
    ScopeValidationError,
    filter_out_of_scope_semantic_decisions,
    filter_out_of_scope_structure_decisions,
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


# ---------------------------------------------------------------------------
# Test H: Out-of-scope block_id filtering
# ---------------------------------------------------------------------------


def test_structure_batch_filters_out_of_scope_block_ids() -> None:
    """Test H: StructureDecisionBatch decisions with block_ids not in the chunk
    must be filtered out, not silently applied."""
    chunk = _make_chunk("sem-0001-aabbcc", ["blk-001", "blk-002"])

    # Provider returned a decision for blk-003 which is NOT in this chunk
    batch = StructureDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0001-aabbcc-pass-a",
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

    violations = validate_structure_batch_scope(
        batch, chunk, request_id="sem-0001-aabbcc-pass-a"
    )
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
        chunk_id="sem-0002-xxyyzz-pass-b",
        decisions=[
            SemanticDecision(
                block_id="blk-010",
                target="terminal_output",
                confidence=0.92,
                evidence_codes=[],
                rationale="",
            ),
            SemanticDecision(
                block_id="blk-999",  # Out of scope — different chunk's block
                target="callout_note",
                confidence=0.88,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    violations = validate_semantic_batch_scope(
        batch, chunk, request_id="sem-0002-xxyyzz-pass-b"
    )
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
        chunk_id="sem-0003-overlap-pass-b",
        decisions=[
            SemanticDecision(
                block_id="blk-019",  # Overlap block — should be valid
                target="keep",
                confidence=0.99,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    violations = validate_semantic_batch_scope(
        batch, chunk, request_id="sem-0003-overlap-pass-b"
    )
    assert violations == [], "Overlap block_ids must be accepted as in-scope"


# ---------------------------------------------------------------------------
# Test I: Wrong chunk_id detection
# ---------------------------------------------------------------------------


def test_structure_batch_wrong_chunk_id_raises() -> None:
    """Test I: A StructureDecisionBatch whose chunk_id doesn't match the request
    must raise ScopeValidationError (critical violation)."""
    chunk = _make_chunk("sem-0004-real", ["blk-030"])

    batch = StructureDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-9999-wrong",  # Completely wrong chunk_id
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
        validate_structure_batch_scope(
            batch, chunk, request_id="sem-0004-real-pass-a"
        )


def test_semantic_batch_wrong_chunk_id_raises() -> None:
    """Test I: A SemanticDecisionBatch whose chunk_id doesn't match the request
    must raise ScopeValidationError."""
    chunk = _make_chunk("sem-0005-real", ["blk-040"])

    batch = SemanticDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0006-other-chunk",  # Different chunk entirely
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
        validate_semantic_batch_scope(
            batch, chunk, request_id="sem-0005-real-pass-b"
        )


def test_batch_chunk_id_matches_request_id() -> None:
    """Provider may echo request_id as chunk_id (mock providers do this).
    This must be accepted without error."""
    chunk = _make_chunk("sem-0006-chunk", ["blk-050"])

    # Provider echoes request_id (not chunk_id) — this is valid
    batch = StructureDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0006-chunk-pass-a",  # This IS the request_id
        decisions=[
            StructureDecision(
                block_id="blk-050",
                is_heading=False,
                heading_level=None,
                confidence=0.85,
                evidence_codes=[],
                rationale="",
            ),
        ],
    )

    # Should NOT raise; request_id is an acceptable chunk_id value
    violations = validate_structure_batch_scope(
        batch, chunk, request_id="sem-0006-chunk-pass-a"
    )
    assert violations == []


def test_batch_chunk_id_matches_chunk_chunk_id() -> None:
    """Provider may echo chunk.chunk_id directly — also valid."""
    chunk = _make_chunk("sem-0007-chunk", ["blk-060"])

    batch = SemanticDecisionBatch(
        schema_version="1.0",
        chunk_id="sem-0007-chunk",  # Matches chunk.chunk_id directly
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

    violations = validate_semantic_batch_scope(
        batch, chunk, request_id="sem-0007-chunk-pass-b"
    )
    assert violations == []
