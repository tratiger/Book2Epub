"""Pass A structural models and deterministic outline tree construction (Appendix H6 & J6-J8)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from book2epub.ir.models import Block, Heading

StructureEvidenceCode = Literal[
    "NUMBERING_PATTERN",
    "MINERU_TITLE_SIGNAL",
    "PRECEDING_SECTION_CONTEXT",
    "FOLLOWING_SECTION_CONTEXT",
    "CROSS_PAGE_SENTENCE_CONTINUITY",
    "TYPOGRAPHIC_GEOMETRY_SIGNAL",
    "BOOK_HIERARCHY_CONSISTENCY",
    "AMBIGUOUS",
]


class StructureDecision(BaseModel):
    """Pass A structural decision for heading or cross-page continuation."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    is_heading: bool | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    paragraph_continuation_of: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[StructureEvidenceCode] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)


class StructureDecisionBatch(BaseModel):
    """Batch of Pass A structural decisions returned by provider."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    chunk_id: str
    decisions: list[StructureDecision] = Field(default_factory=list)


class OutlineNode(BaseModel):
    """Individual node in the parallel BookOutline hierarchy."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    heading_block_id: str
    level: int = Field(ge=1, le=6)
    parent_node_id: str | None = None
    child_node_ids: list[str] = Field(default_factory=list)
    first_block_id: str
    last_block_id: str | None = None
    title: str = ""


class BookOutline(BaseModel):
    """Deterministic document-level outline tree referencing heading blocks."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    root_node_ids: list[str] = Field(default_factory=list)
    nodes: dict[str, OutlineNode] = Field(default_factory=dict)


class OutlineContextItem(BaseModel):
    """Compact outline entry for prompt context (Appendix J8)."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    level: int
    text_preview: str = Field(max_length=160)


def build_book_outline(blocks: list[Block]) -> BookOutline:
    """
    Construct a deterministic BookOutline from an ordered list of BookIR blocks
    following the tree rules in Appendix J7.
    """
    nodes: dict[str, OutlineNode] = {}
    root_ids: list[str] = []

    # Stack holds tuples of (node_id, level)
    stack: list[tuple[str, int]] = []
    seq = 0

    heading_indices: list[tuple[int, Heading]] = []
    for idx, blk in enumerate(blocks):
        if isinstance(blk, Heading):
            heading_indices.append((idx, blk))

    from book2epub.semantic.apply import extract_inlines_text

    for h_idx, (block_index, heading) in enumerate(heading_indices):
        seq += 1
        node_id = f"outline-{seq:04d}-{heading.id}"
        lvl_raw = heading.level if heading.level is not None else 1
        level = max(1, min(6, lvl_raw))

        # Pop stack while top of stack level >= current level
        while stack and stack[-1][1] >= level:
            stack.pop()

        parent_node_id: str | None = None
        if stack:
            parent_node_id = stack[-1][0]
            nodes[parent_node_id].child_node_ids.append(node_id)
        else:
            root_ids.append(node_id)

        # Determine last_block_id for this section:
        # immediately before next heading whose level <= current level, or final book block
        last_block_id: str | None = None
        for next_idx, next_heading in heading_indices[h_idx + 1 :]:
            next_lvl = next_heading.level if next_heading.level is not None else 1
            if next_lvl <= level:
                if next_idx > 0:
                    last_block_id = blocks[next_idx - 1].id
                break

        if last_block_id is None and blocks:
            last_block_id = blocks[-1].id

        title_text = extract_inlines_text(heading.inlines).strip()

        node = OutlineNode(
            node_id=node_id,
            heading_block_id=heading.id,
            level=level,
            parent_node_id=parent_node_id,
            child_node_ids=[],
            first_block_id=heading.id,
            last_block_id=last_block_id,
            title=title_text[:160],
        )
        nodes[node_id] = node
        stack.append((node_id, level))

    return BookOutline(
        schema_version="1.0",
        root_node_ids=root_ids,
        nodes=nodes,
    )


def get_outline_prompt_view(
    outline: BookOutline,
    current_block_id: str | None = None,
    max_items: int = 12,
) -> list[OutlineContextItem]:
    """
    Derive a compact preceding outline list (up to max_items) for prompt context
    as defined in Appendix J8.
    """
    items: list[OutlineContextItem] = []
    for node in outline.nodes.values():
        if current_block_id and node.heading_block_id == current_block_id:
            break
        items.append(
            OutlineContextItem(
                block_id=node.heading_block_id,
                level=node.level,
                text_preview=node.title[:160],
            )
        )
        if len(items) >= max_items:
            break

    return items
