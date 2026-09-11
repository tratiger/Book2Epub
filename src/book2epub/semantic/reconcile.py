"""Reconciliation of overlapping chunk decisions (M8 spec Section 7, Appendix I6)."""

from dataclasses import dataclass, field

from book2epub.semantic.decisions import (
    SemanticBlockDecision,
    SemanticConflict,
    SemanticDecisionBatch,
)
from book2epub.semantic.relations import (
    ReconciledRelation,
    RelationConflict,
    reconcile_relation_batches,
)
from book2epub.semantic.structure import (
    StructureDecision,
    StructureDecisionBatch,
)

__all__ = [
    "ReconciledRelation",
    "RelationConflict",
    "reconcile_relation_batches",
    "ReconciledStructureDecision",
    "ReconciledSemanticDecision",
    "reconcile_structure_batches",
    "reconcile_semantic_batches",
]


@dataclass
class ReconciledStructureDecision:
    """Consolidated Pass A decision across chunk overlaps."""

    block_id: str
    is_heading: bool | None
    heading_level: int | None
    paragraph_continuation_of: str | None
    confidence: float
    evidence_codes: list[str] = field(default_factory=list)
    rationales: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    single_vote: bool = False
    is_conflict: bool = False
    conflict_details: str | None = None


@dataclass
class ReconciledSemanticDecision:
    """Consolidated Pass B decision across chunk overlaps."""

    block_id: str
    target: str
    heading_level: int | None
    confidence: float
    evidence_codes: list[str] = field(default_factory=list)
    rationales: list[str] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    single_vote: bool = False
    is_conflict: bool = False
    conflict_details: str | None = None


def reconcile_structure_batches(
    batches: list[StructureDecisionBatch],
    overlap_block_ids: set[str] | None = None,
) -> tuple[dict[str, ReconciledStructureDecision], list[SemanticConflict]]:
    """
    Reconcile Pass A StructureDecisions across overlapping chunks.
    """
    grouped: dict[str, list[tuple[str, StructureDecision]]] = {}
    for batch in batches:
        for dec in batch.decisions:
            grouped.setdefault(dec.block_id, []).append((batch.chunk_id, dec))

    reconciled: dict[str, ReconciledStructureDecision] = {}
    conflicts: list[SemanticConflict] = []
    overlap_ids = overlap_block_ids or set()

    for block_id, dec_pairs in grouped.items():
        chunk_ids = [cp[0] for cp in dec_pairs]
        decisions = [cp[1] for cp in dec_pairs]

        if len(decisions) == 1:
            dec = decisions[0]
            # Single vote check: was this block present in multiple chunks' overlap?
            is_single_vote = block_id in overlap_ids and len(batches) > 1
            reconciled[block_id] = ReconciledStructureDecision(
                block_id=block_id,
                is_heading=dec.is_heading,
                heading_level=dec.heading_level,
                paragraph_continuation_of=dec.paragraph_continuation_of,
                confidence=dec.confidence,
                evidence_codes=list(dec.evidence_codes),
                rationales=[dec.rationale] if dec.rationale else [],
                chunk_ids=chunk_ids,
                single_vote=is_single_vote,
                is_conflict=False,
            )
            continue

        # Check for conflicts among multiple decisions
        headings = [d.is_heading for d in decisions]
        levels = [d.heading_level for d in decisions]
        conts = [d.paragraph_continuation_of for d in decisions]

        has_conflict = False
        if len(set(headings)) > 1:
            has_conflict = True
        elif (
            any(h is True for h in headings)
            and len({lvl for lvl in levels if lvl is not None}) > 1
        ):
            has_conflict = True
        elif len(set(conts)) > 1:
            has_conflict = True

        if has_conflict:
            conf_targets = [
                f"is_heading={d.is_heading},lvl={d.heading_level}" for d in decisions
            ]
            conflict = SemanticConflict(
                block_id=block_id,
                conflicting_targets=conf_targets,
                conflicting_levels=[d.heading_level for d in decisions],
                confidences=[d.confidence for d in decisions],
                chunk_ids=chunk_ids,
            )
            conflicts.append(conflict)
            reconciled[block_id] = ReconciledStructureDecision(
                block_id=block_id,
                is_heading=None,
                heading_level=None,
                paragraph_continuation_of=None,
                confidence=0.0,
                evidence_codes=["AMBIGUOUS"],
                rationales=[d.rationale for d in decisions if d.rationale],
                chunk_ids=chunk_ids,
                single_vote=False,
                is_conflict=True,
                conflict_details="Conflicting Pass A decisions in chunk overlap",
            )
        else:
            # Agreement: merge confidence as arithmetic mean
            mean_conf = round(sum(d.confidence for d in decisions) / len(decisions), 3)
            all_codes: set[str] = set()
            for d in decisions:
                all_codes.update(d.evidence_codes)
            all_rats = [d.rationale for d in decisions if d.rationale]

            reconciled[block_id] = ReconciledStructureDecision(
                block_id=block_id,
                is_heading=decisions[0].is_heading,
                heading_level=decisions[0].heading_level,
                paragraph_continuation_of=decisions[0].paragraph_continuation_of,
                confidence=mean_conf,
                evidence_codes=sorted(list(all_codes)),
                rationales=all_rats,
                chunk_ids=chunk_ids,
                single_vote=False,
                is_conflict=False,
            )

    return reconciled, conflicts


