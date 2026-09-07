"""Deterministic document splitting for reflowable EPUB content documents."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from book2epub.ir.models import (
    Aside,
    Block,
    CodeBlock,
    DisplayMath,
    Footnote,
    Heading,
    ListBlock,
    PageBreak,
    Paragraph,
    Table,
    Text,
    UnknownBlock,
)

MAX_CHAR_THRESHOLD = 100_000
MAX_PAGE_SPAN = 50


@dataclass
class RenderSection:
    """A split section containing blocks destined for a single XHTML content document."""

    href: str  # e.g. "text/frontmatter.xhtml" or "text/part-0001.xhtml"
    doc_id: str  # e.g. "frontmatter" or "part-0001"
    blocks: list[Block] = field(default_factory=list)


def get_block_char_count(block: Block) -> int:
    """Estimate rendered text character count of a block."""
    if isinstance(block, (Paragraph, Heading)):
        return sum(len(i.text) for i in block.inlines if isinstance(i, Text))
    elif isinstance(block, CodeBlock):
        return len(block.text)
    elif isinstance(block, Table):
        return len(block.html)
    elif isinstance(block, DisplayMath):
        return len(block.latex)
    elif isinstance(block, ListBlock):
        count = 0
        for item_inlines in block.items:
            count += sum(len(i.text) for i in item_inlines if isinstance(i, Text))
        return count
    elif isinstance(block, Aside):
        return sum(len(i.text) for i in block.inlines if isinstance(i, Text))
    elif isinstance(block, Footnote):
        return sum(len(i.text) for i in block.inlines if isinstance(i, Text))
    elif isinstance(block, UnknownBlock):
        return len(block.extracted_text or "")
    return 0


def get_block_pages(block: Block) -> set[int]:
    """Get all source page indices associated with a block."""
    pages: set[int] = set()
    if isinstance(block, PageBreak):
        pages.add(block.page_idx)
    for src in block.sources:
        pages.add(src.page_idx)
    return pages


def calculate_page_span(pages: set[int]) -> int:
    """Calculate the source page span of a set of page indices."""
    if not pages:
        return 0
    return max(pages) - min(pages) + 1


def split_oversized_blocks(
    blocks: list[Block],
    max_chars: int = MAX_CHAR_THRESHOLD,
    max_pages: int = MAX_PAGE_SPAN,
) -> list[list[Block]]:
    """
    Recursively split a list of blocks if it exceeds max_chars or max_pages.

    - Splits before nearest preceding level-2 heading that keeps both sides non-empty.
    - If no suitable level-2 heading exists, splits at block boundary immediately
      before threshold is exceeded.
    - Never splits inside code, figure, table, math, list, or paragraph.
    """
    if len(blocks) <= 1:
        return [blocks]

    running_chars = 0
    running_pages: set[int] = set()
    split_point: int | None = None

    for i, block in enumerate(blocks):
        b_chars = get_block_char_count(block)
        b_pages = get_block_pages(block)

        # Check if adding this block exceeds threshold (and we already have at least 1 block)
        new_chars = running_chars + b_chars
        new_pages = running_pages | b_pages
        new_span = calculate_page_span(new_pages)

        if i > 0 and (new_chars > max_chars or new_span > max_pages):
            # Threshold exceeded. Search backwards for a suitable level-2 heading
            h2_index: int | None = None
            for k in range(i, 0, -1):
                cand = blocks[k]
                if isinstance(cand, Heading) and cand.level == 2:
                    h2_index = k
                    break

            if h2_index is not None and h2_index > 0:
                # If there is a PageBreak immediately preceding the h2, include it
                if h2_index > 0 and isinstance(blocks[h2_index - 1], PageBreak):
                    split_point = h2_index - 1
                else:
                    split_point = h2_index
            else:
                # Split immediately before this block
                if i > 0 and isinstance(blocks[i - 1], PageBreak):
                    split_point = i - 1
                else:
                    split_point = i
            break

        running_chars = new_chars
        running_pages = new_pages

    if split_point is None or split_point <= 0 or split_point >= len(blocks):
        return [blocks]

    left = blocks[:split_point]
    right = blocks[split_point:]

    # Recurse on both sides
    result: list[list[Block]] = []
    result.extend(split_oversized_blocks(left, max_chars, max_pages))
    result.extend(split_oversized_blocks(right, max_chars, max_pages))
    return result


def split_bookir_blocks(blocks: Sequence[Block]) -> list[RenderSection]:
    """
    Split normalized BookIR blocks into RenderSections according to M3 rules:

    1. Content before first level-1 heading -> text/frontmatter.xhtml if non-empty;
    2. Every level-1 heading starts a new content document;
    3. Document split if exceeding 100k chars or 50 source pages;
    4. Files named text/part-0001.xhtml, etc.
    """
    block_list = list(blocks)
    if not block_list:
        return [RenderSection(href="text/part-0001.xhtml", doc_id="part-0001", blocks=[])]

    # Find index of first level-1 heading
    first_h1_idx: int | None = None
    for i, b in enumerate(block_list):
        if isinstance(b, Heading) and b.level == 1:
            first_h1_idx = i
            break

    initial_groups: list[tuple[str | None, list[Block]]] = []

    if first_h1_idx is not None and first_h1_idx > 0:
        # Check if there is non-pagebreak content before first h1
        front_blocks = block_list[:first_h1_idx]
        has_content = any(not isinstance(b, PageBreak) for b in front_blocks)

        if has_content:
            # Check if last block in front_blocks is a PageBreak for the first h1
            # If so, keep it with the h1 instead
            if isinstance(front_blocks[-1], PageBreak):
                h1_pagebreak = front_blocks[-1]
                front_blocks = front_blocks[:-1]
                initial_groups.append(("frontmatter", front_blocks))
                remaining_blocks = [h1_pagebreak] + block_list[first_h1_idx:]
            else:
                initial_groups.append(("frontmatter", front_blocks))
                remaining_blocks = block_list[first_h1_idx:]
        else:
            # Only PageBreaks before first h1; include them in first chapter
            remaining_blocks = block_list
    else:
        remaining_blocks = block_list

    # Group remaining blocks by level-1 headings
    current_chapter: list[Block] = []
    for b in remaining_blocks:
        if isinstance(b, Heading) and b.level == 1:
            if current_chapter:
                if isinstance(current_chapter[-1], PageBreak):
                    pb = current_chapter.pop()
                    if current_chapter:
                        initial_groups.append((None, current_chapter))
                    current_chapter = [pb, b]
                else:
                    initial_groups.append((None, current_chapter))
                    current_chapter = [b]
            else:
                current_chapter = [b]
        else:
            current_chapter.append(b)

    if current_chapter:
        initial_groups.append((None, current_chapter))

    # Now apply threshold splitting (100k chars or 50 pages) and assign filenames
    final_sections: list[RenderSection] = []
    part_counter = 1

    for label, grp_blocks in initial_groups:
        split_chunks = split_oversized_blocks(grp_blocks)
        for chunk in split_chunks:
            if label == "frontmatter" and len(split_chunks) == 1:
                final_sections.append(
                    RenderSection(
                        href="text/frontmatter.xhtml",
                        doc_id="frontmatter",
                        blocks=chunk,
                    )
                )
            else:
                doc_id = f"part-{part_counter:04d}"
                href = f"text/{doc_id}.xhtml"
                final_sections.append(
                    RenderSection(
                        href=href,
                        doc_id=doc_id,
                        blocks=chunk,
                    )
                )
                part_counter += 1

    return final_sections
