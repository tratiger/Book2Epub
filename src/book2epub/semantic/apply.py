"""Materialization and deterministic application of validated semantic decisions
(M8 spec Section 11 & Appendix H8-H11)."""

import logging

from book2epub.errors import SemanticError
from book2epub.ir.models import (
    Aside,
    Block,
    BlockQuote,
    Callout,
    Chart,
    CodeBlock,
    ExampleBlock,
    Figure,
    Footnote,
    Heading,
    Hyperlink,
    Inline,
    InlineMath,
    LineBreak,
    ListBlock,
    PageBoundary,
    Paragraph,
    PreformattedBlock,
    PreformattedSubtype,
    Table,
    Text,
)
from book2epub.semantic.decisions import SemanticAuditRecord, SemanticRelationAuditRecord
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.materializers import materializer_for
from book2epub.semantic.models import SemanticEvidenceBlock
from book2epub.semantic.reconcile import (
    ReconciledSemanticDecision,
    ReconciledStructureDecision,
)
from book2epub.semantic.relations import (
    ReconciledRelation,
    RelationKey,
    deterministic_wrapper_id,
    validate_relation,
)
from book2epub.semantic.validation import validate_structure_continuation

logger = logging.getLogger(__name__)


def extract_inlines_text(inlines: list[Inline]) -> str:
    """Extract plain string content from a list of Inlines."""
    res: list[str] = []
    for inl in inlines:
        if isinstance(inl, Text):
            res.append(inl.text)
        elif isinstance(inl, InlineMath):
            res.append(inl.latex)
        elif isinstance(inl, Hyperlink):
            res.append(extract_inlines_text(inl.children))
        elif isinstance(inl, LineBreak):
            res.append("\n")
    return "".join(res)


def extract_block_visible_text(block: Block) -> str:
    """Extract visible user text for content-hash invariant checks.

    NOTE: Table is intentionally excluded — the invariant for Table→Preformatted
    conversions is checked via evidence.preformatted_text, not a hash of the IR
    node which contains HTML. Returning an empty string here for Table is
    intentional so callers that need Table content must use the evidence source.
    """
    if isinstance(block, (Paragraph, Heading, Aside)):
        return extract_inlines_text(block.inlines)
    elif isinstance(block, CodeBlock):
        return block.text
    elif isinstance(block, PreformattedBlock):
        return block.text
    elif isinstance(block, Callout):
        return "".join(extract_block_visible_text(b) for b in block.blocks)
    elif isinstance(block, BlockQuote):
        return "".join(extract_block_visible_text(b) for b in block.blocks)
    elif isinstance(block, ListBlock):
        return "\n".join(extract_inlines_text(item) for item in block.items)
    # Table: visible text is in HTML source, not directly comparable via this helper.
    # Callers must use SemanticEvidenceBlock.preformatted_text for Table content.
    return ""


def verify_block_hash(evidence_block: SemanticEvidenceBlock, expected_hash: str) -> bool:
    """Verify that the evidence block content hash matches expected decision hash."""
    return evidence_block.content_sha256 == expected_hash


def validate_semantic_target(evidence_block: SemanticEvidenceBlock, target: str) -> bool:
    """Validate that the proposed target is in the block's allowed targets."""
    return target in evidence_block.allowed_targets


def materialize_preformatted_from_evidence(
    evidence_block: SemanticEvidenceBlock,
    subtype: PreformattedSubtype = "generic_preformatted",
) -> PreformattedBlock:
    """
    Deterministically construct a PreformattedBlock from SemanticEvidenceBlock.
    The text field originates from source lines, not model-generated text
    (M6 spec Section 2.1, Appendix H10).
    """
    if evidence_block.preformatted_text is None:
        raise SemanticError(
            f"Cannot materialize preformatted block for {evidence_block.block_id}: "
            "no preformatted_text evidence exists."
        )

    return PreformattedBlock(
        id=evidence_block.block_id,
        text=evidence_block.preformatted_text,
        subtype=subtype,
    )


