"""Component-based XHTML document renderer for reflowable EPUB 3.3 (M10)."""

import logging
import re
from collections import defaultdict
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
    IndexBlock,
    Inline,
    IRWarning,
    ListBlock,
    PageBreak,
    Paragraph,
    PreformattedBlock,
    Table,
    UnknownBlock,
)
from book2epub.presentation.models import BookStyleProfile
from book2epub.render.math import convert_latex_to_mathml
from book2epub.render.models import PageMapEntry, TocEntry

from .base import NS_EPUB, NS_XHTML, NS_XML, NSMAP
from .callouts import render_aside, render_callout
from .containers import (
    render_example_block,
    render_exercise_block,
    render_footnote,
    render_index_block,
    render_unknown_block,
)
from .figures import render_figure
from .headings import render_heading
from .lists import render_definition_list, render_list
from .preformatted import render_code_block, render_preformatted_block
from .prose import render_inlines, render_paragraph
from .quotes import render_blockquote
from .tables import render_table

logger = logging.getLogger(__name__)


class ComponentDocumentRenderer:
    """Renders BookIR blocks into an XHTML content document using modular component helpers."""

    def __init__(
        self,
        doc_href: str,
        doc_id: str,
        title: str,
        language: str,
        registry: AssetRegistry,
        global_heading_seq: int = 1,
        page_label_confidence_map: dict[int, str] | None = None,
        profile: BookStyleProfile | None = None,
    ) -> None:
        self.doc_href = doc_href
        self.doc_id = doc_id
        self.title = title
        self.language = language
        self.registry = registry
        self.heading_seq = global_heading_seq
        self.page_label_conf_map = page_label_confidence_map or {}
        self.profile = profile

        self.contains_mathml = False
        self.page_map_entries: list[PageMapEntry] = []
        self.toc_entries: list[TocEntry] = []
        self.warnings: list[IRWarning] = []
        self.used_ids: set[str] = set()
        self.component_counts: dict[str, int] = defaultdict(int)

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
        base_id = f"scan-page-{pidx + 1:06d}" if is_scan else f"page-{clean_lbl}"

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
        render_inlines(
            parent=parent,
            inlines=inlines,
            registry=self.registry,
            warnings=self.warnings,
            pagebreak_renderer=self._render_pagebreak_element,
            mark_mathml=self._mark_mathml,
        )

    def _mark_mathml(self) -> None:
        self.contains_mathml = True

    def render_block(self, block: Block) -> None:
        """Render a single top-level BookIR block into document body."""
        self._render_block_recursive(self.body, block, depth=0)

    def _render_block_recursive(self, parent: etree._Element, block: Block, depth: int = 0) -> None:
        """Render a block into parent element with recursive container support."""
        if isinstance(block, PageBreak):
            self.component_counts["pagebreak"] += 1
            lbl = block.label or f"scan-{block.page_idx + 1}"
            span = self._render_pagebreak_element(block.page_idx, lbl)
            parent.append(span)

        elif isinstance(block, Heading):
            self.component_counts["heading"] += 1
            self.heading_seq = render_heading(
                parent=parent,
                block=block,
                doc_href=self.doc_href,
                heading_seq=self.heading_seq,
                used_ids=self.used_ids,
                warnings=self.warnings,
                toc_entries=self.toc_entries,
                render_inlines_func=self._render_inlines,
                profile=self.profile,
                is_in_container=(depth > 0),
            )

        elif isinstance(block, Paragraph):
            self.component_counts["paragraph"] += 1
            render_paragraph(parent, block, self._render_inlines)

        elif isinstance(block, DisplayMath):
            self.component_counts["math"] += 1
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
            self.component_counts["code_block"] += 1
            render_code_block(parent, block, self._render_inlines)

        elif isinstance(block, PreformattedBlock):
            self.component_counts[f"preformatted_{block.subtype}"] += 1
            render_preformatted_block(parent, block, self._render_inlines)

        elif isinstance(block, Callout):
            self.component_counts[f"callout_{block.subtype}"] += 1
            render_callout(
                parent=parent,
                block=block,
                recursive_render_func=self._render_block_recursive,
                render_inlines_func=self._render_inlines,
                depth=depth,
            )

        elif isinstance(block, Aside):
            self.component_counts[f"aside_{block.subtype}"] += 1
            render_aside(parent, block, self._render_inlines)

        elif isinstance(block, BlockQuote):
            self.component_counts["quote"] += 1
            render_blockquote(
                parent=parent,
                block=block,
                recursive_render_func=self._render_block_recursive,
                render_inlines_func=self._render_inlines,
                profile=self.profile,
                depth=depth,
            )

        elif isinstance(block, ListBlock):
            self.component_counts["list"] += 1
            render_list(parent, block, self._render_inlines, profile=self.profile)

        elif isinstance(block, DefinitionList):
            self.component_counts["definition_list"] += 1
            render_definition_list(parent, block, self._render_inlines)

        elif isinstance(block, Table):
            self.component_counts["table"] += 1
            render_table(parent, block, self.registry, self._render_inlines)

        elif isinstance(block, (Figure, Chart)):
            self.component_counts["figure" if isinstance(block, Figure) else "chart"] += 1
            render_figure(
                parent=parent,
                block=block,
                registry=self.registry,
                warnings=self.warnings,
                render_inlines_func=self._render_inlines,
                profile=self.profile,
            )

        elif isinstance(block, ExampleBlock):
            self.component_counts["example"] += 1
            render_example_block(parent, block, self._render_block_recursive, depth=depth)

        elif isinstance(block, ExerciseBlock):
            self.component_counts["exercise"] += 1
            render_exercise_block(parent, block, self._render_block_recursive, depth=depth)

        elif isinstance(block, Footnote):
            self.component_counts["footnote"] += 1
            render_footnote(parent, block, self._render_inlines)

        elif isinstance(block, IndexBlock):
            self.component_counts["index"] += 1
            render_index_block(parent, block, self._render_inlines)

        elif isinstance(block, UnknownBlock):
            self.component_counts["unknown"] += 1
            render_unknown_block(parent, block)

    def serialize(self) -> bytes:
        """Serialize document to XML-encoded UTF-8 bytes with XML declaration."""
        return etree.tostring(
            self.root,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
        )
