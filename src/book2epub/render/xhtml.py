"""XHTML 5 content document renderer for reflowable EPUB 3.3."""

import logging
import re
from collections.abc import Sequence

from lxml import etree

from book2epub.ir.assets import AssetRegistry
from book2epub.ir.models import (
    Aside,
    Block,
    BlockQuote,
    Callout,
    Chart,
    CodeBlock,
    DefinitionList,
    DisplayMath,
    ExampleBlock,
    ExerciseBlock,
    Figure,
    Footnote,
    Heading,
    Hyperlink,
    IndexBlock,
    Inline,
    InlineMath,
    IRWarning,
    LayoutHint,
    LineBreak,
    ListBlock,
    PageBoundary,
    PageBreak,
    Paragraph,
    PreformattedBlock,
    Table,
    Text,
    UnknownBlock,
)
from book2epub.render.math import MATHML_NS, convert_latex_to_mathml
from book2epub.render.models import PageMapEntry, TocEntry

logger = logging.getLogger(__name__)

NS_XHTML = "http://www.w3.org/1999/xhtml"
NS_EPUB = "http://www.idpf.org/2007/ops"
NS_XML = "http://www.w3.org/XML/1998/namespace"

NSMAP = {
    None: NS_XHTML,
    "epub": NS_EPUB,
}

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

    # If element is img or has src attribute, ensure relative path is relative to OEBPS/text/
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

    # Ensure alt attribute on img elements for HTML5/EPUB compliance
    if (tag_str == "img" or tag_str.endswith("}img")) and "alt" not in element.attrib:
        element.set("alt", "")

    for child in element:
        # Do not override MathML namespace
        child_tag = str(child.tag)
        if child_tag.startswith(f"{{{MATHML_NS}}}") or child_tag == f"{{{MATHML_NS}}}math":
            continue
        ensure_xhtml_namespace(child)


