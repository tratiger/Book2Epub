"""Adapter converting MinerU middle.json into BookIR models."""

import logging
from pathlib import Path
from typing import Any, Literal

from book2epub.errors import IRError
from book2epub.ir.assets import AssetRegistry
from book2epub.ir.models import (
    Aside,
    BBox,
    Block,
    BookIR,
    BookMetadata,
    Chart,
    CodeBlock,
    DisplayMath,
    Figure,
    Footnote,
    Heading,
    IndexBlock,
    Inline,
    InlineMath,
    IRWarning,
    ListBlock,
    Paragraph,
    SourceDocument,
    SourcePage,
    SourceRef,
    Table,
    Text,
    UnknownBlock,
)
from book2epub.ir.table_sanitizer import sanitize_table_html
from book2epub.ir.text_join import join_prose_texts

logger = logging.getLogger(__name__)

KNOWN_BLOCK_KEYS = {
    "type",
    "lines",
    "blocks",
    "bbox",
    "level",
    "sub_type",
    "attribute",
    "html",
    "image_path",
    "content",
    "language",
}


def parse_bbox(raw_bbox: Any) -> BBox | None:
    """Parse a 4-element coordinate list/tuple into a BBox."""
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            return BBox(
                x0=float(raw_bbox[0]),
                y0=float(raw_bbox[1]),
                x1=float(raw_bbox[2]),
                y1=float(raw_bbox[3]),
            )
        except (ValueError, TypeError):
            return None
    return None


