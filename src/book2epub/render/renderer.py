"""Main ReflowRenderer producing the unpacked OEBPS publication tree."""

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from book2epub.ir.assets import AssetRegistry
from book2epub.ir.models import (
    BookIR,
    Chart,
    CodeBlock,
    DisplayMath,
    Figure,
    InlineMath,
    IRWarning,
    Paragraph,
    Table,
)
from book2epub.render.css import BOOK_CSS_CONTENT
from book2epub.render.metadata import infer_metadata
from book2epub.render.models import (
    PageMapEntry,
    RenderedDocument,
    RenderManifest,
    RenderResult,
    TocEntry,
)
from book2epub.render.splitter import split_bookir_blocks
from book2epub.render.xhtml import DocumentRenderer

logger = logging.getLogger(__name__)


def build_hierarchical_toc(
    flat_entries: list[TocEntry],
    default_title: str,
    first_doc_href: str,
) -> list[TocEntry]:
    """
    Build a logical hierarchical heading tree from flat TocEntries (levels 1-3).

    - If levels jump (h1 -> h3), nest under nearest existing shallower level.
    - If no headings exist, create a single TOC entry using book title to first doc.
    """
    if not flat_entries:
        return [
            TocEntry(
                title=default_title,
                href=first_doc_href,
                level=1,
                children=[],
            )
        ]

    root_entries: list[TocEntry] = []
    stack: list[TocEntry] = []

    for item in flat_entries:
        new_node = TocEntry(
            title=item.title,
            href=item.href,
            level=item.level,
            children=[],
        )

        # Pop from stack until top of stack is shallower (< new_node.level)
        while stack and stack[-1].level >= new_node.level:
            stack.pop()

        if stack:
            stack[-1].children.append(new_node)
        else:
            root_entries.append(new_node)

        stack.append(new_node)

    return root_entries


