"""List and definition list component rendering for EPUB 3.3 (M10/Appendix L11)."""

from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.models import DefinitionList, Inline, ListBlock
from book2epub.presentation.models import BookStyleProfile

from .base import NS_XHTML


def render_list(
    parent: etree._Element,
    block: ListBlock,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
    profile: BookStyleProfile | None = None,
) -> None:
    """Render a ListBlock to XHTML with support for dash markers and native styles."""
    is_dash = False
    if block.ordered is True:
        list_tag = "ol"
        l_attribs: dict[str, str] = {}
    elif block.ordered is False:
        list_tag = "ul"
        if profile and profile.list.unordered_marker == "dash":
            is_dash = True
            l_attribs = {"class": "list list-dash"}
        else:
            l_attribs = {"class": "list"}
    else:
        list_tag = "ul"
        l_attribs = {"class": "list list-marker-preserved"}

    list_el = etree.SubElement(parent, f"{{{NS_XHTML}}}{list_tag}", attrib=l_attribs)

    for item_inlines in block.items:
        li = etree.SubElement(list_el, f"{{{NS_XHTML}}}li")
        if is_dash:
            marker_span = etree.SubElement(
                li,
                f"{{{NS_XHTML}}}span",
                attrib={"class": "list-marker", "aria-hidden": "true"},
            )
            marker_span.text = "– "
            content_span = etree.SubElement(
                li,
                f"{{{NS_XHTML}}}span",
                attrib={"class": "list-content"},
            )
            render_inlines_func(content_span, item_inlines)
        else:
            render_inlines_func(li, item_inlines)


def render_definition_list(
    parent: etree._Element,
    block: DefinitionList,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
) -> None:
    """Render a DefinitionList block to semantic <dl><dt><dd> structure."""
    dl_el = etree.SubElement(parent, f"{{{NS_XHTML}}}dl", attrib={"class": "def-list"})

    for item in block.items:
        dt = etree.SubElement(dl_el, f"{{{NS_XHTML}}}dt")
        render_inlines_func(dt, item.term)

        for defn in item.definitions:
            dd = etree.SubElement(dl_el, f"{{{NS_XHTML}}}dd")
            render_inlines_func(dd, defn)
