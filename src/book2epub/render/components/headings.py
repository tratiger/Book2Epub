"""Heading component renderer for reflowable EPUB 3.3 (M10)."""

from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.models import Heading, Inline, IRWarning, Text
from book2epub.presentation.models import BookStyleProfile
from book2epub.render.models import TocEntry

from .base import NS_XHTML, slugify


def render_heading(
    parent: etree._Element,
    block: Heading,
    doc_href: str,
    heading_seq: int,
    used_ids: set[str],
    warnings: list[IRWarning],
    toc_entries: list[TocEntry],
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
    profile: BookStyleProfile | None = None,
    is_in_container: bool = False,
) -> int:
    """
    Render a Heading block to XHTML with semantic classes and record TOC entry.
    Returns the next heading_seq.
    """
    lvl = block.level if block.level is not None else 2
    lvl = max(1, min(6, lvl))
    tag = f"h{lvl}"

    plain_text = "".join(i.text for i in block.inlines if isinstance(i, Text)).strip()
    slug = slugify(plain_text)
    heading_id = f"h-{heading_seq}-{slug}"
    next_seq = heading_seq + 1

    while heading_id in used_ids:
        heading_id = f"h-{next_seq}-{slug}"
        next_seq += 1
    used_ids.add(heading_id)

    classes = [f"heading heading-{lvl}"]
    if block.level is None:
        classes.append("heading-fallback-level")
        warnings.append(
            IRWarning(
                code="HEADING_LEVEL_FALLBACK",
                message=f"Heading '{plain_text[:40]}' defaulted to h2",
                page_idx=block.sources[0].page_idx if block.sources else None,
            )
        )

    attribs = {
        "id": heading_id,
        "class": " ".join(classes),
    }

    h_el = etree.SubElement(parent, f"{{{NS_XHTML}}}{tag}", attrib=attribs)
    render_inlines_func(h_el, block.inlines)

    # Record in TOC if level 1..3 and not inside a container (M10 Section 12)
    if lvl <= 3 and not is_in_container:
        toc_entries.append(
            TocEntry(
                title=plain_text or "Section",
                href=f"{doc_href}#{heading_id}",
                level=lvl,
            )
        )

    return next_seq