class MiddleJsonAdapter:
    """Converts MinerU 3.4.5 middle.json data into BookIR."""

    def __init__(
        self,
        base_dir: Path,
        metadata: BookMetadata | None = None,
        strict: bool = True,
    ) -> None:
        self.base_dir = base_dir
        self.metadata = metadata or BookMetadata()
        self.strict = strict
        self.registry = AssetRegistry()
        self.warnings: list[IRWarning] = []
        self._block_seq = 0

    def next_block_id(self, prefix: str = "blk") -> str:
        self._block_seq += 1
        return f"{prefix}-{self._block_seq:05d}"

    def resolve_image_path(self, img_rel_path: str) -> Path:
        """Resolve image path relative to base_dir or base_dir / images."""
        p = self.base_dir / img_rel_path
        if p.is_file():
            return p
        images_p = self.base_dir / "images" / img_rel_path
        if images_p.is_file():
            return images_p
        return p

    def extract_source_ref(
        self,
        block: dict[str, Any],
        page_idx: int,
        source_index: int | None = None,
    ) -> SourceRef:
        bbox = parse_bbox(block.get("bbox"))
        line_bboxes: list[BBox] = []
        span_bboxes: list[BBox] = []

        for line in block.get("lines", []):
            l_box = parse_bbox(line.get("bbox"))
            if l_box:
                line_bboxes.append(l_box)
            for span in line.get("spans", []):
                s_box = parse_bbox(span.get("bbox"))
                if s_box:
                    span_bboxes.append(s_box)

        raw_ext = {k: v for k, v in block.items() if k not in KNOWN_BLOCK_KEYS}

        return SourceRef(
            page_idx=page_idx,
            bbox=bbox,
            source_type=block.get("type", "unknown"),
            source_index=source_index,
            line_bboxes=line_bboxes,
            span_bboxes=span_bboxes,
            raw_extensions=raw_ext,
        )

    def extract_inlines(self, block: dict[str, Any], page_idx: int) -> list[Inline]:
        """Extract inline nodes (Text, InlineMath) from a block's lines and spans."""
        inlines: list[Inline] = []
        text_accumulator: list[str] = []
        pending_sources: list[SourceRef] = []

        def flush_text() -> None:
            nonlocal text_accumulator, pending_sources
            if text_accumulator:
                joined = join_prose_texts(text_accumulator)
                if joined:
                    inlines.append(Text(text=joined, sources=list(pending_sources)))
                text_accumulator = []
                pending_sources = []

        for line in block.get("lines", []):
            line_box = parse_bbox(line.get("bbox"))
            for span in line.get("spans", []):
                stype = span.get("type", "text")
                span_box = parse_bbox(span.get("bbox")) or line_box
                s_ref = SourceRef(
                    page_idx=page_idx,
                    bbox=span_box,
                    source_type=stype,
                )

                if stype == "inline_equation":
                    flush_text()
                    latex = span.get("content", "").strip()
                    # Strip single outer $ if present
                    if latex.startswith("$") and latex.endswith("$") and len(latex) >= 2:
                        latex = latex[1:-1].strip()
                    inlines.append(InlineMath(latex=latex, sources=[s_ref]))
                elif stype == "text":
                    content = span.get("content", "")
                    if content:
                        text_accumulator.append(content)
                        pending_sources.append(s_ref)
                else:
                    # Generic span content
                    content = span.get("content", "")
                    if content:
                        text_accumulator.append(content)
                        pending_sources.append(s_ref)

        flush_text()
        return inlines

    def extract_code_text(self, block: dict[str, Any]) -> str:
        """Extract code content preserving newlines and indentation."""
        lines_out: list[str] = []
        for line in block.get("lines", []):
            spans_text = "".join(span.get("content", "") for span in line.get("spans", []))
            lines_out.append(spans_text)
        return "\n".join(lines_out)

    def convert_middle_json(self, data: dict[str, Any]) -> BookIR:
        """Parse middle.json and return a BookIR model."""
        pdf_info: list[dict[str, Any]] = data.get("pdf_info", [])

        # Build SourceDocument
        source_pages: list[SourcePage] = []
        for p in pdf_info:
            pidx = p.get("page_idx", 0)
            psize = p.get("page_size", [0, 0])
            w = float(psize[0]) if len(psize) >= 1 else 0.0
            h = float(psize[1]) if len(psize) >= 2 else 0.0
            source_pages.append(SourcePage(page_idx=pidx, width=w, height=h))

        source_doc = SourceDocument(
            mineru_version=data.get("_version_name", "3.4.5"),
            mineru_backend=data.get("_backend", "hybrid"),
            mineru_effort=data.get("_effort", "high"),
            page_count=len(source_pages),
            pages=source_pages,
        )

        all_blocks: list[Block] = []

        for p_idx, page in enumerate(pdf_info):
            page_idx = page.get("page_idx", p_idx)
            para_blocks = page.get("para_blocks", [])

            # Collect blocks for this page
            page_blocks: list[Block] = []

            for b_idx, block in enumerate(para_blocks):
                b_type = block.get("type", "unknown")
                s_ref = self.extract_source_ref(block, page_idx, source_index=b_idx)
                b_id = self.next_block_id()

                if b_type == "title":
                    level = block.get("level")
                    if isinstance(level, int) and 1 <= level <= 6:
                        hl = level
                    else:
                        hl = None
                    inlines = self.extract_inlines(block, page_idx)
                    page_blocks.append(Heading(id=b_id, level=hl, inlines=inlines, sources=[s_ref]))

                elif b_type == "text":
                    inlines = self.extract_inlines(block, page_idx)
                    if inlines:
                        page_blocks.append(Paragraph(id=b_id, inlines=inlines, sources=[s_ref]))

                elif b_type in ("image", "chart"):
                    # Find body span
                    img_rel_path: str | None = None
                    caption_inlines: list[Inline] = []
                    footnote_inlines: list[Inline] = []
                    chart_content: str | None = None

                    for sub in block.get("blocks", []):
                        st = sub.get("type", "")
                        if "caption" in st:
                            caption_inlines.extend(self.extract_inlines(sub, page_idx))
                        elif "footnote" in st:
                            footnote_inlines.extend(self.extract_inlines(sub, page_idx))
                        elif "body" in st or st in ("image", "chart"):
                            for line in sub.get("lines", []):
                                for sp in line.get("spans", []):
                                    if sp.get("image_path"):
                                        img_rel_path = sp.get("image_path")
                                    if sp.get("content"):
                                        chart_content = sp.get("content")

                    # Also check top-level lines/spans if no blocks
                    if not img_rel_path:
                        for line in block.get("lines", []):
                            for sp in line.get("spans", []):
                                if sp.get("image_path"):
                                    img_rel_path = sp.get("image_path")

                    if img_rel_path:
                        local_path = self.resolve_image_path(img_rel_path)
                        role: Literal[
                            "figure", "chart", "table-fallback", "equation-fallback", "cover"
                        ] = "chart" if b_type == "chart" else "figure"
                        try:
                            asset_id = self.registry.register_asset(local_path, role=role)
                        except Exception as e:
                            logger.error("Failed to register image asset: %s", e)
                            if self.strict:
                                raise
                            asset_id = f"missing-{img_rel_path}"

                        if b_type == "chart":
                            page_blocks.append(
                                Chart(
                                    id=b_id,
                                    asset_id=asset_id,
                                    caption=caption_inlines,
                                    footnotes=footnote_inlines,
                                    description=chart_content,
                                    sources=[s_ref],
                                )
                            )
                        else:
                            page_blocks.append(
                                Figure(
                                    id=b_id,
                                    asset_id=asset_id,
                                    caption=caption_inlines,
                                    footnotes=footnote_inlines,
                                    sources=[s_ref],
                                )
                            )
                    else:
                        logger.warning("Visual block %s has no image_path", b_id)
                        page_blocks.append(
                            UnknownBlock(
                                id=b_id,
                                source_type=b_type,
                                extracted_text=chart_content,
                                sources=[s_ref],
                            )
                        )

                elif b_type == "table":
                    raw_table_html = ""
                    fallback_img_path = None
                    caption_inlines = []
                    footnote_inlines = []

                    for sub in block.get("blocks", []):
                        st = sub.get("type", "")
                        if "caption" in st:
                            caption_inlines.extend(self.extract_inlines(sub, page_idx))
                        elif "footnote" in st:
                            footnote_inlines.extend(self.extract_inlines(sub, page_idx))
                        elif "body" in st or st == "table":
                            for line in sub.get("lines", []):
                                for sp in line.get("spans", []):
                                    if sp.get("html"):
                                        raw_table_html = sp.get("html")
                                    if sp.get("image_path"):
                                        fallback_img_path = sp.get("image_path")

                    if not raw_table_html:
                        for line in block.get("lines", []):
                            for sp in line.get("spans", []):
                                if sp.get("html"):
                                    raw_table_html = sp.get("html")
                                if sp.get("image_path"):
                                    fallback_img_path = sp.get("image_path")

                    sanitized_html = sanitize_table_html(
                        raw_table_html,
                        asset_registry=self.registry,
                        base_dir=self.base_dir,
                    )

                    fallback_asset_id = None
                    if fallback_img_path:
                        local_fb = self.resolve_image_path(fallback_img_path)
                        if local_fb.is_file():
                            fallback_asset_id = self.registry.register_asset(
                                local_fb, role="table-fallback"
                            )

                    if sanitized_html:
                        page_blocks.append(
                            Table(
                                id=b_id,
                                html=sanitized_html,
                                fallback_asset_id=fallback_asset_id,
                                caption=caption_inlines,
                                footnotes=footnote_inlines,
                                sources=[s_ref],
                            )
                        )
                    elif fallback_asset_id:
                        # Structured table failed, fallback to table image
                        logger.warning("Table %s HTML invalid; using fallback image", b_id)
                        page_blocks.append(
                            Figure(
                                id=b_id,
                                asset_id=fallback_asset_id,
                                caption=caption_inlines,
                                footnotes=footnote_inlines,
                                sources=[s_ref],
                            )
                        )
                    else:
                        raise IRError(f"Table block {b_id} has neither valid HTML nor image asset")

                elif b_type == "code":
                    subtype = block.get("sub_type", "code")
                    st_val: Literal["code", "algorithm"] = (
                        "algorithm" if subtype == "algorithm" else "code"
                    )
                    code_text = ""
                    caption_inlines = []
                    footnote_inlines = []

                    for sub in block.get("blocks", []):
                        st = sub.get("type", "")
                        if "caption" in st:
                            caption_inlines.extend(self.extract_inlines(sub, page_idx))
                        elif "footnote" in st:
                            footnote_inlines.extend(self.extract_inlines(sub, page_idx))
                        elif "body" in st or st == "code":
                            code_text = self.extract_code_text(sub)

                    if not code_text:
                        code_text = self.extract_code_text(block)

                    page_blocks.append(
                        CodeBlock(
                            id=b_id,
                            text=code_text,
                            subtype=st_val,
                            caption=caption_inlines,
                            footnotes=footnote_inlines,
                            language=block.get("language"),
                            sources=[s_ref],
                        )
                    )

                elif b_type == "interline_equation":
                    latex = ""
                    fallback_img_path = None
                    for line in block.get("lines", []):
                        for sp in line.get("spans", []):
                            if sp.get("content"):
                                latex = sp.get("content").strip()
                            if sp.get("image_path"):
                                fallback_img_path = sp.get("image_path")

                    # Strip outer $$ if present
                    if latex.startswith("$$") and latex.endswith("$$") and len(latex) >= 4:
                        latex = latex[2:-2].strip()

                    fallback_id = None
                    if fallback_img_path:
                        local_fb = self.resolve_image_path(fallback_img_path)
                        if local_fb.is_file():
                            fallback_id = self.registry.register_asset(
                                local_fb, role="equation-fallback"
                            )

                    page_blocks.append(
                        DisplayMath(
                            id=b_id,
                            latex=latex,
                            fallback_asset_id=fallback_id,
                            sources=[s_ref],
                        )
                    )

                elif b_type == "list":
                    # Collect item inlines
                    items: list[list[Inline]] = []
                    for sub in block.get("blocks", []):
                        item_inlines = self.extract_inlines(sub, page_idx)
                        if item_inlines:
                            items.append(item_inlines)
                    if not items:
                        for line in block.get("lines", []):
                            l_inlines = self.extract_inlines({"lines": [line]}, page_idx)
                            if l_inlines:
                                items.append(l_inlines)

                    ordered = None
                    attr = str(block.get("attribute", "")).lower()
                    if "ordered" in attr:
                        ordered = True
                    elif "unordered" in attr:
                        ordered = False

                    page_blocks.append(
                        ListBlock(
                            id=b_id,
                            ordered=ordered,
                            items=items,
                            subtype=block.get("sub_type"),
                            sources=[s_ref],
                        )
                    )

                elif b_type == "index":
                    items = []
                    for line in block.get("lines", []):
                        l_inlines = self.extract_inlines({"lines": [line]}, page_idx)
                        if l_inlines:
                            items.append(l_inlines)
                    page_blocks.append(IndexBlock(id=b_id, items=items, sources=[s_ref]))

                elif b_type == "aside_text":
                    inlines = self.extract_inlines(block, page_idx)
                    page_blocks.append(Aside(id=b_id, inlines=inlines, sources=[s_ref]))

                elif b_type == "page_footnote":
                    inlines = self.extract_inlines(block, page_idx)
                    page_blocks.append(
                        Footnote(id=b_id, inlines=inlines, scope="page", sources=[s_ref])
                    )

                else:
                    # Unknown block type
                    inlines = self.extract_inlines(block, page_idx)
                    text_extracted = " ".join(i.text for i in inlines if isinstance(i, Text))
                    self.warnings.append(
                        IRWarning(
                            code="UNKNOWN_BLOCK_TYPE",
                            message=(
                                f"Encountered unknown block type '{b_type}' on page {page_idx + 1}"
                            ),
                            page_idx=page_idx,
                            details={"type": b_type, "text": text_extracted[:100]},
                        )
                    )
                    page_blocks.append(
                        UnknownBlock(
                            id=b_id,
                            source_type=b_type,
                            extracted_text=text_extracted or None,
                            sources=[s_ref],
                        )
                    )

            # Insert aside_text near its reading position in page_blocks
            for d_idx, d_block in enumerate(page.get("discarded_blocks", [])):
                d_type = d_block.get("type", "")
                if d_type == "aside_text":
                    d_id = self.next_block_id()
                    d_ref = self.extract_source_ref(d_block, page_idx, source_index=d_idx)
                    inlines = self.extract_inlines(d_block, page_idx)
                    aside_node = Aside(id=d_id, inlines=inlines, sources=[d_ref])
                    aside_box = parse_bbox(d_block.get("bbox"))
                    if aside_box is not None:
                        insert_pos = len(page_blocks)
                        for pos, blk in enumerate(page_blocks):
                            b_box = blk.sources[0].bbox if blk.sources else None
                            if b_box is not None and b_box.y0 > aside_box.y0:
                                insert_pos = pos
                                break
                        page_blocks.insert(insert_pos, aside_node)
                    else:
                        page_blocks.append(aside_node)

                elif d_type == "page_footnote":
                    d_id = self.next_block_id()
                    d_ref = self.extract_source_ref(d_block, page_idx, source_index=d_idx)
                    inlines = self.extract_inlines(d_block, page_idx)
                    page_blocks.append(
                        Footnote(id=d_id, inlines=inlines, scope="page", sources=[d_ref])
                    )

            all_blocks.extend(page_blocks)

        return BookIR(
            schema_version="1.0",
            source=source_doc,
            metadata=self.metadata,
            blocks=all_blocks,
            assets=self.registry.assets,
            warnings=self.warnings,
        )