class DocumentRenderer:
    """Renders a sequence of BookIR blocks into an XHTML content document."""

    def __init__(
        self,
        doc_href: str,
        doc_id: str,
        title: str,
        language: str,
        registry: AssetRegistry,
        global_heading_seq: int = 1,
        page_label_confidence_map: dict[int, str] | None = None,
    ) -> None:
        self.doc_href = doc_href
        self.doc_id = doc_id
        self.title = title
        self.language = language
        self.registry = registry
        self.heading_seq = global_heading_seq
        self.page_label_conf_map = page_label_confidence_map or {}

        self.contains_mathml = False
        self.page_map_entries: list[PageMapEntry] = []
        self.toc_entries: list[TocEntry] = []
        self.warnings: list[IRWarning] = []
        self.used_ids: set[str] = set()

        # Build root document
        self.root = etree.Element(
            f"{{{NS_XHTML}}}html",
            nsmap=NSMAP,
            attrib={
                f"{{{NS_XML}}}lang": self.language,
                "lang": self.language,
            },
        )
        self.head = etree.SubElement(self.root, f"{{{NS_XHTML}}}head")
        doc_title_el = etree.SubElement(self.head, f"{{{NS_XHTML}}}title")
        doc_title_el.text = self.title

        # Stylesheet link
        etree.SubElement(
            self.head,
            f"{{{NS_XHTML}}}link",
            attrib={
                "rel": "stylesheet",
                "type": "text/css",
                "href": "../styles/book.css",
            },
        )

        self.body = etree.SubElement(self.root, f"{{{NS_XHTML}}}body")

    def _generate_pagebreak_id(self, pidx: int, label: str) -> tuple[str, str]:
        """Generate XML-safe unique ID and label for a pagebreak."""
        is_scan = label.startswith("scan-")
        clean_lbl = re.sub(r"[^a-zA-Z0-9_-]", "-", label).strip("-") or str(pidx + 1)
        if is_scan:
            base_id = f"scan-page-{pidx + 1:06d}"
        else:
            base_id = f"page-{clean_lbl}"

        candidate_id = base_id
        counter = 1
        while candidate_id in self.used_ids:
            counter += 1
            candidate_id = f"{base_id}-{counter}"

        self.used_ids.add(candidate_id)
        return candidate_id, label

    def _render_pagebreak_element(self, pidx: int, label: str) -> etree._Element:
        """Create a standard EPUB 3.3 pagebreak span element and record in PageMap."""
        frag_id, display_label = self._generate_pagebreak_id(pidx, label)
        span = etree.Element(
            f"{{{NS_XHTML}}}span",
            attrib={
                "id": frag_id,
                f"{{{NS_EPUB}}}type": "pagebreak",
                "role": "doc-pagebreak",
                "aria-label": display_label,
            },
        )
        conf = self.page_label_conf_map.get(pidx, "low")
        self.page_map_entries.append(
            PageMapEntry(
                page_idx=pidx,
                label=display_label,
                xhtml_path=self.doc_href,
                fragment_id=frag_id,
                printed_label_confidence=conf,
            )
        )
        return span

    def _render_inlines(self, parent: etree._Element, inlines: Sequence[Inline]) -> None:
        """Render inline elements into parent element."""
        for inl in inlines:
            if isinstance(inl, Text):
                append_text_node(parent, inl.text)

            elif isinstance(inl, Hyperlink):
                a = etree.SubElement(parent, f"{{{NS_XHTML}}}a", attrib={"href": inl.url})
                self._render_inlines(a, inl.children)

            elif isinstance(inl, PageBoundary):
                lbl = inl.label or f"scan-{inl.page_idx + 1}"
                pb_span = self._render_pagebreak_element(inl.page_idx, lbl)
                parent.append(pb_span)

            elif isinstance(inl, InlineMath):
                res = convert_latex_to_mathml(inl.latex, display_block=False)
                if res.success and res.mathml_element is not None:
                    parent.append(res.mathml_element)
                    self.contains_mathml = True
                else:
                    # Fallback
                    if inl.fallback_asset_id:
                        asset = self.registry.get_asset(inl.fallback_asset_id)
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
                        self.warnings.append(
                            IRWarning(
                                code="MATH_UNCONVERTED",
                                message=(
                                    "Inline LaTeX could not be converted: "
                                    f"{res.fallback_latex[:30]}"
                                ),
                            )
                        )

            elif isinstance(inl, LineBreak):
                etree.SubElement(parent, f"{{{NS_XHTML}}}br")

    def _get_layout_classes(self, hint: LayoutHint | None) -> str:
        """Derive responsive CSS classes from LayoutHint."""
        if not hint:
            return "size-large align-center"
        s_cls = f"size-{hint.size_class}"
        a_cls = f"align-{hint.alignment}"
        return f"{s_cls} {a_cls}"

    def render_block(self, block: Block) -> None:
        """Render a single BookIR Block into document body."""
        self.render_block_into(self.body, block)

    def render_block_into(self, parent: etree._Element, block: Block) -> None:
        """Render a single BookIR Block into the given parent element."""
        if isinstance(block, PageBreak):
            lbl = block.label or f"scan-{block.page_idx + 1}"
            span = self._render_pagebreak_element(block.page_idx, lbl)
            parent.append(span)

        elif isinstance(block, Heading):
            lvl = block.level if block.level is not None else 2
            lvl = max(1, min(6, lvl))
            tag = f"h{lvl}"

            plain_text = "".join(i.text for i in block.inlines if isinstance(i, Text)).strip()
            slug = slugify(plain_text)
            heading_id = f"h-{self.heading_seq}-{slug}"
            self.heading_seq += 1
            self.used_ids.add(heading_id)

            attribs: dict[str, str] = {"id": heading_id}
            if block.level is None:
                attribs["class"] = "heading-fallback-level"
                self.warnings.append(
                    IRWarning(
                        code="HEADING_LEVEL_FALLBACK",
                        message=f"Heading '{plain_text[:40]}' defaulted to h2",
                        page_idx=block.sources[0].page_idx if block.sources else None,
                    )
                )

            h_el = etree.SubElement(parent, f"{{{NS_XHTML}}}{tag}", attrib=attribs)
            self._render_inlines(h_el, block.inlines)

            # Record in TOC if level 1..3
            if lvl <= 3:
                self.toc_entries.append(
                    TocEntry(
                        title=plain_text or "Section",
                        href=f"{self.doc_href}#{heading_id}",
                        level=lvl,
                    )
                )

        elif isinstance(block, Paragraph):
            p = etree.SubElement(parent, f"{{{NS_XHTML}}}p")
            self._render_inlines(p, block.inlines)

        elif isinstance(block, DisplayMath):
            div = etree.SubElement(
                parent,
                f"{{{NS_XHTML}}}div",
                attrib={"class": "math display"},
            )
            res = convert_latex_to_mathml(block.latex, display_block=True)
            if res.success and res.mathml_element is not None:
                div.append(res.mathml_element)
                self.contains_mathml = True
            else:
                if block.fallback_asset_id:
                    asset = self.registry.get_asset(block.fallback_asset_id)
                    if asset:
                        etree.SubElement(
                            div,
                            f"{{{NS_XHTML}}}img",
                            attrib={
                                "class": "math-fallback",
                                "src": f"../{asset.rel_path}",
                                "alt": res.fallback_latex,
                            },
                        )
                    else:
                        code_el = etree.SubElement(
                            div,
                            f"{{{NS_XHTML}}}code",
                            attrib={"class": "math-unconverted"},
                        )
                        code_el.text = res.fallback_latex
                else:
                    code_el = etree.SubElement(
                        div,
                        f"{{{NS_XHTML}}}code",
                        attrib={"class": "math-unconverted"},
                    )
                    code_el.text = res.fallback_latex
                    self.warnings.append(
                        IRWarning(
                            code="MATH_UNCONVERTED",
                            message=(
                                f"Display LaTeX could not be converted: {res.fallback_latex[:40]}"
                            ),
                            page_idx=block.sources[0].page_idx if block.sources else None,
                        )
                    )

        elif isinstance(block, CodeBlock):
            lang_attr = ""
            if block.language:
                clean_lang = LANG_PATTERN.sub("", block.language.lower())
                if clean_lang:
                    lang_attr = f"language-{clean_lang}"

            has_caption = bool(block.caption)
            has_footnotes = bool(block.footnotes)

            if has_caption or has_footnotes:
                fig = etree.SubElement(
                    parent,
                    f"{{{NS_XHTML}}}figure",
                    attrib={"class": "code-listing"},
                )
                if has_caption:
                    fc = etree.SubElement(fig, f"{{{NS_XHTML}}}figcaption")
                    self._render_inlines(fc, block.caption)

                pre = etree.SubElement(fig, f"{{{NS_XHTML}}}pre")
                c_attribs = {"class": lang_attr} if lang_attr else {}
                code_el = etree.SubElement(pre, f"{{{NS_XHTML}}}code", attrib=c_attribs)
                code_el.text = block.text

                if has_footnotes:
                    fn_div = etree.SubElement(
                        fig,
                        f"{{{NS_XHTML}}}div",
                        attrib={"class": "code-note"},
                    )
                    self._render_inlines(fn_div, block.footnotes)
            else:
                pre = etree.SubElement(parent, f"{{{NS_XHTML}}}pre")
                c_attribs = {"class": lang_attr} if lang_attr else {}
                code_el = etree.SubElement(pre, f"{{{NS_XHTML}}}code", attrib=c_attribs)
                code_el.text = block.text

        elif isinstance(block, (Figure, Chart)):
            cls_base = "figure" if isinstance(block, Figure) else "chart"
            layout_cls = self._get_layout_classes(block.layout_hint)
            fig = etree.SubElement(
                parent,
                f"{{{NS_XHTML}}}figure",
                attrib={"class": f"{cls_base} {layout_cls}"},
            )

            asset = self.registry.get_asset(block.asset_id)
            img_src = f"../{asset.rel_path}" if asset else f"../images/{block.asset_id}"

            # Alt text: descriptive caption or empty
            caption_text = "".join(i.text for i in block.caption if isinstance(i, Text)).strip()
            alt_text = caption_text if caption_text else ""
            if not alt_text:
                self.warnings.append(
                    IRWarning(
                        code="ACCESSIBILITY_EMPTY_ALT",
                        message=f"{cls_base.capitalize()} {block.id} has empty alt text",
                        page_idx=block.sources[0].page_idx if block.sources else None,
                    )
                )

            if block.caption:
                fc = etree.SubElement(fig, f"{{{NS_XHTML}}}figcaption")
                self._render_inlines(fc, block.caption)

            etree.SubElement(
                fig,
                f"{{{NS_XHTML}}}img",
                attrib={"src": img_src, "alt": alt_text},
            )

            if block.footnotes:
                fn_div = etree.SubElement(
                    fig,
                    f"{{{NS_XHTML}}}div",
                    attrib={"class": "figure-note"},
                )
                self._render_inlines(fn_div, block.footnotes)

        elif isinstance(block, Table):
            layout_cls = self._get_layout_classes(block.layout_hint)
            fig = etree.SubElement(
                parent,
                f"{{{NS_XHTML}}}figure",
                attrib={"class": f"table-figure {layout_cls}"},
            )

            if block.caption:
                fc = etree.SubElement(fig, f"{{{NS_XHTML}}}figcaption")
                self._render_inlines(fc, block.caption)

            wrap = etree.SubElement(fig, f"{{{NS_XHTML}}}div", attrib={"class": "table-wrap"})

            if block.html and "<table" in block.html:
                try:
                    table_el = etree.fromstring(block.html.encode("utf-8"))
                    ensure_xhtml_namespace(table_el)
                    wrap.append(table_el)
                except Exception as e:
                    logger.warning("Failed to parse table XML: %s", e)
                    # Fallback to table image if available
                    if block.fallback_asset_id:
                        asset = self.registry.get_asset(block.fallback_asset_id)
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
                asset = self.registry.get_asset(block.fallback_asset_id)
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
                self._render_inlines(fn_div, block.footnotes)

        elif isinstance(block, ListBlock):
            if block.ordered is True:
                list_tag = "ol"
                l_attribs: dict[str, str] = {}
            elif block.ordered is False:
                list_tag = "ul"
                l_attribs = {}
            else:
                list_tag = "ul"
                l_attribs = {"class": "list-marker-preserved"}

            list_el = etree.SubElement(parent, f"{{{NS_XHTML}}}{list_tag}", attrib=l_attribs)
            for item_inlines in block.items:
                li = etree.SubElement(list_el, f"{{{NS_XHTML}}}li")
                self._render_inlines(li, item_inlines)

        elif isinstance(block, Aside):
            aside_el = etree.SubElement(
                parent,
                f"{{{NS_XHTML}}}aside",
                attrib={"class": f"aside aside-{block.subtype}"},
            )
            p = etree.SubElement(aside_el, f"{{{NS_XHTML}}}p")
            self._render_inlines(p, block.inlines)

        elif isinstance(block, PreformattedBlock):
            # M10 Legacy Semantic Bridge: PreformattedBlock -> selectable <pre>/<code>
            pre = etree.SubElement(parent, f"{{{NS_XHTML}}}pre")
            code_el = etree.SubElement(pre, f"{{{NS_XHTML}}}code")
            code_el.text = block.text

        elif isinstance(block, Callout):
            # M10 Legacy Semantic Bridge: Callout -> conservative <aside class="aside ...">
            st = block.subtype or "note"
            aside_el = etree.SubElement(
                parent,
                f"{{{NS_XHTML}}}aside",
                attrib={"class": f"aside aside-{st}"},
            )
            for child in block.blocks:
                self.render_block_into(aside_el, child)

        elif isinstance(block, BlockQuote):
            # M10 Legacy Semantic Bridge: BlockQuote -> semantic <blockquote>
            bq = etree.SubElement(parent, f"{{{NS_XHTML}}}blockquote")
            if hasattr(block, "blocks") and getattr(block, "blocks"):
                for child in block.blocks:
                    self.render_block_into(bq, child)
            elif hasattr(block, "inlines") and getattr(block, "inlines"):
                p = etree.SubElement(bq, f"{{{NS_XHTML}}}p")
                self._render_inlines(p, block.inlines)

        elif isinstance(block, DefinitionList):
            # M10 Legacy Semantic Bridge: DefinitionList -> <dl>/<dt>/<dd>
            dl = etree.SubElement(parent, f"{{{NS_XHTML}}}dl")
            for item in block.items:
                dt = etree.SubElement(dl, f"{{{NS_XHTML}}}dt")
                self._render_inlines(dt, item.term)
                for defn in item.definitions:
                    dd = etree.SubElement(dl, f"{{{NS_XHTML}}}dd")
                    self._render_inlines(dd, defn)

        elif isinstance(block, ExampleBlock):
            # M10 Legacy Semantic Bridge: ExampleBlock -> <section class="example">
            sec = etree.SubElement(parent, f"{{{NS_XHTML}}}section", attrib={"class": "example"})
            for child in block.blocks:
                self.render_block_into(sec, child)

        elif isinstance(block, ExerciseBlock):
            # M10 Legacy Semantic Bridge: ExerciseBlock -> <section class="exercise">
            sec = etree.SubElement(parent, f"{{{NS_XHTML}}}section", attrib={"class": "exercise"})
            for child in block.blocks:
                self.render_block_into(sec, child)

        elif isinstance(block, Footnote):
            fn_id = f"fn-{block.id}"
            aside_el = etree.SubElement(
                parent,
                f"{{{NS_XHTML}}}aside",
                attrib={
                    "id": fn_id,
                    f"{{{NS_EPUB}}}type": "footnote",
                    "class": "page-footnote",
                },
            )
            p = etree.SubElement(aside_el, f"{{{NS_XHTML}}}p")
            self._render_inlines(p, block.inlines)

        elif isinstance(block, IndexBlock):
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
                self._render_inlines(p, item_inlines)

        elif isinstance(block, UnknownBlock):
            if block.extracted_text:
                div = etree.SubElement(
                    parent,
                    f"{{{NS_XHTML}}}div",
                    attrib={"class": "unknown-block"},
                )
                div.text = block.extracted_text
                self.warnings.append(
                    IRWarning(
                        code="UNKNOWN_BLOCK_RENDERED",
                        message=f"Unknown block type '{block.source_type}' rendered as text div",
                        page_idx=block.sources[0].page_idx if block.sources else None,
                    )
                )
            elif block.asset_id:
                asset = self.registry.get_asset(block.asset_id)
                if asset:
                    fig = etree.SubElement(
                        parent,
                        f"{{{NS_XHTML}}}figure",
                        attrib={"class": "figure size-large align-center"},
                    )
                    etree.SubElement(
                        fig,
                        f"{{{NS_XHTML}}}img",
                        attrib={
                            "src": f"../{asset.rel_path}",
                            "alt": f"Unknown block {block.source_type}",
                        },
                    )

    def serialize(self) -> bytes:
        """Serialize document to XML-encoded UTF-8 bytes with XML declaration."""
        return etree.tostring(
            self.root,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        )
