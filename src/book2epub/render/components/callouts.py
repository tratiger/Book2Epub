"""Callout and sidebar component rendering for EPUB 3.3 (M10/Appendix L8)."""

from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.models import Aside, Block, Callout, Inline

from .base import MAX_NESTING_DEPTH, NS_XHTML


def render_callout(
    parent: etree._Element,
    block: Callout,
    recursive_render_func: Callable[[etree._Element, Block, int], None],
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
    depth: int = 0,
) -> None:
    """Render a Callout block recursively into semantic <aside class="callout ...">."""
    if depth >= MAX_NESTING_DEPTH:
        return

    st = block.subtype or "note"
    aside_el = etree.SubElement(
        parent,
        f"{{{NS_XHTML}}}aside",
        attrib={"class": f"callout callout-{st}"},
    )

    if block.title:
        title_div = etree.SubElement(
            aside_el,
            f"{{{NS_XHTML}}}div",
            attrib={"class": "callout-title"},
        )
        render_inlines_func(title_div, block.title)

    for child_block in block.blocks:
        recursive_render_func(aside_el, child_block, depth + 1)


def render_aside(
    parent: etree._Element,
    block: Aside,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
) -> None:
    """Render an Aside block to semantic <aside class="aside ...">."""
    st = block.subtype or "sidebar"
    aside_el = etree.SubElement(
        parent,
        f"{{{NS_XHTML}}}aside",
        attrib={"class": f"aside aside-{st}"},
    )
    p = etree.SubElement(aside_el, f"{{{NS_XHTML}}}p")
    render_inlines_func(p, block.inlines)
