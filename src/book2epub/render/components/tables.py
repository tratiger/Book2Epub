"""Table component rendering for EPUB 3.3 (M10/Appendix L9)."""

import logging
from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.assets import AssetRegistry
from book2epub.ir.models import Inline, LayoutHint, Table

from .base import NS_XHTML, ensure_xhtml_namespace

logger = logging.getLogger(__name__)


def _get_layout_classes(hint: LayoutHint | None) -> str:
    """Derive responsive CSS classes from LayoutHint."""
    if not hint:
        return "size-large align-center"
    return f"size-{hint.size_class} align-{hint.alignment}"


def render_table(
    parent: etree._Element,
    block: Table,
    registry: AssetRegistry,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
) -> None:
    """Render a Table block to semantic XHTML structure within a table-wrap figure."""
    layout_cls = _get_layout_classes(block.layout_hint)
    fig = etree.SubElement(
        parent,
        f"{{{NS_XHTML}}}figure",
        attrib={"class": f"table-figure {layout_cls}"},
    )

    if block.caption:
        fc = etree.SubElement(fig, f"{{{NS_XHTML}}}figcaption")
        render_inlines_func(fc, block.caption)

    wrap = etree.SubElement(fig, f"{{{NS_XHTML}}}div", attrib={"class": "table-wrap"})

    if block.html and "<table" in block.html:
        try:
            table_el = etree.fromstring(block.html.encode("utf-8"))
            ensure_xhtml_namespace(table_el)
            wrap.append(table_el)
        except Exception as exc:
            logger.warning("Failed to parse table XML: %s", exc)
            if block.fallback_asset_id:
                asset = registry.get_asset(block.fallback_asset_id)
                if asset:
                    etree.SubElement(
                        wrap,
                        f"{{{NS_XHTML}}}img",
                        attrib={
                            "src": f"../{asset.rel_path}",
                            "alt": "Table image fallback",
                        },
                    )
    elif block.fallback_asset_id:
        asset = registry.get_asset(block.fallback_asset_id)
        if asset:
            etree.SubElement(
                wrap,
                f"{{{NS_XHTML}}}img",
                attrib={
                    "src": f"../{asset.rel_path}",
                    "alt": "Table image fallback",
                },
            )

    if block.footnotes:
        fn_div = etree.SubElement(
            fig,
            f"{{{NS_XHTML}}}div",
            attrib={"class": "table-note"},
        )
        render_inlines_func(fn_div, block.footnotes)
