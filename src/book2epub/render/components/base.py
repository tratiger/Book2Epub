"""Common constants, namespaces, and XML utilities for component renderers (M10)."""

import re

from lxml import etree

from book2epub.render.math import MATHML_NS

NS_XHTML = "http://www.w3.org/1999/xhtml"
NS_EPUB = "http://www.idpf.org/2007/ops"
NS_XML = "http://www.w3.org/XML/1998/namespace"

NSMAP = {
    None: NS_XHTML,
    "epub": NS_EPUB,
}

MAX_NESTING_DEPTH = 8
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
LANG_PATTERN = re.compile(r"[^a-z0-9_+-]+")


def slugify(text: str, max_len: int = 30) -> str:
    """Create a URL/ID-safe slug fragment from text."""
    s = SLUG_PATTERN.sub("-", text.lower()).strip("-")
    if not s:
        return "item"
    return s[:max_len].rstrip("-")


def append_text_node(parent: etree._Element, text: str) -> None:
    """Append text to an lxml element, properly placing it in text or last child tail."""
    if not text:
        return
    if len(parent) == 0:
        parent.text = (parent.text or "") + text
    else:
        parent[-1].tail = (parent[-1].tail or "") + text


def ensure_xhtml_namespace(element: etree._Element) -> None:
    """Ensure element and all its children have the XHTML namespace unless MathML."""
    tag_str = str(element.tag)
    if not tag_str.startswith("{"):
        element.tag = f"{{{NS_XHTML}}}{tag_str}"

    src = element.get("src")
    if src:
        if src.startswith("images/"):
            element.set("src", f"../{src}")
        elif (
            not src.startswith("../")
            and not src.startswith("http://")
            and not src.startswith("https://")
        ):
            element.set("src", f"../images/{src}")

    if (tag_str == "img" or tag_str.endswith("}img")) and "alt" not in element.attrib:
        element.set("alt", "")

    for child in element:
        child_tag = str(child.tag)
        if child_tag.startswith(f"{{{MATHML_NS}}}") or child_tag == f"{{{MATHML_NS}}}math":
            continue
        ensure_xhtml_namespace(child)
