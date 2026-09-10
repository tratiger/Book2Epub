"""Provider response scope validation for semantic and structure batches (M8 hardening).

Validates that every decision returned by a provider:
- belongs to the chunk that was sent in the request (chunk_id match)
- references a block_id that was included in that chunk

These checks prevent a provider from injecting or cross-contaminating decisions
across chunks, which would silently corrupt the BookIR.
"""

import logging

from book2epub.semantic.chunking import SemanticChunkInput
from book2epub.semantic.decisions import SemanticDecisionBatch
from book2epub.semantic.structure import StructureDecisionBatch

logger = logging.getLogger(__name__)


class ScopeValidationError(ValueError):
    """Raised when a provider response references out-of-scope blocks or wrong chunk_id."""


def _chunk_block_ids(chunk: SemanticChunkInput) -> frozenset[str]:
    """Return the full set of block_ids that belong to this chunk (primary + overlap)."""
    ids: set[str] = set(chunk.block_ids)
    ids.update(chunk.overlap_block_ids)
    return frozenset(ids)


def validate_structure_batch_scope(
    batch: StructureDecisionBatch,
    chunk: SemanticChunkInput,
    request_id: str,
) -> list[str]:
    """Validate a StructureDecisionBatch returned by a provider against its originating chunk.

    Returns a list of human-readable violation strings (empty == clean).
    Raises ScopeValidationError for critical violations (wrong chunk_id where
    neither the batch chunk_id nor the expected chunk_id matches).
    """
    violations: list[str] = []

    # 1. chunk_id must match: provider may echo either chunk_id or request_id
    expected_chunk_id = chunk.chunk_id
    if batch.chunk_id not in (request_id, expected_chunk_id):
        msg = (
            f"StructureDecisionBatch chunk_id={batch.chunk_id!r} does not match "
            f"request_id={request_id!r} or expected chunk={expected_chunk_id!r}"
        )
        logger.error(msg)
        raise ScopeValidationError(msg)

    # 2. Every block_id in decisions must belong to this chunk
    valid_ids = _chunk_block_ids(chunk)
    for dec in batch.decisions:
        if dec.block_id not in valid_ids:
            violation = (
                f"StructureDecision block_id={dec.block_id!r} not in chunk "
                f"{expected_chunk_id!r} (valid ids count: {len(valid_ids)})"
            )
            logger.warning(violation)
            violations.append(violation)

    return violations


def validate_semantic_batch_scope(
    batch: SemanticDecisionBatch,
    chunk: SemanticChunkInput,
    request_id: str,
) -> list[str]:
    """Validate a SemanticDecisionBatch returned by a provider against its originating chunk.

    Returns a list of human-readable violation strings (empty == clean).
    Raises ScopeValidationError for critical violations (wrong chunk_id).
    """
    violations: list[str] = []

    # 1. chunk_id must match: provider may echo either chunk_id or request_id
    expected_chunk_id = chunk.chunk_id
    if batch.chunk_id not in (request_id, expected_chunk_id):
        msg = (
            f"SemanticDecisionBatch chunk_id={batch.chunk_id!r} does not match "
            f"request_id={request_id!r} or expected chunk={expected_chunk_id!r}"
        )
        logger.error(msg)
        raise ScopeValidationError(msg)

    # 2. Every block_id in decisions must belong to this chunk
    valid_ids = _chunk_block_ids(chunk)
    for dec in batch.decisions:
        if dec.block_id not in valid_ids:
            violation = (
                f"SemanticDecision block_id={dec.block_id!r} not in chunk "
                f"{expected_chunk_id!r} (valid ids count: {len(valid_ids)})"
            )
            logger.warning(violation)
            violations.append(violation)

    return violations


def filter_out_of_scope_structure_decisions(
    batch: StructureDecisionBatch,
    chunk: SemanticChunkInput,
) -> StructureDecisionBatch:
    """Return a new StructureDecisionBatch with out-of-scope decisions removed."""
    valid_ids = _chunk_block_ids(chunk)
    good_decisions = [d for d in batch.decisions if d.block_id in valid_ids]
    if len(good_decisions) < len(batch.decisions):
        removed = [d.block_id for d in batch.decisions if d.block_id not in valid_ids]
        logger.warning(
            "Filtered %d out-of-scope structure decisions from chunk %s: %s",
            len(removed),
            chunk.chunk_id,
            removed,
        )
    return StructureDecisionBatch(
        schema_version=batch.schema_version,
        chunk_id=batch.chunk_id,
        decisions=good_decisions,
    )


def filter_out_of_scope_semantic_decisions(
    batch: SemanticDecisionBatch,
    chunk: SemanticChunkInput,
) -> SemanticDecisionBatch:
    """Return a new SemanticDecisionBatch with out-of-scope decisions removed."""
    valid_ids = _chunk_block_ids(chunk)
    good_decisions = [d for d in batch.decisions if d.block_id in valid_ids]
    if len(good_decisions) < len(batch.decisions):
        removed = [d.block_id for d in batch.decisions if d.block_id not in valid_ids]
        logger.warning(
            "Filtered %d out-of-scope semantic decisions from chunk %s: %s",
            len(removed),
            chunk.chunk_id,
            removed,
        )
    return SemanticDecisionBatch(
        schema_version=batch.schema_version,
        chunk_id=batch.chunk_id,
        decisions=good_decisions,
    )
