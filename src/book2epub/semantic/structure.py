"""Pass A structural models and deterministic outline tree construction (Appendix H6 & J6-J8)."""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

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
    decisions: list[StructureDecision] = Field(default_factory=list, max_length=256)


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
    _block_order: list[str] = PrivateAttr(default_factory=list)


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

    result = BookOutline(
        schema_version="1.0",
        root_node_ids=root_ids,
        nodes=nodes,
    )
    result._block_order = [block.id for block in blocks]
    return result


def get_outline_prompt_view(
    outline: BookOutline,
    current_block_id: str | None = None,
    max_items: int = 12,
    ordered_block_ids: Sequence[str] | None = None,
) -> list[OutlineContextItem]:
    """
    Derive a compact outline list (up to max_items) for prompt context (Appendix J8).

    Returns: ancestor chain of current block + bounded nearby sibling headings.
    Works even when current_block_id is a non-heading block (paragraph etc.) — finds
    the nearest preceding heading node and uses its ancestor chain.

    This prevents front-of-book bias in long documents (e.g. 100-page books where
    chunk 20 should not see Chapter 1 headings as primary context).
    """
    if not current_block_id or not outline.nodes:
        # No context available: return up to max_items from the beginning
        items: list[OutlineContextItem] = []
        for node in outline.nodes.values():
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

    if ordered_block_ids is None:
        ordered_block_ids = outline._block_order or None

    # Build ordered node list (insertion order = document order)
    ordered_nodes = list(outline.nodes.values())

    # Build block_id → node index map for heading blocks
    heading_id_to_idx: dict[str, int] = {
        node.heading_block_id: i for i, node in enumerate(ordered_nodes)
    }

    # Find the nearest preceding heading node for current_block_id.  Chunking has
    # the complete draft order, so use it when available; block IDs are opaque and
    # must not be sorted lexicographically as a proxy for document position.
    current_node_idx: int | None = heading_id_to_idx.get(current_block_id)
    if current_node_idx is None:
        if ordered_block_ids is not None:
            order = {block_id: i for i, block_id in enumerate(ordered_block_ids)}
            current_order = order.get(current_block_id)
            if current_order is not None:
                preceding = [
                    (i, order[node.heading_block_id])
                    for i, node in enumerate(ordered_nodes)
                    if node.heading_block_id in order
                    and order[node.heading_block_id] <= current_order
                ]
                if preceding:
                    current_node_idx = max(preceding, key=lambda pair: pair[1])[0]
        else:
            # Backwards-compatible fallback for callers that only have an outline.
            # Section endpoints are preferred; lexical comparison is only the last
            # resort for legacy synthetic IDs.
            endpoint_matches = [
                i
                for i, node in enumerate(ordered_nodes)
                if current_block_id in (node.first_block_id, node.last_block_id)
            ]
            current_node_idx = endpoint_matches[-1] if endpoint_matches else None
            if current_node_idx is None:
                best_idx = None
                for i, node in enumerate(ordered_nodes):
                    if node.heading_block_id <= current_block_id:
                        best_idx = i
                    else:
                        break
                current_node_idx = best_idx

    if current_node_idx is None:
        # current block is before all headings — return first max_items
        items = []
        for node in ordered_nodes[:max_items]:
            items.append(
                OutlineContextItem(
                    block_id=node.heading_block_id,
                    level=node.level,
                    text_preview=node.title[:160],
                )
            )
        return items

    current_node = ordered_nodes[current_node_idx]

    # Build ancestor chain (current → parent → grandparent → ... → root)
    ancestors: list[OutlineNode] = []
    ancestor_node_ids: set[str] = set()
    cursor_node = current_node
    while True:
        if cursor_node.node_id in ancestor_node_ids:
            break  # cycle guard
        ancestors.append(cursor_node)
        ancestor_node_ids.add(cursor_node.node_id)
        if cursor_node.parent_node_id and cursor_node.parent_node_id in outline.nodes:
            cursor_node = outline.nodes[cursor_node.parent_node_id]
        else:
            break
    # Reverse so root ancestor is first
    ancestors.reverse()

    result: list[OutlineContextItem] = []
    seen_node_ids: set[str] = set()

    def _add(node: OutlineNode) -> None:
        if node.node_id not in seen_node_ids and len(result) < max_items:
            seen_node_ids.add(node.node_id)
            result.append(
                OutlineContextItem(
                    block_id=node.heading_block_id,
                    level=node.level,
                    text_preview=node.title[:160],
                )
            )

    # 1. Ancestor chain (includes current)
    for anc in ancestors:
        _add(anc)

    # 2. Preceding siblings at current level (up to 3, nearest first)
    sibling_budget = min(3, max_items - len(result))
    if sibling_budget > 0:
        preceding_siblings: list[OutlineNode] = []
        for i in range(current_node_idx - 1, -1, -1):
            node = ordered_nodes[i]
            if node.node_id in seen_node_ids:
                continue
            if node.level == current_node.level:
                preceding_siblings.append(node)
                if len(preceding_siblings) >= sibling_budget:
                    break
            elif node.level < current_node.level:
                break  # hit parent level — stop
        for sib in reversed(preceding_siblings):
            _add(sib)

    # 3. Following sibling headings (up to 2, for future context)
    following_budget = min(2, max_items - len(result))
    if following_budget > 0:
        following_count = 0
        for i in range(current_node_idx + 1, len(ordered_nodes)):
            if following_count >= following_budget:
                break
            node = ordered_nodes[i]
            if node.node_id in seen_node_ids:
                continue
            if (
                node.parent_node_id == current_node.parent_node_id
                and node.level == current_node.level
            ):
                _add(node)
                following_count += 1

    return result
