"""Materialization and deterministic application of validated semantic decisions
(M8 spec Section 11 & Appendix H8-H11)."""

import logging

from book2epub.errors import SemanticError
from book2epub.ir.models import (
    Block,
    BlockQuote,
    Callout,
    CodeBlock,
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
from book2epub.semantic.decisions import SemanticAuditRecord
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.models import SemanticEvidenceBlock
from book2epub.semantic.reconcile import (
    ReconciledSemanticDecision,
    ReconciledStructureDecision,
)

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
    if isinstance(block, (Paragraph, Heading)):
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
        return "".join(extract_inlines_text(item) for item in block.items)
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

_PREFORMATTED_SUBTYPES = frozenset({
    "terminal_output",
    "shell_command",
    "source_code",
    "log_output",
    "config_file",
    "generic_preformatted",
    "repl_session",
    "terminal_session",
})


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

        # ------------------------------------------------------------------ #
        # 1. table -> preformatted (terminal_output, shell_command, etc.)     #
        # ------------------------------------------------------------------ #
        if isinstance(blk, Table) and target in _PREFORMATTED_SUBTYPES:
            if not ev.preformatted_text:
                rejected_blk, audit = _reject_invalid(
                    blk, source_kind, target, dec, hash_before,
                    reason="No preformatted text evidence exists",
                )
                audits.append(audit)
                new_blocks.append(rejected_blk)
                continue

            # Table content invariant: use evidence preformatted_text for
            # new block; do NOT use extract_block_visible_text(Table)=="".
            new_blk = PreformattedBlock(
                id=blk.id,
                sources=blk.sources,
                subtype=target,  # type: ignore[arg-type]
                text=ev.preformatted_text,
                caption=list(blk.caption),
                footnotes=list(blk.footnotes),
            )
            new_blocks.append(new_blk)
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

        # ------------------------------------------------------------------ #
        # 2. code -> richer preformatted subtype                              #
        # ------------------------------------------------------------------ #
        if isinstance(blk, CodeBlock) and target in _PREFORMATTED_SUBTYPES:
            new_blk = PreformattedBlock(
                id=blk.id,
                sources=blk.sources,
                subtype=target,  # type: ignore[arg-type]
                text=blk.text,
                language=blk.language,
                caption=list(blk.caption),
                footnotes=list(blk.footnotes),
            )
            # Text bytes must match CodeBlock.text exactly
            assert compute_text_sha256(new_blk.text) == compute_text_sha256(blk.text)
            new_blocks.append(new_blk)
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

        # ------------------------------------------------------------------ #
        # 2b. preformatted -> alternate preformatted subtype                  #
        # ------------------------------------------------------------------ #
        if isinstance(blk, PreformattedBlock) and target in _PREFORMATTED_SUBTYPES:
            new_blk = blk.model_copy(update={"subtype": target})
            new_blocks.append(new_blk)
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

        # 3. paragraph -> callout                                             #
        # ------------------------------------------------------------------ #
        if isinstance(blk, Paragraph) and (target.startswith("callout_") or target == "sidebar"):
            callout_sub = (
                target.replace("callout_", "") if target.startswith("callout_") else "sidebar"
            )
            if callout_sub not in ("note", "tip", "warning", "caution", "important", "sidebar"):
                callout_sub = "note"
            new_callout = Callout(
                id=blk.id,
                sources=blk.sources,
                subtype=callout_sub,  # type: ignore[arg-type]
                blocks=[blk],
            )
            text_after = extract_block_visible_text(new_callout)
            if compute_text_sha256(text_after) != hash_before:
                raise SemanticError(
                    f"Content hash violation when wrapping Paragraph {blk.id} into Callout!"
                )
            new_blocks.append(new_callout)
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-b-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target=target,
                    final_target=f"callout_{callout_sub}",
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

        # ------------------------------------------------------------------ #
        # 4. paragraph -> block quote                                         #
        # ------------------------------------------------------------------ #
        if isinstance(blk, Paragraph) and target in ("quote", "block_quote"):
            new_quote = BlockQuote(
                id=blk.id,
                sources=blk.sources,
                blocks=[blk],
            )
            text_after = extract_block_visible_text(new_quote)
            if compute_text_sha256(text_after) != hash_before:
                raise SemanticError(
                    f"Content hash violation when wrapping Paragraph {blk.id} into BlockQuote!"
                )
            new_blocks.append(new_quote)
            audits.append(
                SemanticAuditRecord(
                    decision_id=f"pass-b-{blk.id}",
                    block_id=blk.id,
                    source_kind=source_kind,
                    proposed_target=target,
                    final_target="block_quote",
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

        # ------------------------------------------------------------------ #
        # 5. paragraph -> list                                                #
        # ------------------------------------------------------------------ #
        if isinstance(blk, Paragraph) and target in ("list", "unordered_list", "ordered_list"):
            # Allowed only when evidence has at least two source lines/items with parsable marker
            text_before_visible = extract_block_visible_text(blk)
            lines = text_before_visible.strip().splitlines()
            if len(lines) >= 2:
                items: list[list[Inline]] = [
                    [Text(text=line)] for line in lines if line.strip()
                ]
                is_ordered = target == "ordered_list"
                new_list = ListBlock(
                    id=blk.id,
                    sources=blk.sources,
                    ordered=is_ordered,
                    items=items,
                )
                new_blocks.append(new_list)
                audits.append(
                    SemanticAuditRecord(
                        decision_id=f"pass-b-{blk.id}",
                        block_id=blk.id,
                        source_kind=source_kind,
                        proposed_target=target,
                        final_target="list",
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
            else:
                # Reject list conversion if fewer than 2 items
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
                        status="rejected_invalid_target",
                        rejection_reason="Fewer than 2 lines/items for list materialization",
                        source_content_sha256=hash_before,
                    )
                )
                new_blocks.append(blk)
                continue

        # ------------------------------------------------------------------ #
        # 6. text -> table (only if table_html is available in evidence)      #
        # ------------------------------------------------------------------ #
        if isinstance(blk, Paragraph) and target == "table":
            if not ev.table_html_available or not ev.table_html:
                rejected_blk, audit = _reject_invalid(
                    blk, source_kind, "table", dec, hash_before,
                    reason="No table_html evidence exists for table materialization",
                )
                audits.append(audit)
                new_blocks.append(rejected_blk)
                continue
            else:
                new_tbl = Table(
                    id=blk.id,
                    sources=blk.sources,
                    html=ev.table_html,
                )
                new_blocks.append(new_tbl)
                audits.append(
                    SemanticAuditRecord(
                        decision_id=f"pass-b-{blk.id}",
                        block_id=blk.id,
                        source_kind=source_kind,
                        proposed_target="table",
                        final_target="table",
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

        # Default: keep original (target was allowed but no specific case handled it)
        new_blocks.append(blk)

    return new_blocks, audits
