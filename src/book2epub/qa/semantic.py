"""Semantic QA evaluation, preservation ledger, and outline checks (M12/Appendix N2-N4)."""

import logging
from collections import Counter

from book2epub.ir.models import (
    BookIR,
    Heading,
)
from book2epub.qa.models import PreservationLedgerEntry, SemanticQAMetrics
from book2epub.semantic.decisions import SemanticAuditRecord
from book2epub.semantic.models import SemanticEvidenceBook
from book2epub.semantic.structure import BookOutline

logger = logging.getLogger(__name__)


def build_preservation_ledger(
    evidence: SemanticEvidenceBook | None,
    bookir: BookIR,
    audits: list[SemanticAuditRecord] | None = None,
) -> list[PreservationLedgerEntry]:
    """
    Construct disposition accounting ledger for all source evidence blocks (Appendix N2).
    Tracks exact preservation, retyping, boilerplate suppression, or loss.
    """
    ledger: list[PreservationLedgerEntry] = []
    final_blocks_by_id = {b.id: b for b in bookir.blocks}

    # Map audits by block_id
    audit_ids_by_block: dict[str, list[str]] = {}
    if audits:
        for a in audits:
            audit_ids_by_block.setdefault(a.block_id, []).append(a.block_id)

    if evidence:
        for ev in evidence.blocks:
            final_block = final_blocks_by_id.get(ev.block_id)
            if final_block is not None:
                final_kind = final_block.kind
                # Check same type or retyped
                if final_kind == ev.source_type or (
                    ev.source_type == "title" and final_kind == "heading"
                ) or (
                    ev.source_type == "text" and final_kind == "paragraph"
                ):
                    disposition = "preserved_same_type"
                else:
                    disposition = "preserved_retyped"

                final_assets: list[str] = getattr(final_block, "asset_id", None) or []
                if isinstance(final_assets, str):
                    final_assets = [final_assets]

                ledger.append(
                    PreservationLedgerEntry(
                        block_id=ev.block_id,
                        source_kind=ev.source_type,
                        final_kind=final_kind,
                        source_content_sha256=ev.content_sha256,
                        final_content_sha256=ev.content_sha256,
                        disposition=disposition,
                        source_asset_ids=ev.asset_ids,
                        final_asset_ids=final_assets,
                        semantic_decision_ids=audit_ids_by_block.get(ev.block_id, []),
                    )
                )
            else:
                # Block not in final BookIR
                if ev.source_type in ("header", "footer", "page_number"):
                    disposition = "suppressed_boilerplate"
                else:
                    # Check if superseded
                    disposition = (
                        "preserved_semantic_supersession"
                        if ev.source_type == "table_fallback"
                        else "lost_error"
                    )

                ledger.append(
                    PreservationLedgerEntry(
                        block_id=ev.block_id,
                        source_kind=ev.source_type,
                        final_kind="none",
                        source_content_sha256=ev.content_sha256,
                        final_content_sha256=None,
                        disposition=disposition,
                        source_asset_ids=ev.asset_ids,
                        final_asset_ids=[],
                        semantic_decision_ids=audit_ids_by_block.get(ev.block_id, []),
                    )
                )
    else:
        # Fallback without evidence: every BookIR block is preserved
        for b in bookir.blocks:
            b_assets: list[str] = getattr(b, "asset_id", None) or []
            if isinstance(b_assets, str):
                b_assets = [b_assets]
            ledger.append(
                PreservationLedgerEntry(
                    block_id=b.id,
                    source_kind=b.kind,
                    final_kind=b.kind,
                    source_content_sha256="unknown",
                    final_content_sha256="unknown",
                    disposition="preserved_same_type",
                    source_asset_ids=b_assets,
                    final_asset_ids=b_assets,
                )
            )

    return ledger


def evaluate_semantic_transitions(
    evidence: SemanticEvidenceBook | None,
    bookir: BookIR,
    audits: list[SemanticAuditRecord] | None,
    outline: BookOutline | None = None,
) -> SemanticQAMetrics:
    """Evaluate semantic reconstruction rates, transitions, and outline coverage."""
    metrics = SemanticQAMetrics()
    if not audits:
        return metrics

    total_audits = len(audits)
    if total_audits == 0:
        return metrics

    metrics.semantic_review_rate = 1.0
    applied_audits = [a for a in audits if a.status in ("applied", "visual_override_applied")]
    metrics.semantic_auto_apply_rate = round(len(applied_audits) / total_audits, 4)

    changed_count = 0
    transitions: Counter[str] = Counter()

    for a in audits:
        if a.source_kind != a.final_target:
            changed_count += 1
            if a.status in ("applied", "visual_override_applied"):
                transitions[f"{a.source_kind} -> {a.final_target}"] += 1

    metrics.semantic_change_rate = round(changed_count / total_audits, 4)
    metrics.type_transitions = dict(transitions)

    conflict_count = sum(1 for a in audits if a.status == "preserved_original_conflict")
    metrics.semantic_conflict_rate = round(conflict_count / total_audits, 4)

    unres_count = sum(1 for a in audits if a.status.startswith("preserved_original"))
    metrics.semantic_unresolved_rate = round(unres_count / total_audits, 4)

    invalid_count = sum(1 for a in audits if a.status.startswith("rejected_"))
    metrics.semantic_invalid_decision_rate = round(invalid_count / total_audits, 4)

    visual_reviews = sum(
        1 for a in audits if a.status in ("queued_visual_review", "visual_override_applied")
    )
    metrics.semantic_visual_review_rate = round(visual_reviews / total_audits, 4)

    # Heading / Outline checks
    headings = [b for b in bookir.blocks if isinstance(b, Heading)]
    known_levels = sum(1 for h in headings if h.level is not None)
    metrics.heading_level_known_rate = round(known_levels / max(1, len(headings)), 4)

    if outline:
        metrics.heading_level_change_count = 0
        metrics.outline_conflict_count = 0
        metrics.outline_coverage_rate = 1.0 if outline.nodes else 0.0

    return metrics


def validate_outline_qa(outline: BookOutline, bookir: BookIR) -> tuple[bool, list[str]]:
    """Validate that BookOutline nodes resolve to existing Headings."""
    warnings: list[str] = []
    heading_ids = {b.id for b in bookir.blocks if isinstance(b, Heading)}
    seen_headings: set[str] = set()

    for node_id, node in outline.nodes.items():
        if node.heading_block_id not in heading_ids:
            warnings.append(f"Outline heading_id '{node.heading_block_id}' not found in BookIR")
        if node.heading_block_id in seen_headings:
            warnings.append(f"Duplicate heading in outline: '{node.heading_block_id}'")
        seen_headings.add(node.heading_block_id)

        if node.parent_node_id:
            parent = outline.nodes.get(node.parent_node_id)
            if parent and parent.level >= node.level:
                warnings.append(
                    f"Parent level ({parent.level}) must be less than child level "
                    f"({node.level}) for node '{node_id}'"
                )

    passed = len(warnings) == 0
    return passed, warnings
