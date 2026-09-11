"""Provider response scope validation for semantic and structure batches (M8 hardening).

Validates that every decision returned by a provider:
- belongs to the chunk that was sent in the request (exact chunk_id match)
- references a block_id that belongs to that chunk (primary + overlap)
- contains no duplicate block_ids within the same batch
- references paragraph_continuation_of within the chunk scope
- references related_block_ids within the chunk scope

These checks prevent a provider from injecting or cross-contaminating decisions
across chunks, which would silently corrupt the BookIR.
"""

import logging
from collections import Counter

from book2epub.semantic.book_state import (
    BookStateObservationBatch,
    detect_numbering_family,
)
from book2epub.semantic.chunking import SemanticChunkInput
from book2epub.semantic.decisions import SemanticDecisionBatch
from book2epub.semantic.relations import relation_key
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
    request_id: str | None = None,
) -> list[str]:
    """Validate a StructureDecisionBatch returned by a provider against its originating chunk.

    Contract:
    - batch.chunk_id must EXACTLY match chunk.chunk_id (request_id is for API audit only).
    - every decision.block_id must be in chunk scope (primary + overlap).
    - no duplicate block_ids in the same batch.
    - decision.paragraph_continuation_of (if set) must be in chunk scope.

    Returns a list of human-readable violation strings (empty == clean).
    Raises ScopeValidationError for critical violations (wrong chunk_id).
    """
    violations: list[str] = []

    # 1. chunk_id must match chunk.chunk_id EXACTLY
    expected_chunk_id = chunk.chunk_id
    if batch.chunk_id != expected_chunk_id:
        msg = (
            f"StructureDecisionBatch chunk_id={batch.chunk_id!r} does not match "
            f"expected chunk_id={expected_chunk_id!r}"
        )
        logger.error(msg)
        raise ScopeValidationError(msg)

    valid_ids = _chunk_block_ids(chunk)

    # 2. Check for duplicate block_ids in the same batch
    counts = Counter(d.block_id for d in batch.decisions)
    for bid, count in counts.items():
        if count > 1:
            violation = (
                f"Duplicate decision for block_id {bid!r} ({count} occurrences) "
                f"in chunk {expected_chunk_id!r}"
            )
            logger.warning(violation)
            violations.append(violation)

    # 3. Every block_id must belong to this chunk
    for dec in batch.decisions:
        if dec.block_id not in valid_ids:
            violation = (
                f"StructureDecision block_id={dec.block_id!r} not in chunk "
                f"{expected_chunk_id!r} (valid ids count: {len(valid_ids)})"
            )
            logger.warning(violation)
            violations.append(violation)

        # 4. paragraph_continuation_of must be in chunk scope
        if dec.paragraph_continuation_of and dec.paragraph_continuation_of not in valid_ids:
            violation = (
                f"StructureDecision block_id={dec.block_id!r} references "
                f"out-of-scope paragraph_continuation_of={dec.paragraph_continuation_of!r} "
                f"in chunk {expected_chunk_id!r}"
            )
            logger.warning(violation)
            violations.append(violation)

    return violations


def validate_semantic_batch_scope(
    batch: SemanticDecisionBatch,
    chunk: SemanticChunkInput,
    request_id: str | None = None,
) -> list[str]:
    """Validate a SemanticDecisionBatch returned by a provider against its originating chunk.

    Contract:
    - batch.chunk_id must EXACTLY match chunk.chunk_id.
    - every decision.block_id must be in chunk scope (primary + overlap).
    - no duplicate block_ids in the same batch.
    - related_block_ids must all be in chunk scope.

    Returns a list of human-readable violation strings (empty == clean).
    Raises ScopeValidationError for critical violations (wrong chunk_id).
    """
    violations: list[str] = []

    # 1. chunk_id must match chunk.chunk_id EXACTLY
    expected_chunk_id = chunk.chunk_id
    if batch.chunk_id != expected_chunk_id:
        msg = (
            f"SemanticDecisionBatch chunk_id={batch.chunk_id!r} does not match "
            f"expected chunk_id={expected_chunk_id!r}"
        )
        logger.error(msg)
        raise ScopeValidationError(msg)

    valid_ids = _chunk_block_ids(chunk)

    # 2. Check for duplicate block_ids in the same batch
    counts = Counter(d.block_id for d in batch.decisions)
    for bid, count in counts.items():
        if count > 1:
            violation = (
                f"Duplicate decision for block_id {bid!r} ({count} occurrences) "
                f"in chunk {expected_chunk_id!r}"
            )
            logger.warning(violation)
            violations.append(violation)

    # 3. Every block_id and legacy related_block_ids must belong to this chunk
    for dec in batch.decisions:
        if dec.block_id not in valid_ids:
            violation = (
                f"SemanticDecision block_id={dec.block_id!r} not in chunk "
                f"{expected_chunk_id!r} (valid ids count: {len(valid_ids)})"
            )
            logger.warning(violation)
            violations.append(violation)

        # 4. related_block_ids must all be in chunk scope
        for rel_id in dec.related_block_ids:
            if rel_id not in valid_ids:
                violation = (
                    f"SemanticDecision block_id={dec.block_id!r} references "
                    f"out-of-scope related_block_id={rel_id!r} in chunk {expected_chunk_id!r}"
                )
                logger.warning(violation)
                violations.append(violation)

    relation_counts = Counter(relation_key(rel) for rel in batch.relations)
    for rel in batch.relations:
        relation_violations = validate_relation_scope(rel, chunk)
        if relation_counts[relation_key(rel)] > 1:
            relation_violations.append(
                f"Duplicate semantic relation {relation_key(rel)!r} in chunk {expected_chunk_id!r}"
            )
        violations.extend(relation_violations)

    return violations


