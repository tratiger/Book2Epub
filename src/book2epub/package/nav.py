"""EPUB 3.3 nav.xhtml (Navigation Document) generator."""

from collections.abc import Sequence

from lxml import etree

from book2epub.render.models import PageMapEntry, TocEntry

NS_XHTML = "http://www.w3.org/1999/xhtml"
NS_EPUB = "http://www.idpf.org/2007/ops"
NS_XML = "http://www.w3.org/XML/1998/namespace"

NSMAP = {
    None: NS_XHTML,
    "epub": NS_EPUB,
}


def _render_toc_list(parent_ol: etree._Element, entries: Sequence[TocEntry]) -> None:
    """Render nested TOC list strictly conforming to EPUB nav requirements."""
    for entry in entries:
        li = etree.SubElement(parent_ol, f"{{{NS_XHTML}}}li")
        a = etree.SubElement(li, f"{{{NS_XHTML}}}a", attrib={"href": entry.href})
        a.text = entry.title

        if entry.children:
            child_ol = etree.SubElement(li, f"{{{NS_XHTML}}}ol")
            _render_toc_list(child_ol, entry.children)


def generate_nav_xhtml(
    title: str,
    language: str,
    toc_entries: Sequence[TocEntry],
    page_map_entries: Sequence[PageMapEntry],
    first_doc_href: str,
) -> bytes:
    """
    Generate XML-serialized nav.xhtml document with:
    - TOC nav
    - page-list nav
    - landmarks nav
    """
    root = etree.Element(
        f"{{{NS_XHTML}}}html",
        nsmap=NSMAP,
        attrib={
            f"{{{NS_XML}}}lang": language,
            "lang": language,
        },
    )

    head = etree.SubElement(root, f"{{{NS_XHTML}}}head")
    doc_title = etree.SubElement(head, f"{{{NS_XHTML}}}title")
    doc_title.text = f"Navigation - {title}"

    etree.SubElement(
        head,
        f"{{{NS_XHTML}}}link",
        attrib={
            "rel": "stylesheet",
            "type": "text/css",
            "href": "styles/book.css",
        },
    )

    body = etree.SubElement(root, f"{{{NS_XHTML}}}body")

    # 1. TOC Nav
    toc_nav = etree.SubElement(
        body,
        f"{{{NS_XHTML}}}nav",
        attrib={
            f"{{{NS_EPUB}}}type": "toc",
            "id": "toc",
            "role": "doc-toc",
        },
    )
    toc_h = etree.SubElement(toc_nav, f"{{{NS_XHTML}}}h2")
    toc_h.text = "Table of Contents"

    toc_ol = etree.SubElement(toc_nav, f"{{{NS_XHTML}}}ol")
    _render_toc_list(toc_ol, toc_entries)

    # 2. Page-list Nav
    if page_map_entries:
        page_nav = etree.SubElement(
            body,
            f"{{{NS_XHTML}}}nav",
            attrib={
                f"{{{NS_EPUB}}}type": "page-list",
                "id": "page-list",
                "role": "doc-pagelist",
                "aria-label": "Pages",
            },
        )
        page_h = etree.SubElement(page_nav, f"{{{NS_XHTML}}}h2")
        page_h.text = "Pages"

        page_ol = etree.SubElement(page_nav, f"{{{NS_XHTML}}}ol")
        for p in page_map_entries:
            li = etree.SubElement(page_ol, f"{{{NS_XHTML}}}li")
            target_href = f"{p.xhtml_path}#{p.fragment_id}"
            a = etree.SubElement(li, f"{{{NS_XHTML}}}a", attrib={"href": target_href})
            a.text = p.label

    # 3. Landmarks Nav
    landmarks_nav = etree.SubElement(
        body,
        f"{{{NS_XHTML}}}nav",
        attrib={
            f"{{{NS_EPUB}}}type": "landmarks",
            "id": "landmarks",
            "hidden": "hidden",
        },
    )
    lm_h = etree.SubElement(landmarks_nav, f"{{{NS_XHTML}}}h2")
    lm_h.text = "Landmarks"

    lm_ol = etree.SubElement(landmarks_nav, f"{{{NS_XHTML}}}ol")
    lm_li = etree.SubElement(lm_ol, f"{{{NS_XHTML}}}li")
    lm_a = etree.SubElement(
        lm_li,
        f"{{{NS_XHTML}}}a",
        attrib={
            f"{{{NS_EPUB}}}type": "bodymatter",
            "href": first_doc_href,
        },
    )
    lm_a.text = "Start of Content"

    return etree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=True,
    )