class ReflowRenderer:
    """Renders normalized BookIR into an unpacked OEBPS render tree."""

    def __init__(
        self,
        output_dir: Path,
        cli_title: str | None = None,
        cli_language: str | None = None,
        cli_identifier: str | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.cli_title = cli_title
        self.cli_language = cli_language
        self.cli_identifier = cli_identifier

    def render(self, bookir: BookIR) -> RenderResult:
        """
        Execute full M3 rendering pipeline:

        1. Infer final metadata (title, language, identifier).
        2. Split blocks into sections.
        3. Render each section to XHTML.
        4. Copy image assets into OEBPS/images/.
        5. Write OEBPS/styles/book.css.
        6. Assemble PageMap and hierarchical TOC.
        7. Write OEBPS/render-manifest.json.
        """
        oebps_dir = self.output_dir / "OEBPS"
        text_dir = oebps_dir / "text"
        styles_dir = oebps_dir / "styles"
        images_dir = oebps_dir / "images"

        text_dir.mkdir(parents=True, exist_ok=True)
        styles_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        # 1. Resolve final metadata
        metadata = infer_metadata(
            bookir,
            cli_title=self.cli_title,
            cli_language=self.cli_language,
            cli_identifier=self.cli_identifier,
        )

        # Asset registry
        registry = AssetRegistry()
        for asset in bookir.assets.values():
            registry.register_existing(asset)

        # Confidence map for page labels
        conf_map: dict[int, str] = {
            p.page_idx: ("high" if p.printed_label_confidence >= 0.8 else "low")
            for p in bookir.source.pages
        }

        # 2. Split blocks into sections
        sections = split_bookir_blocks(bookir.blocks)

        all_page_map: list[PageMapEntry] = []
        all_flat_toc: list[TocEntry] = []
        rendered_docs: list[RenderedDocument] = []
        all_warnings: list[IRWarning] = list(bookir.warnings)

        global_heading_seq = 1

        # 3. Render each section
        for sec in sections:
            doc_path = oebps_dir / sec.href
            doc_path.parent.mkdir(parents=True, exist_ok=True)

            doc_renderer = DocumentRenderer(
                doc_href=sec.href,
                doc_id=sec.doc_id,
                title=metadata.title or "Section",
                language=metadata.language or "und",
                registry=registry,
                global_heading_seq=global_heading_seq,
                page_label_confidence_map=conf_map,
            )

            for block in sec.blocks:
                doc_renderer.render_block(block)

            # Advance global heading sequence
            global_heading_seq = doc_renderer.heading_seq

            # Serialize and write XHTML
            xhtml_bytes = doc_renderer.serialize()
            doc_path.write_bytes(xhtml_bytes)

            rendered_docs.append(
                RenderedDocument(
                    href=sec.href,
                    id=sec.doc_id,
                    title=metadata.title or sec.doc_id,
                    contains_mathml=doc_renderer.contains_mathml,
                    media_type="application/xhtml+xml",
                )
            )

            all_page_map.extend(doc_renderer.page_map_entries)
            all_flat_toc.extend(doc_renderer.toc_entries)
            all_warnings.extend(doc_renderer.warnings)

        # Ensure all source pages have a PageMap destination
        seen_pages = {e.page_idx for e in all_page_map}
        first_doc_href = rendered_docs[0].href if rendered_docs else "text/part-0001.xhtml"

        for p in bookir.source.pages:
            if p.page_idx not in seen_pages:
                lbl = p.printed_label or f"scan-{p.page_idx + 1}"
                frag_id = f"scan-page-{p.page_idx + 1:06d}"
                all_page_map.append(
                    PageMapEntry(
                        page_idx=p.page_idx,
                        label=lbl,
                        xhtml_path=first_doc_href,
                        fragment_id=frag_id,
                        printed_label_confidence=(
                            "high" if p.printed_label_confidence >= 0.8 else "low"
                        ),
                    )
                )

        # Sort PageMap by page_idx
        all_page_map.sort(key=lambda e: e.page_idx)

        # 4. Hierarchical TOC
        hierarchical_toc = build_hierarchical_toc(
            all_flat_toc,
            default_title=metadata.title or "Book",
            first_doc_href=first_doc_href,
        )

        # 5. Write styles/book.css
        css_path = styles_dir / "book.css"
        css_path.write_text(BOOK_CSS_CONTENT, encoding="utf-8")

        # 6. Copy assets to images/
        asset_manifest_entries: list[dict[str, Any]] = []
        for asset in registry.list_assets():
            dest_asset_path = oebps_dir / asset.rel_path
            dest_asset_path.parent.mkdir(parents=True, exist_ok=True)
            if asset.local_path.exists():
                shutil.copy2(asset.local_path, dest_asset_path)
            else:
                logger.warning("Asset local path does not exist: %s", asset.local_path)

            asset_manifest_entries.append(
                {
                    "id": asset.asset_id,
                    "href": asset.rel_path,
                    "media_type": asset.media_type,
                    "role": asset.role,
                    "source_path": str(asset.local_path),
                }
            )

        # 7. Write render-manifest.json
        manifest = RenderManifest(
            title=metadata.title or "Untitled Book",
            language=metadata.language or "und",
            identifier=metadata.identifier or "urn:uuid:default",
            page_map=all_page_map,
            toc=hierarchical_toc,
            documents=rendered_docs,
            assets=asset_manifest_entries,
            styles=[{"id": "book-css", "href": "styles/book.css", "media_type": "text/css"}],
            warnings=[
                {"code": w.code, "message": w.message, "page_idx": w.page_idx} for w in all_warnings
            ],
        )

        manifest_path = oebps_dir / "render-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Calculate summary counts
        figure_count = sum(1 for b in bookir.blocks if isinstance(b, Figure))
        chart_count = sum(1 for b in bookir.blocks if isinstance(b, Chart))
        table_count = sum(1 for b in bookir.blocks if isinstance(b, Table))
        code_count = sum(1 for b in bookir.blocks if isinstance(b, CodeBlock))
        display_math_count = sum(1 for b in bookir.blocks if isinstance(b, DisplayMath))
        inline_math_count = 0
        for b in bookir.blocks:
            if isinstance(b, Paragraph):
                inline_math_count += sum(1 for i in b.inlines if isinstance(i, InlineMath))

        fallback_count = sum(
            1 for w in all_warnings if "FALLBACK" in w.code or "UNCONVERTED" in w.code
        )

        return RenderResult(
            oebps_dir=oebps_dir,
            manifest=manifest,
            source_page_count=bookir.source.page_count,
            xhtml_part_count=len(rendered_docs),
            figure_count=figure_count,
            chart_count=chart_count,
            table_count=table_count,
            code_count=code_count,
            math_count=display_math_count + inline_math_count,
            fallback_count=fallback_count,
            warning_count=len(all_warnings),
        )
