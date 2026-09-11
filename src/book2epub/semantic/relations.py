"""Deterministic reconciliation and validation of Pass B relations."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from book2epub.ir.models import (
    Block,
    Chart,
    CodeBlock,
    Figure,
    Footnote,
    Heading,
    Paragraph,
    PreformattedBlock,
    Table,
)
from book2epub.semantic.decisions import RelationType, SemanticRelationDecision

type RelationKey = tuple[RelationType, tuple[str, ...], str | None]


@dataclass
class ReconciledRelation:
    """A deterministic relation vote consolidated across chunk overlap."""

    relation_type: RelationType
    source_block_ids: list[str]
    target_block_id: str | None
    confidence: float
    evidence_codes: list[str] = field(default_factory=list)
    rationales: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    single_vote: bool = False
    is_conflict: bool = False
    conflict_details: str | None = None

    @property
    def key(self) -> RelationKey:
        return (self.relation_type, tuple(self.source_block_ids), self.target_block_id)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe cache representation."""
        return {
            "relation_type": self.relation_type,
            "source_block_ids": list(self.source_block_ids),
            "target_block_id": self.target_block_id,
            "confidence": self.confidence,
            "evidence_codes": list(self.evidence_codes),
            "rationales": list(self.rationales),
            "chunk_ids": list(self.chunk_ids),
            "single_vote": self.single_vote,
            "is_conflict": self.is_conflict,
            "conflict_details": self.conflict_details,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> ReconciledRelation:
        return cls(
            relation_type=value["relation_type"],  # type: ignore[arg-type]
            source_block_ids=list(cast(list[str], value.get("source_block_ids", []))),
            target_block_id=value.get("target_block_id"),  # type: ignore[arg-type]
            confidence=float(cast(Any, value.get("confidence", 0.0))),
            evidence_codes=list(cast(list[str], value.get("evidence_codes", []))),
            rationales=list(cast(list[str], value.get("rationales", []))),
            chunk_ids=list(cast(list[str], value.get("chunk_ids", []))),
            single_vote=bool(value.get("single_vote", False)),
            is_conflict=bool(value.get("is_conflict", False)),
            conflict_details=value.get("conflict_details"),  # type: ignore[arg-type]
        )


@dataclass
class RelationConflict:
    """Conflicting relation identities for one source group."""

    source_block_ids: tuple[str, ...]
    relation_keys: list[RelationKey]
    chunk_ids: list[str]
    reason: str


def relation_key(rel: SemanticRelationDecision | ReconciledRelation) -> RelationKey:
    """Return the stable identity used for overlap reconciliation."""
    return (rel.relation_type, tuple(rel.source_block_ids), rel.target_block_id)


def reconcile_relation_batches(
    batches: Sequence[object],
    overlap_block_ids: set[str] | None = None,
) -> tuple[dict[RelationKey, ReconciledRelation], list[RelationConflict]]:
    """Merge equal relation votes and preserve conflicting votes as unresolved.

    A higher-confidence vote never wins a contradiction. Every conflicting identity
    remains in the returned mapping so the application and audit paths can record it.
    """
    grouped: dict[RelationKey, list[tuple[str, SemanticRelationDecision]]] = {}
    for batch in batches:
        chunk_id = str(getattr(batch, "chunk_id", ""))
        for rel in getattr(batch, "relations", []):
            grouped.setdefault(relation_key(rel), []).append((chunk_id, rel))

    overlap_ids = overlap_block_ids or set()
    reconciled: dict[RelationKey, ReconciledRelation] = {}
    conflicts: list[RelationConflict] = []

    by_source: dict[tuple[str, ...], list[RelationKey]] = {}
    for key in grouped:
        by_source.setdefault(tuple(sorted(key[1])), []).append(key)
    conflicting_keys: set[RelationKey] = set()
    for source_ids, keys in by_source.items():
        if len(keys) > 1:
            conflicting_keys.update(keys)
            chunk_ids = sorted({cid for key in keys for cid, _ in grouped[key]})
            conflicts.append(
                RelationConflict(
                    source_block_ids=source_ids,
                    relation_keys=keys,
                    chunk_ids=chunk_ids,
                    reason="Conflicting relation targets or relation types for source group",
                )
            )

    for key, votes in grouped.items():
        relation_type, source_ids, target_id = key
        chunk_ids = sorted({chunk_id for chunk_id, _ in votes})
        codes = sorted({str(code) for _, vote in votes for code in vote.evidence_codes})
        rationales = [vote.rationale for _, vote in votes if vote.rationale]
        is_single_vote = len(votes) == 1 and bool(set(source_ids) & overlap_ids)
        reconciled[key] = ReconciledRelation(
            relation_type=relation_type,
            source_block_ids=list(source_ids),
            target_block_id=target_id,
            confidence=round(sum(vote.confidence for _, vote in votes) / len(votes), 3),
            evidence_codes=codes,
            rationales=rationales,
            chunk_ids=chunk_ids,
            single_vote=is_single_vote,
            is_conflict=key in conflicting_keys,
            conflict_details=(
                "Conflicting relation identities for the same source group"
                if key in conflicting_keys
                else None
            ),
        )
    return reconciled, conflicts


def _page_indices(block: Block) -> set[int]:
    return {source.page_idx for source in block.sources}


def _within_one_page(source: Block, target: Block) -> bool:
    source_pages = _page_indices(source)
    target_pages = _page_indices(target)
    if not source_pages or not target_pages:
        return False
    return min(abs(a - b) for a in source_pages for b in target_pages) <= 1


def _source_inlines(block: Block) -> list[object] | None:
    if isinstance(block, (Paragraph, Heading)):
        return list(block.inlines)
    if isinstance(block, Footnote):
        return list(block.inlines)
    return None


def _same_inlines(left: Sequence[object], right: Sequence[object]) -> bool:
    return [getattr(item, "model_dump")() for item in left] == [
        getattr(item, "model_dump")() for item in right
    ]


def _caption_target(block: Block) -> bool:
    return isinstance(block, (Figure, Chart, Table, CodeBlock, PreformattedBlock))


def _validate_group_relation(
    rel: SemanticRelationDecision | ReconciledRelation,
    blocks_by_id: dict[str, Block],
    block_order: dict[str, int],
) -> tuple[bool, str]:
    if not rel.source_block_ids:
        return False, "relation requires at least one source block"
    if len(rel.source_block_ids) < 2:
        return False, "group relation requires at least two source blocks"
    indices = [block_order[block_id] for block_id in rel.source_block_ids]
    if indices != sorted(indices):
        return False, "source block IDs are not in source order"
    if any(right != left + 1 for left, right in zip(indices, indices[1:])):
        return False, "source block IDs are not contiguous"
    if any(isinstance(blocks_by_id[block_id], Heading) for block_id in rel.source_block_ids):
        return False, "group relation crosses or includes a Heading boundary"
    if rel.target_block_id is not None and rel.target_block_id not in blocks_by_id:
        return False, f"Target block ID '{rel.target_block_id}' does not exist"
    return True, ""


def validate_relation(
    rel: SemanticRelationDecision | ReconciledRelation,
    blocks_by_id: dict[str, Block],
    block_order: dict[str, int],
) -> tuple[bool, str]:
    """Validate relation scope, source compatibility, and source-page locality."""
    for source_id in rel.source_block_ids:
        if source_id not in blocks_by_id:
            return False, f"Source block ID '{source_id}' does not exist"
    if rel.target_block_id and rel.target_block_id not in blocks_by_id:
        return False, f"Target block ID '{rel.target_block_id}' does not exist"

    if rel.relation_type in {"member_of_callout", "member_of_example"}:
        return _validate_group_relation(rel, blocks_by_id, block_order)

    if len(rel.source_block_ids) != 1 or not rel.target_block_id:
        return False, f"{rel.relation_type} requires exactly one source and one target"

    source = blocks_by_id[rel.source_block_ids[0]]
    target = blocks_by_id[rel.target_block_id]
    if rel.relation_type in {"caption_of", "footnote_of"}:
        if not _caption_target(target):
            return (
                False,
                f"Target block '{target.id}' ({target.kind}) cannot receive "
                f"{rel.relation_type}",
            )
        if _source_inlines(source) is None:
            return False, "relation source is not caption-compatible prose"
        if not _within_one_page(source, target):
            return False, "source and target are more than one page apart"
        if not isinstance(target, (Figure, Chart, Table, CodeBlock, PreformattedBlock)):
            return False, "target does not support caption or footnote inlines"
        existing = target.caption if rel.relation_type == "caption_of" else target.footnotes
        source_inlines = _source_inlines(source) or []
        if existing and not _same_inlines(existing, source_inlines):
            return False, f"target already has a different {rel.relation_type}"
        return True, ""

    if rel.relation_type == "paragraph_continuation":
        if not isinstance(source, Paragraph) or not isinstance(target, Paragraph):
            return False, "paragraph_continuation requires Paragraph source and target"
        if block_order[rel.source_block_ids[0]] + 1 != block_order[rel.target_block_id]:
            return False, "paragraph_continuation blocks are not adjacent in source order"
        if not _within_one_page(source, target) or _page_indices(source) == _page_indices(target):
            return False, "paragraph_continuation must cross an adjacent page boundary"
        return True, ""

    return False, f"unsupported relation type {rel.relation_type!r}"


def deterministic_wrapper_id(
    relation_type: RelationType,
    source_block_ids: list[str],
    existing_ids: set[str],
) -> str:
    """Create a stable relation wrapper ID without colliding with source IDs."""
    payload = f"{relation_type}|{'|'.join(source_block_ids)}".encode()
    base = f"relation-{relation_type}-{hashlib.sha256(payload).hexdigest()[:16]}"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def validate_unique_block_ids(blocks: list[Block]) -> list[str]:
    """Recursively validate that every IR block ID is unique."""
    seen: dict[str, str] = {}
    duplicates: list[str] = []

    def visit(items: list[Block], path: str) -> None:
        for index, block in enumerate(items):
            current_path = f"{path}[{index}]"
            if block.id in seen:
                duplicates.append(
                    f"duplicate block id {block.id!r} at {current_path}; first at {seen[block.id]}"
                )
            else:
                seen[block.id] = current_path
            children = getattr(block, "blocks", None)
            if isinstance(children, list):
                visit(children, f"{current_path}.blocks")

    visit(blocks, "blocks")
    return duplicates


__all__ = [
    "RelationKey",
    "RelationConflict",
    "ReconciledRelation",
    "RelationType",
    "SemanticRelationDecision",
    "deterministic_wrapper_id",
    "reconcile_relation_batches",
    "relation_key",
    "validate_relation",
    "validate_unique_block_ids",
]
