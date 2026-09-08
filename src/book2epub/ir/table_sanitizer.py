"""Table HTML sanitizer enforcing strict XHTML safety and removing dangerous constructs."""

import logging
import re
from pathlib import Path

from lxml import html
from lxml.etree import tostring

from book2epub.ir.assets import AssetRegistry

logger = logging.getLogger(__name__)

ALLOWED_TAGS = {
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "colgroup",
    "col",
    "p",
    "span",
    "br",
    "img",
    "sup",
    "sub",
    "em",
    "strong",
    "b",
    "i",
}

CELL_ATTRIBUTES = {"rowspan", "colspan", "scope", "headers"}
IMG_ATTRIBUTES = {"src", "alt"}
ALLOWED_CLASSES = {
    "align-left",
    "align-center",
    "align-right",
    "table-cell",
    "math-inline",
    "math-display",
}


def sanitize_table_html(
    raw_html: str,
    asset_registry: AssetRegistry | None = None,
    base_dir: Path | None = None,
) -> str | None:
    """
    Sanitize MinerU table HTML into well-formed, XHTML-safe table markup.

    Returns the sanitized <table>...</table> string, or None if invalid.
    """
    if not raw_html or not raw_html.strip():
        return None

    # Handle <eq>...</eq> before or during parsing
    # Convert <eq>latex</eq> to <span class="math-inline" data-latex="latex"></span>
    def _eq_replacer(match: re.Match[str]) -> str:
        latex_content = match.group(1).strip()
        # Escape quotes in data-latex
        safe_latex = latex_content.replace('"', "&quot;")
        return f'<span class="math-inline" data-latex="{safe_latex}">{latex_content}</span>'

    preprocessed_html = re.sub(r"<eq>(.*?)</eq>", _eq_replacer, raw_html, flags=re.DOTALL)

    try:
        # Parse fragment
        fragment = html.fragment_fromstring(preprocessed_html, create_parent=True)
    except Exception as e:
        logger.warning("Failed to parse table HTML fragment: %e", e)
        return None

    # Locate table element
    tables = fragment.xpath(".//table")
    if not tables:
        logger.warning("No <table> element found in table HTML.")
        return None
    table_elem = tables[0]

    # Clean nodes recursively
    for elem in list(table_elem.iter()):
        tag = elem.tag.lower()
        if tag not in ALLOWED_TAGS:
            # If element is not allowed, drop tag but retain children/text
            parent = elem.getparent()
            if parent is not None:
                if elem.text:
                    prev = elem.getprevious()
                    if prev is not None:
                        prev.tail = (prev.tail or "") + elem.text
                    else:
                        parent.text = (parent.text or "") + elem.text
                for child in elem:
                    parent.append(child)
                parent.remove(elem)
            continue

        # Filter attributes
        attribs = dict(elem.attrib)
        for attr, val in attribs.items():
            attr_lower = attr.lower()

            # Remove event handlers and style
            if attr_lower.startswith("on") or attr_lower == "style":
                del elem.attrib[attr]
                continue

            # Tag specific attributes
            if tag in ("th", "td"):
                if attr_lower in CELL_ATTRIBUTES:
                    continue
            elif tag == "img":
                if attr_lower == "src":
                    # Reject remote URLs
                    if val.startswith("http://") or val.startswith("https://"):
                        logger.warning("Rejected remote table image src: %s", val)
                        del elem.attrib[attr]
                        continue
                    # Register local asset if registry provided
                    if asset_registry and base_dir:
                        local_img_path = base_dir / val
                        if not local_img_path.is_file() and (base_dir / "images" / val).is_file():
                            local_img_path = base_dir / "images" / val
                        if local_img_path.is_file():
                            asset_id = asset_registry.register_asset(local_img_path, role="figure")
                            elem.attrib["data-asset-id"] = asset_id
                    continue
                elif attr_lower == "alt":
                    continue
            elif tag == "span" and attr_lower == "data-latex":
                continue

            # Class attribute
            if attr_lower == "class":
                classes = [c for c in val.split() if c in ALLOWED_CLASSES]
                if classes:
                    elem.attrib["class"] = " ".join(classes)
                else:
                    del elem.attrib[attr]
                continue

            # Drop other attributes (e.g. random id, bgcolor, width)
            del elem.attrib[attr]

    try:
        sanitized_xml = tostring(table_elem, encoding="unicode", method="xml")
        return sanitized_xml
    except Exception as e:
        logger.warning("Failed to serialize sanitized table to XML: %e", e)
        return None
