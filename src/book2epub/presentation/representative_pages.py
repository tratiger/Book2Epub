"""
Deterministic selection of representative source pages for presentation style inference
(M10/Appendix L14).
"""

import logging
from collections.abc import Sequence

from book2epub.ir.models import (
    Aside,
    Block,
    BookIR,
    Callout,
    Chart,
    CodeBlock,
    Figure,
    Heading,
    ListBlock,
    Paragraph,
    PreformattedBlock,
    Table,
)

logger = logging.getLogger(__name__)


def _get_block_page(blk: Block) -> int | None:
    """Return primary page index of block if source evidence is present."""
    if blk.sources:
        return blk.sources[0].page_idx
    return None


def select_representative_pages(
    bookir: BookIR,
    max_pages: int = 8,
) -> list[int]:
    """
    Select up to `max_pages` (default 8) distinct source page indices
    representing diverse visual grammar structures for style inference.
    Follows deterministic 8-slot priority defined in M10 Section 4.
    """
    selected: list[int] = []
    seen: set[int] = set()

    def add_page(pidx: int | None) -> bool:
        if pidx is not None and pidx not in seen and 0 <= pidx < bookir.source.page_count:
            seen.add(pidx)
            selected.append(pidx)
            return True
        return False

    blocks: Sequence[Block] = bookir.blocks
    page_count = bookir.source.page_count

    # 1. First page containing level-1 heading
    for b in blocks:
        if isinstance(b, Heading) and b.level == 1:
            if add_page(_get_block_page(b)):
                break

    # 2. Page containing level-2 or level-3 heading
    for b in blocks:
        if isinstance(b, Heading) and b.level in (2, 3):
            if add_page(_get_block_page(b)):
                break

    # 3. Page containing source code
    for b in blocks:
        if isinstance(b, CodeBlock) or (
            isinstance(b, PreformattedBlock)
            and b.subtype in ("source_code", "generic_preformatted")
        ):
            if add_page(_get_block_page(b)):
                break

    # 4. Page containing terminal/preformatted content
    for b in blocks:
        if isinstance(b, PreformattedBlock) and b.subtype in (
            "terminal_output",
            "terminal_session",
            "shell_command",
            "repl_session",
            "log_output",
            "config_file",
        ):
            if add_page(_get_block_page(b)):
                break

    # 5. Page containing a table
    for b in blocks:
        if isinstance(b, Table):
            if add_page(_get_block_page(b)):
                break

    # 6. Page containing a figure/chart
    for b in blocks:
        if isinstance(b, (Figure, Chart)):
            if add_page(_get_block_page(b)):
                break

    # 7. Page containing list/callout/sidebar
    for b in blocks:
        if isinstance(b, (ListBlock, Callout, Aside)):
            if add_page(_get_block_page(b)):
                break

    # 8. Ordinary prose page near middle of book
    target_mid = page_count // 2
    best_prose_page: int | None = None
    min_dist = page_count + 1

    for b in blocks:
        if isinstance(b, Paragraph):
            p = _get_block_page(b)
            if p is not None and p not in seen:
                dist = abs(p - target_mid)
                if dist < min_dist:
                    min_dist = dist
                    best_prose_page = p

    if best_prose_page is not None:
        add_page(best_prose_page)

    # Fill remaining slots by evenly distributed pages across the book
    if len(selected) < max_pages and page_count > 0:
        step = max(1, page_count // max_pages)
        for cand in range(0, page_count, step):
            if len(selected) >= max_pages:
                break
            add_page(cand)

        # If still slots remaining, scan all pages
        if len(selected) < max_pages:
            for cand in range(page_count):
                if len(selected) >= max_pages:
                    break
                add_page(cand)

    selected.sort()
    return selected[:max_pages]