# ---------------------------------------------------------------------------
# Pass A: Structure decisions (heading promotion/demotion, continuation)
# ---------------------------------------------------------------------------

def apply_structure_decisions(
    blocks: list[Block],
    decisions: dict[str, ReconciledStructureDecision],
    evidence_lookup: dict[str, SemanticEvidenceBlock],
    auto_apply_threshold: float = 0.80,
    single_vote_threshold: float = 0.85,
) -> tuple[list[Block], list[SemanticAuditRecord]]:
    """
    Apply Pass A structural decisions (heading promotion/demotion and cross-page continuation).
    Enforces text immutability and returns (new_blocks, audit_records).

    No in-place mutation of input blocks. All modifications produce new node instances
    via constructor or model_copy.
    """
    new_blocks: list[Block] = []
    audits: list[SemanticAuditRecord] = []

    for blk in blocks:
        dec = decisions.get(blk.id)
        if not dec:
            new_blocks.append(blk)
            continue

        source_kind = blk.kind
        text_before = extract_block_visible_text(blk)
        hash_before = compute_text_sha256(text_before)

        # Check confidence threshold
        min_thresh = single_vote_threshold if dec.single_vote else auto_apply_threshold
        if dec.is_conflict:
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-a-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target="conflict",
                    final_target=source_kind,
                    confidence=dec.confidence,
                    evidence_codes=dec.evidence_codes,
                    provider="structure",
                    model="structure",
                    request_ids=dec.chunk_ids,
                    status="preserved_original_conflict",
                    rejection_reason=dec.conflict_details,
                    source_content_sha256=hash_before,
                )
            )
            new_blocks.append(blk)
            continue

        if dec.confidence < 0.45:
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-a-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target="heading" if dec.is_heading else "paragraph",
                    final_target=source_kind,
                    confidence=dec.confidence,
                    evidence_codes=dec.evidence_codes,
                    provider="structure",
                    model="structure",
                    request_ids=dec.chunk_ids,
                    status="preserved_original_low_confidence",
                    rejection_reason="Confidence below minimum review floor",
                    source_content_sha256=hash_before,
                )
            )
            new_blocks.append(blk)
            continue

        if dec.confidence < min_thresh:
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-a-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target="heading" if dec.is_heading else "paragraph",
                    final_target=source_kind,
                    confidence=dec.confidence,
                    evidence_codes=dec.evidence_codes,
                    provider="structure",
                    model="structure",
                    request_ids=dec.chunk_ids,
                    status="queued_visual_review",
                    rejection_reason="Confidence below auto-apply threshold",
                    source_content_sha256=hash_before,
                )
            )
            new_blocks.append(blk)
            continue

        # Handle cross-page paragraph continuation
        if dec.paragraph_continuation_of and isinstance(blk, Paragraph) and new_blocks:
            prior_id = dec.paragraph_continuation_of
            prior_blk = new_blocks[-1]
            if prior_blk.id == prior_id and isinstance(prior_blk, Paragraph):
                continuation_ok, continuation_reason = validate_structure_continuation(
                    prior_blk,
                    blk,
                    evidence_lookup,
                )
                if not continuation_ok:
                    audits.append(
                        SemanticAuditRecord(
                            decision_id=f"pass-a-cont-{blk.id}",
                            block_id=blk.id,
                            source_kind=source_kind,
                            proposed_target="paragraph_continuation",
                            final_target=source_kind,
                            confidence=dec.confidence,
                            evidence_codes=dec.evidence_codes,
                            provider="structure",
                            model="structure",
                            request_ids=dec.chunk_ids,
                            status="rejected_invalid_continuation",
                            rejection_reason=continuation_reason,
                            source_content_sha256=hash_before,
                        )
                    )
                else:
                    # Build merged paragraph WITHOUT in-place mutation of prior_blk.
                    # Construct new combined inlines and sources lists.
                    page_boundary = PageBoundary(
                        page_idx=blk.sources[0].page_idx if blk.sources else 0
                    )
                    merged_inlines = list(prior_blk.inlines) + [page_boundary] + list(blk.inlines)
                    merged_sources = list(prior_blk.sources) + list(blk.sources)
                    merged_para = prior_blk.model_copy(
                        update={"inlines": merged_inlines, "sources": merged_sources}
                    )
                    # Replace the last element in new_blocks with the merged paragraph
                    new_blocks[-1] = merged_para

                    audits.append(
                        SemanticAuditRecord(
                            decision_id=f"pass-a-cont-{blk.id}",
                            block_id=blk.id,
                            source_kind=source_kind,
                            proposed_target="paragraph_continuation",
                            final_target="merged_continuation",
                            confidence=dec.confidence,
                            evidence_codes=dec.evidence_codes,
                            provider="structure",
                            model="structure",
                            request_ids=dec.chunk_ids,
                            status="applied",
                            source_content_sha256=hash_before,
                        )
                    )
                    continue

        # Handle heading promotion / demotion / level setting
        if dec.is_heading is True and dec.heading_level is not None:
            if isinstance(blk, Paragraph):
                new_heading = Heading(
                    id=blk.id,
                    sources=blk.sources,
                    level=dec.heading_level,
                    inlines=blk.inlines,
                )
                text_after = extract_block_visible_text(new_heading)
                if compute_text_sha256(text_after) != hash_before:
                    raise SemanticError(
                        f"Content hash violation when retyping Paragraph {blk.id} to Heading!"
                    )
                new_blocks.append(new_heading)
                audits.append(
                    SemanticAuditRecord(
                        decision_id=f"pass-a-{blk.id}",
                        block_id=blk.id,
                        source_kind=source_kind,
                        proposed_target=f"heading_h{dec.heading_level}",
                        final_target=f"heading_h{dec.heading_level}",
                        confidence=dec.confidence,
                        evidence_codes=dec.evidence_codes,
                        provider="structure",
                        model="structure",
                        request_ids=dec.chunk_ids,
                        status="applied",
                        source_content_sha256=hash_before,
                    )
                )
                continue
            elif isinstance(blk, Heading):
                # model_copy: no in-place mutation
                new_heading = blk.model_copy(update={"level": dec.heading_level})
                new_blocks.append(new_heading)
                audits.append(
                    SemanticAuditRecord(
                        decision_id=f"pass-a-{blk.id}",
                        block_id=blk.id,
                        source_kind=source_kind,
                        proposed_target=f"heading_h{dec.heading_level}",
                        final_target=f"heading_h{dec.heading_level}",
                        confidence=dec.confidence,
                        evidence_codes=dec.evidence_codes,
                        provider="structure",
                        model="structure",
                        request_ids=dec.chunk_ids,
                        status="applied",
                        source_content_sha256=hash_before,
                    )
                )
                continue

        elif dec.is_heading is False and isinstance(blk, Heading):
            # Demote heading to paragraph
            new_para = Paragraph(
                id=blk.id,
                sources=blk.sources,
                inlines=blk.inlines,
            )
            text_after = extract_block_visible_text(new_para)
            if compute_text_sha256(text_after) != hash_before:
                raise SemanticError(
                    f"Content hash violation when demoting Heading {blk.id} to Paragraph!"
                )
            new_blocks.append(new_para)
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-a-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target="paragraph",
                    final_target="paragraph",
                    confidence=dec.confidence,
                    evidence_codes=dec.evidence_codes,
                    provider="structure",
                    model="structure",
                    request_ids=dec.chunk_ids,
                    status="applied",
                    source_content_sha256=hash_before,
                )
            )
            continue

        new_blocks.append(blk)

    return new_blocks, audits