def validate_relation_scope(rel: object, chunk: SemanticChunkInput) -> list[str]:
    """Validate relation source/target IDs against one exact chunk scope."""
    valid_ids = _chunk_block_ids(chunk)
    violations: list[str] = []
    source_ids = list(getattr(rel, "source_block_ids", []))
    target_id = getattr(rel, "target_block_id", None)
    if not source_ids:
        violations.append("Semantic relation has no source_block_ids")
    if len(source_ids) != len(set(source_ids)):
        violations.append("Semantic relation contains duplicate source_block_ids")
    for source_id in source_ids:
        if source_id not in valid_ids:
            violations.append(
                f"Semantic relation source_block_id={source_id!r} is not in chunk "
                f"{chunk.chunk_id!r}"
            )
    if target_id is not None and target_id not in valid_ids:
        violations.append(
            f"Semantic relation target_block_id={target_id!r} is not in chunk "
            f"{chunk.chunk_id!r}"
        )
    return violations


def filter_out_of_scope_structure_decisions(
    batch: StructureDecisionBatch,
    chunk: SemanticChunkInput,
) -> StructureDecisionBatch:
    """Return a new StructureDecisionBatch with filtered decisions."""
    valid_ids = _chunk_block_ids(chunk)
    counts = Counter(d.block_id for d in batch.decisions)

    good_decisions = []
    for d in batch.decisions:
        # Filter out if block_id not in valid chunk IDs
        if d.block_id not in valid_ids:
            logger.warning(
                "Filtered out-of-scope structure decision for block %s in chunk %s",
                d.block_id,
                chunk.chunk_id,
            )
            continue
        # Filter out if duplicate within same batch (treat duplicate as invalid/conflict)
        if counts[d.block_id] > 1:
            logger.warning(
                "Filtered conflicting duplicate structure decision for block %s in chunk %s",
                d.block_id,
                chunk.chunk_id,
            )
            continue

        # Sanitize out-of-scope paragraph_continuation_of
        if d.paragraph_continuation_of and d.paragraph_continuation_of not in valid_ids:
            logger.warning(
                "Sanitizing out-of-scope continuation target %s on block %s in chunk %s",
                d.paragraph_continuation_of,
                d.block_id,
                chunk.chunk_id,
            )
            d = d.model_copy(update={"paragraph_continuation_of": None})

        good_decisions.append(d)

    return StructureDecisionBatch(
        schema_version=batch.schema_version,
        chunk_id=batch.chunk_id,
        decisions=good_decisions,
    )


