"""
Semantic container components (ExampleBlock, ExerciseBlock, Footnote, Index)
(M10/Appendix L13).
"""

from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.models import (
    Block,
    ExampleBlock,
    ExerciseBlock,
    Footnote,
    IndexBlock,
    Inline,
    UnknownBlock,
)

from .base import MAX_NESTING_DEPTH, NS_EPUB, NS_XHTML


def render_example_block(
    parent: etree._Element,
    block: ExampleBlock,
    recursive_render_func: Callable[[etree._Element, Block, int], None],
    depth: int = 0,
) -> None:
    """Render an ExampleBlock container to semantic <section class="example">."""
    if depth >= MAX_NESTING_DEPTH:
        return

    sec = etree.SubElement(parent, f"{{{NS_XHTML}}}section", attrib={"class": "example"})
    for child in block.blocks:
        recursive_render_func(sec, child, depth + 1)


def render_exercise_block(
    parent: etree._Element,
    block: ExerciseBlock,
    recursive_render_func: Callable[[etree._Element, Block, int], None],
    depth: int = 0,
) -> None:
    """Render an ExerciseBlock container to semantic <section class="exercise">."""
    if depth >= MAX_NESTING_DEPTH:
        return

    sec = etree.SubElement(parent, f"{{{NS_XHTML}}}section", attrib={"class": "exercise"})
    for child in block.blocks:
        recursive_render_func(sec, child, depth + 1)


def render_footnote(
    parent: etree._Element,
    block: Footnote,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
) -> None:
    """Render a Footnote to semantic <aside epub:type="footnote">."""
    fn_id = f"fn-{block.id}"
    aside_el = etree.SubElement(
        parent,
        f"{{{NS_XHTML}}}aside",
        attrib={
            "id": fn_id,
            f"{{{NS_EPUB}}}type": "footnote",
            "class": "page-footnote footnote",
        },
    )
    p = etree.SubElement(aside_el, f"{{{NS_XHTML}}}p")
    render_inlines_func(p, block.inlines)


def render_index_block(
    parent: etree._Element,
    block: IndexBlock,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
) -> None:
    """Render an IndexBlock to semantic <section epub:type="index">."""
    sec = etree.SubElement(
        parent,
        f"{{{NS_XHTML}}}section",
        attrib={
            f"{{{NS_EPUB}}}type": "index",
            "class": "index",
        },
    )
    for item_inlines in block.items:
        p = etree.SubElement(sec, f"{{{NS_XHTML}}}p")
        render_inlines_func(p, item_inlines)


def render_unknown_block(
    parent: etree._Element,
    block: UnknownBlock,
) -> None:
    """Render an UnknownBlock safely as a fallback text div."""
    if block.extracted_text:
        div = etree.SubElement(parent, f"{{{NS_XHTML}}}div", attrib={"class": "unknown-block"})
        div.text = block.extracted_text