# ---------------------------------------------------------------------------
# Pass B: Semantic block decisions
# ---------------------------------------------------------------------------

def _reject_invalid(
    blk: Block,
    source_kind: str,
    target: str,
    dec: ReconciledSemanticDecision,
    hash_before: str,
    reason: str,
) -> tuple[Block, SemanticAuditRecord]:
    """Produce a rejection audit record and return the original block unchanged."""
    return blk, SemanticAuditRecord(
        decision_id=f"pass-b-{blk.id}",
        block_id=blk.id,
        source_kind=source_kind,
        proposed_target=target,
        final_target=source_kind,
        confidence=dec.confidence,
        evidence_codes=dec.evidence_codes,
        provider="semantic",
        model="semantic",
        request_ids=dec.chunk_ids,
        status="rejected_invalid_target",
        rejection_reason=reason,
        source_content_sha256=hash_before,
    )


def apply_semantic_decisions(
    blocks: list[Block],
    decisions: dict[str, ReconciledSemanticDecision],
    evidence_lookup: dict[str, SemanticEvidenceBlock],
    auto_apply_threshold: float = 0.80,
    single_vote_threshold: float = 0.85,
    defer_relation_group_block_ids: set[str] | None = None,
) -> tuple[list[Block], list[SemanticAuditRecord]]:
    """
    Apply Pass B semantic block decisions (table -> preformatted, code subtype, callout, etc.).
    Enforces content immutability (M8 Section 11).

    Hard gate: for any target that is not keep/keep_original, the target MUST appear in
    evidence.allowed_targets before any case branch is executed. This prevents LLM
    hallucinated targets from reaching materialization.

    No in-place mutation of input blocks.
    """
    new_blocks: list[Block] = []
    audits: list[SemanticAuditRecord] = []
    deferred_group_ids = defer_relation_group_block_ids or set()

    for blk in blocks:
        dec = decisions.get(blk.id)
        if not dec or dec.target in ("keep", "keep_original"):
            new_blocks.append(blk)
            continue

        source_kind = blk.kind
        hash_before = compute_text_sha256(extract_block_visible_text(blk))
        target = dec.target

        # ------------------------------------------------------------------ #
        # Check conflict                                                       #
        # ------------------------------------------------------------------ #
        if dec.is_conflict:
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-b-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target=target,
                    final_target=source_kind,
                    confidence=dec.confidence,
                    evidence_codes=dec.evidence_codes,
                    provider="semantic",
                    model="semantic",
                    request_ids=dec.chunk_ids,
                    status="preserved_original_conflict",
                    rejection_reason=dec.conflict_details,
                    source_content_sha256=hash_before,
                )
            )
            new_blocks.append(blk)
            continue

        # ------------------------------------------------------------------ #
        # Confidence checks                                                    #
        # ------------------------------------------------------------------ #
        min_thresh = single_vote_threshold if dec.single_vote else auto_apply_threshold
        if dec.confidence < 0.45:
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-b-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target=target,
                    final_target=source_kind,
                    confidence=dec.confidence,
                    evidence_codes=dec.evidence_codes,
                    provider="semantic",
                    model="semantic",
                    request_ids=dec.chunk_ids,
                    status="preserved_original_low_confidence",
                    rejection_reason="Confidence below review floor",
                    source_content_sha256=hash_before,
                )
            )
            new_blocks.append(blk)
            continue

        if dec.confidence < min_thresh:
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-b-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target=target,
                    final_target=source_kind,
                    confidence=dec.confidence,
                    evidence_codes=dec.evidence_codes,
                    provider="semantic",
                    model="semantic",
                    request_ids=dec.chunk_ids,
                    status="queued_visual_review",
                    rejection_reason="Confidence below auto-apply threshold",
                    source_content_sha256=hash_before,
                )
            )
            new_blocks.append(blk)
            continue

        # ------------------------------------------------------------------ #
        # HARD GATE: allowed_targets check — must happen before any case       #
        # branch. Evidence block must exist and target must be in its          #
        # allowed_targets whitelist.                                           #
        # keep / keep_original already handled above; all other targets        #
        # require explicit evidence authorization.                             #
        # ------------------------------------------------------------------ #
        ev = evidence_lookup.get(blk.id)
        if ev is None:
            rejected_blk, audit = _reject_invalid(
                blk, source_kind, target, dec, hash_before,
                reason=(
                    f"No evidence block found for block_id={blk.id!r}; "
                    f"cannot authorize target={target!r}"
                ),
            )
            audits.append(audit)
            new_blocks.append(rejected_blk)
            continue

        if not validate_semantic_target(ev, target):
            rejected_blk, audit = _reject_invalid(
                blk, source_kind, target, dec, hash_before,
                reason=(
                    f"Target {target!r} not in allowed_targets for block {blk.id!r} "
                    f"(allowed: {ev.allowed_targets!r})"
                ),
            )
            audits.append(audit)
            new_blocks.append(rejected_blk)
            continue

        # A validated high-confidence member_of_callout relation owns grouping
        # for these source blocks. Keep the original paragraph until relation
        # application; otherwise Paragraph->Callout would create a duplicate
        # wrapper/child ID. This gate intentionally follows allowed_targets.
        if target.startswith("callout_") or target == "sidebar":
            if blk.id in deferred_group_ids:
                new_blocks.append(blk)
                continue

        materializer = materializer_for(blk, target, ev)
        if materializer is None:
            rejected_blk, audit = _reject_invalid(
                blk,
                source_kind,
                target,
                dec,
                hash_before,
                reason=f"No deterministic materializer for {source_kind} -> {target}",
            )
            audits.append(audit)
            new_blocks.append(rejected_blk)
            continue

        try:
            materialized = materializer.apply(blk, ev, dec)
            materialized_blocks = materialized if isinstance(materialized, list) else [materialized]
            if not materialized_blocks:
                raise ValueError("materializer returned no blocks")
            if target not in {"table"}:
                expected_text = (
                    ev.preformatted_text
                    if isinstance(blk, Table)
                    and isinstance(materialized_blocks[0], PreformattedBlock)
                    else extract_block_visible_text(blk)
                )
                actual_text = "\n".join(
                    "\n".join(extract_inlines_text(item) for item in block.items)
                    if isinstance(block, ListBlock)
                    else extract_block_visible_text(block)
                    for block in materialized_blocks
                )
                if expected_text != actual_text:
                    raise ValueError("materializer changed user-visible source content")
        except (SemanticError, ValueError) as exc:
            rejected_blk, audit = _reject_invalid(
                blk,
                source_kind,
                target,
                dec,
                hash_before,
                reason=f"Materializer rejected target: {exc}",
            )
            audits.append(audit)
            new_blocks.append(rejected_blk)
            continue

        new_blocks.extend(materialized_blocks)
        audits.append(
            SemanticAuditRecord(
                decision_id=f"pass-b-{blk.id}",
                block_id=blk.id,
                source_kind=source_kind,
                proposed_target=target,
                final_target=target,
                confidence=dec.confidence,
                evidence_codes=dec.evidence_codes,
                provider="semantic",
                model="semantic",
                request_ids=dec.chunk_ids,
                status="applied",
                source_content_sha256=hash_before,
            )
        )
        continue

        # Defensive fallback: every advertised target must have gone through
        # the canonical registry above. Never silently preserve a decision.
        rejected_blk, audit = _reject_invalid(
            blk,
            source_kind,
            target,
            dec,
            hash_before,
            reason=f"No deterministic materializer for {source_kind} -> {target}",
        )
        audits.append(audit)
        new_blocks.append(rejected_blk)

    return new_blocks, audits


