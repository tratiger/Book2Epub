"""Prose paragraphs and inline element rendering for EPUB 3.3 (M10)."""

from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.assets import AssetRegistry
from book2epub.ir.models import (
    Hyperlink,
    Inline,
    InlineMath,
    IRWarning,
    LineBreak,
    PageBoundary,
    Paragraph,
    Text,
)
from book2epub.render.math import convert_latex_to_mathml

from .base import NS_XHTML, append_text_node


def render_inlines(
    parent: etree._Element,
    inlines: Sequence[Inline],
    registry: AssetRegistry,
    warnings: list[IRWarning],
    pagebreak_renderer: Callable[[int, str], etree._Element],
    mark_mathml: Callable[[], None],
) -> None:
    """Render sequence of inline elements into parent element."""
    for inl in inlines:
        if isinstance(inl, Text):
            append_text_node(parent, inl.text)

        elif isinstance(inl, Hyperlink):
            a = etree.SubElement(parent, f"{{{NS_XHTML}}}a", attrib={"href": inl.url})
            render_inlines(a, inl.children, registry, warnings, pagebreak_renderer, mark_mathml)

        elif isinstance(inl, PageBoundary):
            lbl = inl.label or f"scan-{inl.page_idx + 1}"
            pb_span = pagebreak_renderer(inl.page_idx, lbl)
            parent.append(pb_span)

        elif isinstance(inl, InlineMath):
            res = convert_latex_to_mathml(inl.latex, display_block=False)
            if res.success and res.mathml_element is not None:
                parent.append(res.mathml_element)
                mark_mathml()
            else:
                if inl.fallback_asset_id:
                    asset = registry.get_asset(inl.fallback_asset_id)
                    if asset:
                        etree.SubElement(
                            parent,
                            f"{{{NS_XHTML}}}img",
                            attrib={
                                "class": "math-fallback",
                                "src": f"../{asset.rel_path}",
                                "alt": res.fallback_latex,
                            },
                        )
                    else:
                        code_fb = etree.SubElement(
                            parent,
                            f"{{{NS_XHTML}}}code",
                            attrib={"class": "math-unconverted"},
                        )
                        code_fb.text = res.fallback_latex
                else:
                    code_fb = etree.SubElement(
                        parent,
                        f"{{{NS_XHTML}}}code",
                        attrib={"class": "math-unconverted"},
                    )
                    code_fb.text = res.fallback_latex
                    warnings.append(
                        IRWarning(
                            code="MATH_UNCONVERTED",
                            message=(
                                f"Inline LaTeX could not be converted: {res.fallback_latex[:30]}"
                            ),
                        )
                    )

        elif isinstance(inl, LineBreak):
            etree.SubElement(parent, f"{{{NS_XHTML}}}br")


def render_paragraph(
    parent: etree._Element,
    block: Paragraph,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
) -> etree._Element:
    """Render a Paragraph block to XHTML."""
    p = etree.SubElement(parent, f"{{{NS_XHTML}}}p")
    render_inlines_func(p, block.inlines)
    return p