def reconcile_semantic_batches(
    batches: list[SemanticDecisionBatch],
    overlap_block_ids: set[str] | None = None,
) -> tuple[dict[str, ReconciledSemanticDecision], list[SemanticConflict]]:
    """
    Reconcile Pass B SemanticDecisions across overlapping chunks.
    """
    grouped: dict[str, list[tuple[str, SemanticBlockDecision]]] = {}
    for batch in batches:
        for dec in batch.decisions:
            grouped.setdefault(dec.block_id, []).append((batch.chunk_id, dec))

    reconciled: dict[str, ReconciledSemanticDecision] = {}
    conflicts: list[SemanticConflict] = []
    overlap_ids = overlap_block_ids or set()

    for block_id, dec_pairs in grouped.items():
        chunk_ids = [cp[0] for cp in dec_pairs]
        decisions = [cp[1] for cp in dec_pairs]

        def codes(decision: SemanticBlockDecision) -> list[str]:
            legacy_codes = getattr(decision, "_legacy_evidence_codes", [])
            return list(legacy_codes or decision.evidence_codes)

        if len(decisions) == 1:
            dec = decisions[0]
            is_single_vote = block_id in overlap_ids and len(batches) > 1
            reconciled[block_id] = ReconciledSemanticDecision(
                block_id=block_id,
                target=dec.target,
                heading_level=dec.heading_level,
                confidence=dec.confidence,
                evidence_codes=codes(dec),
                rationales=[dec.rationale] if dec.rationale else [],
                chunk_ids=chunk_ids,
                single_vote=is_single_vote,
                is_conflict=False,
            )
            continue

        # Check for conflict in target or level
        targets = [d.target for d in decisions]
        levels = [d.heading_level for d in decisions]

        has_conflict = False
        if len(set(targets)) > 1:
            has_conflict = True
        elif (
            any(lvl is not None for lvl in levels)
            and len({lvl for lvl in levels if lvl is not None}) > 1
        ):
            has_conflict = True

        if has_conflict:
            conflict = SemanticConflict(
                block_id=block_id,
                conflicting_targets=[str(t) for t in targets],
                conflicting_levels=levels,
                confidences=[d.confidence for d in decisions],
                chunk_ids=chunk_ids,
            )
            conflicts.append(conflict)
            reconciled[block_id] = ReconciledSemanticDecision(
                block_id=block_id,
                target="keep_original",
                heading_level=None,
                confidence=0.0,
                evidence_codes=["AMBIGUOUS"],
                rationales=[d.rationale for d in decisions if d.rationale],
                chunk_ids=chunk_ids,
                single_vote=False,
                is_conflict=True,
                conflict_details="Conflicting Pass B targets in chunk overlap",
            )
        else:
            mean_conf = round(sum(d.confidence for d in decisions) / len(decisions), 3)
            all_codes: set[str] = set()
            for d in decisions:
                all_codes.update(codes(d))
            all_rats = [d.rationale for d in decisions if d.rationale]

            reconciled[block_id] = ReconciledSemanticDecision(
                block_id=block_id,
                target=decisions[0].target,
                heading_level=decisions[0].heading_level,
                confidence=mean_conf,
                evidence_codes=sorted(list(all_codes)),
                rationales=all_rats,
                chunk_ids=chunk_ids,
                single_vote=False,
                is_conflict=False,
            )

    return reconciled, conflicts