def _relation_items(
    relations: dict[RelationKey, ReconciledRelation] | list[ReconciledRelation],
) -> list[ReconciledRelation]:
    if isinstance(relations, dict):
        return list(relations.values())
    return list(relations)


def _relation_audit(
    relation: ReconciledRelation,
    status: str,
    reason: str | None = None,
) -> SemanticRelationAuditRecord:
    return SemanticRelationAuditRecord(
        relation_id=(
            f"relation-{relation.relation_type}-"
            f"{'-'.join(relation.source_block_ids)}-"
            f"{relation.target_block_id or 'none'}"
        ),
        relation_type=relation.relation_type,
        source_block_ids=list(relation.source_block_ids),
        target_block_id=relation.target_block_id,
        confidence=relation.confidence,
        evidence_codes=relation.evidence_codes,
        provider="semantic",
        model="semantic",
        request_ids=relation.chunk_ids,
        status=status,  # type: ignore[arg-type]
        rejection_reason=reason,
    )


def _callout_subtype(
    source_blocks: list[Block],
    semantic_decisions: dict[str, ReconciledSemanticDecision],
    auto_apply_threshold: float,
    single_vote_threshold: float,
    evidence_lookup: dict[str, SemanticEvidenceBlock] | None = None,
) -> str | None:
    valid = {"note", "tip", "warning", "caution", "important", "sidebar"}

    def usable_decision(
        block: Block, decision: ReconciledSemanticDecision
    ) -> bool:
        if decision.is_conflict:
            return False
        decision_threshold = (
            single_vote_threshold if decision.single_vote else auto_apply_threshold
        )
        if decision.confidence < decision_threshold:
            return False
        if evidence_lookup is not None:
            evidence = evidence_lookup.get(block.id)
            if evidence is None or not validate_semantic_target(evidence, decision.target):
                return False
        return True

    # An explicit but unauthorized callout decision must not become authorized
    # indirectly through a group relation. It also prevents a different source
    # in the same group from masking the invalid target.
    for block in source_blocks:
        decision = semantic_decisions.get(block.id)
        if decision is not None and (
            decision.target.startswith("callout_") or decision.target == "sidebar"
        ) and not usable_decision(block, decision):
            return None

    for block in source_blocks:
        if isinstance(block, Callout):
            return block.subtype
        decision = semantic_decisions.get(block.id)
        if decision is None or not usable_decision(block, decision):
            continue
        target = decision.target if decision else ""
        if target.startswith("callout_"):
            subtype = target.removeprefix("callout_")
            if subtype in valid:
                return subtype
        if target == "sidebar":
            return "sidebar"
    return None


