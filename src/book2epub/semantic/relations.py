"""Semantic relationships between blocks: captions, footnotes,
continuations, and groups (M8 Section 12)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from book2epub.ir.models import Block, CodeBlock, Figure, Paragraph, PreformattedBlock, Table

RelationType = Literal[
    "caption_of",
    "footnote_of",
    "paragraph_continuation",
    "member_of_callout",
    "member_of_example",
]


class SemanticRelationDecision(BaseModel):
    """Semantic relation decision connecting multiple blocks."""

    model_config = ConfigDict(extra="forbid")

    relation_type: RelationType
    source_block_ids: list[str]
    target_block_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[str] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)


def validate_relation(
    rel: SemanticRelationDecision,
    blocks_by_id: dict[str, Block],
    block_order: dict[str, int],
) -> tuple[bool, str]:
    """
    Validate a relation decision against M8 Section 12 constraints.
    Returns (is_valid, error_reason).
    """
    # 1. All block IDs must exist
    for src_id in rel.source_block_ids:
        if src_id not in blocks_by_id:
            return False, f"Source block ID '{src_id}' does not exist"

    if rel.target_block_id and rel.target_block_id not in blocks_by_id:
        return False, f"Target block ID '{rel.target_block_id}' does not exist"

    # 2. Source order contiguity check for multi-block groups
    if len(rel.source_block_ids) > 1:
        order_indices = [block_order[sid] for sid in rel.source_block_ids]
        sorted_indices = sorted(order_indices)
        if order_indices != sorted_indices:
            return False, "Source block IDs are not in source order"
        for i in range(len(sorted_indices) - 1):
            if sorted_indices[i + 1] != sorted_indices[i] + 1:
                return False, "Source block IDs are not contiguous"

    # 3. Caption/footnote target validation
    if rel.relation_type in ("caption_of", "footnote_of"):
        if not rel.target_block_id:
            return False, f"{rel.relation_type} requires target_block_id"
        target_block = blocks_by_id[rel.target_block_id]
        if not isinstance(target_block, (Figure, Table, CodeBlock, PreformattedBlock)):
            return (
                False,
                f"Target block '{rel.target_block_id}' ({target_block.kind}) "
                f"cannot receive {rel.relation_type}",
            )

    # 4. Paragraph continuation requires Paragraph-compatible blocks
    if rel.relation_type == "paragraph_continuation":
        if not rel.target_block_id or len(rel.source_block_ids) != 1:
            return False, "paragraph_continuation requires exactly 1 source and 1 target"
        src_block = blocks_by_id[rel.source_block_ids[0]]
        tgt_block = blocks_by_id[rel.target_block_id]
        if not isinstance(src_block, Paragraph) or not isinstance(tgt_block, Paragraph):
            return False, "paragraph_continuation requires both source and target to be Paragraphs"

    return True, ""
