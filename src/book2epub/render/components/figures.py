"""Figure and chart component rendering for EPUB 3.3 (M10/Appendix L10)."""

from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.assets import AssetRegistry
from book2epub.ir.models import Chart, Figure, Inline, IRWarning, LayoutHint, Text
from book2epub.presentation.models import BookStyleProfile

from .base import NS_XHTML


def _get_layout_classes(hint: LayoutHint | None) -> str:
    """Derive responsive CSS classes from LayoutHint."""
    if not hint:
        return "size-large align-center"
    return f"size-{hint.size_class} align-{hint.alignment}"


def render_figure(
    parent: etree._Element,
    block: Figure | Chart,
    registry: AssetRegistry,
    warnings: list[IRWarning],
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
    profile: BookStyleProfile | None = None,
) -> None:
    """Render a Figure or Chart block to semantic XHTML <figure>."""
    cls_base = "figure" if isinstance(block, Figure) else "chart"
    layout_cls = _get_layout_classes(block.layout_hint)
    fig = etree.SubElement(
        parent,
        f"{{{NS_XHTML}}}figure",
        attrib={"class": f"{cls_base} {layout_cls}"},
    )

    asset = registry.get_asset(block.asset_id)
    img_src = f"../{asset.rel_path}" if asset else f"../images/{block.asset_id}"

    caption_text = "".join(i.text for i in block.caption if isinstance(i, Text)).strip()
    alt_text = caption_text if caption_text else ""
    if not alt_text:
        warnings.append(
            IRWarning(
                code="ACCESSIBILITY_EMPTY_ALT",
                message=f"{cls_base.capitalize()} {block.id} has empty alt text",
                page_idx=block.sources[0].page_idx if block.sources else None,
            )
        )

    caption_pos = profile.figure.caption_position if profile else "after"

    def emit_caption() -> None:
        if block.caption:
            fc = etree.SubElement(
                fig,
                f"{{{NS_XHTML}}}figcaption",
                attrib={"class": "figure-caption"},
            )
            render_inlines_func(fc, block.caption)

    def emit_img() -> None:
        etree.SubElement(
            fig,
            f"{{{NS_XHTML}}}img",
            attrib={"class": "figure-image", "src": img_src, "alt": alt_text},
        )

    if caption_pos == "before":
        emit_caption()
        emit_img()
    else:
        emit_img()
        emit_caption()

    if block.footnotes:
        fn_div = etree.SubElement(
            fig,
            f"{{{NS_XHTML}}}div",
            attrib={"class": "figure-note"},
        )
        render_inlines_func(fn_div, block.footnotes)