def filter_out_of_scope_semantic_decisions(
    batch: SemanticDecisionBatch,
    chunk: SemanticChunkInput,
) -> SemanticDecisionBatch:
    """Return a new SemanticDecisionBatch with filtered decisions."""
    valid_ids = _chunk_block_ids(chunk)
    counts = Counter(d.block_id for d in batch.decisions)

    good_decisions = []
    for d in batch.decisions:
        # Filter out if block_id not in valid chunk IDs
        if d.block_id not in valid_ids:
            logger.warning(
                "Filtered out-of-scope semantic decision for block %s in chunk %s",
                d.block_id,
                chunk.chunk_id,
            )
            continue
        # Filter out if duplicate within same batch
        if counts[d.block_id] > 1:
            logger.warning(
                "Filtered conflicting duplicate semantic decision for block %s in chunk %s",
                d.block_id,
                chunk.chunk_id,
            )
            continue

        # Sanitize related_block_ids: drop any out-of-scope IDs
        if d.related_block_ids:
            sanitized_rels = [r for r in d.related_block_ids if r in valid_ids]
            if len(sanitized_rels) != len(d.related_block_ids):
                logger.warning(
                    "Sanitizing out-of-scope related_block_ids on block %s in chunk %s",
                    d.block_id,
                    chunk.chunk_id,
                )
                d = d.model_copy()
                d._legacy_related_block_ids = sanitized_rels

        good_decisions.append(d)

    good_relations = []
    relation_counts = Counter(relation_key(rel) for rel in batch.relations)
    for rel in batch.relations:
        if validate_relation_scope(rel, chunk) or relation_counts[relation_key(rel)] > 1:
            logger.warning(
                "Filtered invalid or duplicate semantic relation in chunk %s: %s",
                chunk.chunk_id,
                relation_key(rel),
            )
            continue
        good_relations.append(rel)

    return SemanticDecisionBatch(
        schema_version=batch.schema_version,
        chunk_id=batch.chunk_id,
        decisions=good_decisions,
        relations=good_relations,
        observations=batch.observations,
    )


def validate_book_state_observation_scope(
    observation: BookStateObservationBatch,
    chunk: SemanticChunkInput,
) -> list[str]:
    """Validate an inline BookState observation against its exact chunk scope."""
    if observation.chunk_id != chunk.chunk_id:
        raise ScopeValidationError(
            f"BookStateObservationBatch chunk_id={observation.chunk_id!r} does not match "
            f"expected chunk_id={chunk.chunk_id!r}"
        )

    valid_ids = _chunk_block_ids(chunk)
    violations: list[str] = []
    for field_name in (
        "heading_patterns",
        "preformatted_conventions",
        "callout_conventions",
    ):
        for item in getattr(observation, field_name):
            for block_id in item.example_block_ids:
                if block_id not in valid_ids:
                    violations.append(
                        f"BookState observation {field_name} example_block_id={block_id!r} "
                        f"is not in chunk {chunk.chunk_id!r}"
                    )

    # Numbering observations use source labels rather than example_block_ids.
    # Validate both the block scope and the verbatim caption/label so a model
    # cannot seed BookState with a plausible but hallucinated label.  The
    # legacy example_labels field is accepted only when it matches a scoped
    # source block; new responses should use the explicit examples field.
    draft_by_id = {block.block_id: block for block in chunk.blocks}

    def source_text_for_kind(block: object, kind: str) -> str:
        current_kind = getattr(block, "current_kind", "")
        kind_matches = {
            "figure": current_kind == "figure",
            "table": current_kind == "table",
            "listing": current_kind in {"code", "preformatted"},
            "example": current_kind == "example",
            "exercise": current_kind == "exercise",
        }
        if not kind_matches.get(kind, False):
            return ""
        caption = str(
            getattr(block, "caption_text", None)
            or getattr(block, "caption_preview", None)
            or ""
        )
        if caption or kind not in {"example", "exercise"}:
            return caption
        return str(
            getattr(block, "plain_text", None)
            or getattr(block, "text_preview", None)
            or ""
        )

    for item in observation.numbering_conventions:
        for example in item.examples:
            if example.block_id not in valid_ids:
                violations.append(
                    f"BookState observation numbering_conventions example block_id="
                    f"{example.block_id!r} is not in chunk {chunk.chunk_id!r}"
                )
                continue
            source_text = source_text_for_kind(draft_by_id.get(example.block_id), item.kind)
            if not source_text or example.label not in source_text:
                violations.append(
                    f"BookState observation numbering_conventions label={example.label!r} "
                    f"is not verbatim in source block {example.block_id!r}"
                )
            elif detect_numbering_family(example.label)[1] != item.family:
                violations.append(
                    f"BookState observation numbering_conventions family={item.family!r} "
                    f"does not match source label {example.label!r}"
                )

        for label in item.example_labels:
            if not any(
                label in source_text_for_kind(block, item.kind)
                for block in chunk.blocks
            ):
                violations.append(
                    f"BookState observation numbering_conventions label={label!r} "
                    f"is not verbatim in a scoped {item.kind} source block"
                )
            elif detect_numbering_family(label)[1] != item.family:
                violations.append(
                    f"BookState observation numbering_conventions family={item.family!r} "
                    f"does not match source label {label!r}"
                )

    for item in observation.domain_terms:
        if item.source_block_id not in valid_ids:
            violations.append(
                f"BookState observation domain term source_block_id="
                f"{item.source_block_id!r} is not in chunk {chunk.chunk_id!r}"
            )
    return violations
