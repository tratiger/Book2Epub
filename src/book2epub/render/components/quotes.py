"""BlockQuote component rendering for EPUB 3.3 (M10/Appendix L12)."""

from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.models import Block, BlockQuote, Inline
from book2epub.presentation.models import BookStyleProfile

from .base import MAX_NESTING_DEPTH, NS_XHTML


def render_blockquote(
    parent: etree._Element,
    block: BlockQuote,
    recursive_render_func: Callable[[etree._Element, Block, int], None],
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
    profile: BookStyleProfile | None = None,
    depth: int = 0,
) -> None:
    """Render a BlockQuote block to semantic <blockquote> structure."""
    if depth >= MAX_NESTING_DEPTH:
        return

    variant = profile.quote.variant if profile else "accent_left"
    quote_el = etree.SubElement(
        parent,
        f"{{{NS_XHTML}}}blockquote",
        attrib={"class": f"quote quote-{variant}"},
    )

    if hasattr(block, "blocks") and getattr(block, "blocks"):
        for child in block.blocks:
            recursive_render_func(quote_el, child, depth + 1)
    elif hasattr(block, "inlines") and getattr(block, "inlines"):
        p = etree.SubElement(quote_el, f"{{{NS_XHTML}}}p")
        render_inlines_func(p, block.inlines)

    if getattr(block, "attribution", None):
        footer = etree.SubElement(
            quote_el,
            f"{{{NS_XHTML}}}footer",
            attrib={"class": "quote-attribution"},
        )
        render_inlines_func(footer, block.attribution)