def apply_semantic_relations(
    blocks: list[Block],
    relations: dict[RelationKey, ReconciledRelation] | list[ReconciledRelation],
    semantic_decisions: dict[str, ReconciledSemanticDecision] | None = None,
    auto_apply_threshold: float = 0.80,
    single_vote_threshold: float = 0.85,
    evidence_lookup: dict[str, SemanticEvidenceBlock] | None = None,
) -> tuple[list[Block], list[SemanticRelationAuditRecord]]:
    """Validate and apply reconciled Pass B relations without generating text."""
    current = list(blocks)
    audits: list[SemanticRelationAuditRecord] = []
    decisions = semantic_decisions or {}
    attached_caption_sources: dict[str, str] = {}
    attached_footnote_sources: dict[str, str] = {}

    relation_items = _relation_items(relations)
    relation_items.sort(
        key=lambda rel: (
            min((next((i for i, block in enumerate(current) if block.id == sid), 10**9)
                 for sid in rel.source_block_ids), default=10**9),
            rel.relation_type,
            tuple(rel.source_block_ids),
        )
    )

    for relation in relation_items:
        if relation.is_conflict:
            audits.append(
                _relation_audit(relation, "conflict", relation.conflict_details)
            )
            continue

        threshold = single_vote_threshold if relation.single_vote else auto_apply_threshold
        if relation.confidence < threshold:
            audits.append(
                _relation_audit(
                    relation,
                    "queued_visual",
                    "Confidence below relation auto-apply threshold",
                )
            )
            continue

        blocks_by_id = {block.id: block for block in current}
        block_order = {block.id: index for index, block in enumerate(current)}
        valid, reason = validate_relation(relation, blocks_by_id, block_order)
        if not valid:
            audits.append(_relation_audit(relation, "rejected", reason))
            continue

        source_ids = relation.source_block_ids
        target_id = relation.target_block_id
        if relation.relation_type == "caption_of" or relation.relation_type == "footnote_of":
            assert target_id is not None
            source_id = source_ids[0]
            source = blocks_by_id[source_id]
            target = blocks_by_id[target_id]
            source_inlines = _source_inlines_for_relation(source)
            if source_inlines is None:
                audits.append(
                    _relation_audit(
                        relation, "rejected", "source has no movable inline content"
                    )
                )
                continue
            attached = (
                attached_caption_sources if relation.relation_type == "caption_of"
                else attached_footnote_sources
            )
            previous_target = attached.get(source_id)
            if previous_target is not None and previous_target != target_id:
                audits.append(
                    _relation_audit(
                        relation,
                        "rejected",
                        "source is already attached to another target",
                    )
                )
                continue
            updated_field = "caption" if relation.relation_type == "caption_of" else "footnotes"
            if relation.relation_type == "caption_of":
                updated_inlines = source_inlines
            else:
                assert isinstance(target, (Figure, Chart, Table, CodeBlock, PreformattedBlock))
                existing_footnotes = list(target.footnotes)
                updated_inlines = existing_footnotes[:]
                for inline in source_inlines:
                    if not any(
                        existing_inline.model_dump() == inline.model_dump()
                        for existing_inline in updated_inlines
                    ):
                        updated_inlines.append(inline)
            updated = target.model_copy(update={updated_field: updated_inlines})
            current[block_order[target_id]] = updated
            attached[source_id] = target_id
            current = [block for block in current if block.id != source_id]
            audits.append(_relation_audit(relation, "applied"))
            continue

        if relation.relation_type in {"member_of_callout", "member_of_example"}:
            source_blocks = [blocks_by_id[source_id] for source_id in source_ids]
            existing_ids = {block.id for block in current}
            wrapper_id = deterministic_wrapper_id(
                relation.relation_type, source_ids, existing_ids
            )
            wrapper_sources = []
            for source_block in source_blocks:
                for source_ref in source_block.sources:
                    if source_ref not in wrapper_sources:
                        wrapper_sources.append(source_ref)
            if relation.relation_type == "member_of_callout":
                subtype = _callout_subtype(
                    source_blocks,
                    decisions,
                    auto_apply_threshold,
                    single_vote_threshold,
                    evidence_lookup,
                )
                if subtype is None:
                    audits.append(
                        _relation_audit(
                            relation, "rejected", "no validated callout subtype"
                        )
                    )
                    continue
                wrapper: Block = Callout(
                    id=wrapper_id,
                    sources=wrapper_sources,
                    subtype=subtype,  # type: ignore[arg-type]
                    blocks=source_blocks,
                )
            else:
                wrapper = ExampleBlock(
                    id=wrapper_id,
                    sources=wrapper_sources,
                    blocks=source_blocks,
                )
            first_index = min(block_order[source_id] for source_id in source_ids)
            current = [block for block in current if block.id not in set(source_ids)]
            current.insert(first_index, wrapper)
            audits.append(_relation_audit(relation, "applied"))
            continue

        if relation.relation_type == "paragraph_continuation":
            assert target_id is not None
            source = blocks_by_id[source_ids[0]]
            target = blocks_by_id[target_id]
            assert isinstance(source, Paragraph) and isinstance(target, Paragraph)
            merged = source.model_copy(
                update={
                    "inlines": list(source.inlines)
                    + [PageBoundary(page_idx=target.sources[0].page_idx)]
                    + list(target.inlines),
                    "sources": list(source.sources) + list(target.sources),
                }
            )
            current[block_order[source.id]] = merged
            current = [block for block in current if block.id != target.id]
            audits.append(_relation_audit(relation, "applied"))
            continue

        audits.append(_relation_audit(relation, "rejected", "unsupported relation type"))

    return current, audits


def _source_inlines_for_relation(block: Block) -> list[Inline] | None:
    if isinstance(block, (Paragraph, Heading, Footnote)):
        return list(block.inlines)
    return None
