"""Semantic evidence extraction from middle.json and Raw BookIR."""

import re
from typing import Any

from book2epub.ir.models import (
    BBox,
    BookIR,
    Footnote,
    ListBlock,
    SourceRef,
    SourceTextSegment,
    Table,
    extract_inline_source_segments,
    extract_inline_visible_text,
)
from book2epub.semantic.hashing import compute_content_sha256, compute_text_sha256
from book2epub.semantic.materializers import allowed_targets_for
from book2epub.semantic.models import (
    EvidenceLine,
    EvidenceSegment,
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)

SHELL_PROMPT_PATTERNS = [
    re.compile(r"^\s*[$#>]\s+\S", re.MULTILINE),
    re.compile(r"^\s*[A-Za-z]:\\[^>]*>\s*\S", re.MULTILINE),
    re.compile(r"^\s*PS\s+[^>]*>\s*\S", re.MULTILINE),
]

CODE_KEYWORDS = {
    "def ", "function ", "class ", "import ", "return ", "if ", "for ", "while ",
    "const ", "let ", "var ", "public ", "private ", "void ", "int ", "#include",
}


def _detect_shell_prompt(text: str) -> bool:
    """Check if any line in text starts with a shell/terminal prompt."""
    if not text:
        return False
    return any(p.search(text) for p in SHELL_PROMPT_PATTERNS)


def _detect_code_tokens(text: str) -> bool:
    """Check if text contains multiple code-like punctuation tokens or keywords."""
    if not text:
        return False
    score = 0
    for tok in ("{", "}", "()", ";", "=>", "==", "!=", "->"):
        if tok in text:
            score += 1
    for kw in CODE_KEYWORDS:
        if kw in text:
            score += 1
    return score >= 3


def _extract_preformatted_text_from_middle_block(raw_block: dict[str, Any]) -> str:
    """
    Recursively extract preformatted lines from a middle.json block preserving
    source line breaks and intra-line spacing (M6 spec Section 4.2).
    """
    lines_out: list[str] = []

    def collect_lines(node: dict[str, Any]) -> None:
        # Check subblocks first (for tables, image containers, etc.)
        subblocks = node.get("blocks", [])
        if subblocks:
            for sub in subblocks:
                collect_lines(sub)
            return

        for line in node.get("lines", []):
            line_str = "".join(span.get("content", "") for span in line.get("spans", []))
            lines_out.append(line_str)

    collect_lines(raw_block)
    return "\n".join(lines_out)


def _extract_plain_text_from_middle_block(raw_block: dict[str, Any]) -> str:
    """
    Extract best-effort visible-text flattening for model context (M6 spec Section 4.1).
    """
    lines_out: list[str] = []

    def collect(node: dict[str, Any]) -> None:
        subblocks = node.get("blocks", [])
        if subblocks:
            for sub in subblocks:
                collect(sub)
            return

        for line in node.get("lines", []):
            line_parts: list[str] = []
            for span in line.get("spans", []):
                stype = span.get("type", "text")
                content = span.get("content", "")
                if stype == "inline_equation":
                    line_parts.append(f"<MATH:{content.strip('$')}>")
                else:
                    line_parts.append(content)
            lines_out.append("".join(line_parts))

    collect(raw_block)
    return "\n".join(lines_out)


def _extract_evidence_lines(raw_block: dict[str, Any]) -> list[EvidenceLine]:
    """Build fine-grained EvidenceLine objects from a middle block."""
    result: list[EvidenceLine] = []
    line_seq = 0

    def collect(node: dict[str, Any]) -> None:
        nonlocal line_seq
        subblocks = node.get("blocks", [])
        if subblocks:
            for sub in subblocks:
                collect(sub)
            return

        for line in node.get("lines", []):
            line_seq += 1
            bbox = line.get("bbox")
            line_box = list(bbox) if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else None
            segments: list[EvidenceSegment] = []
            for s_idx, span in enumerate(line.get("spans", [])):
                s_bbox = span.get("bbox")
                span_box = (
                    list(s_bbox)
                    if isinstance(s_bbox, (list, tuple)) and len(s_bbox) == 4
                    else line_box
                )
                text = span.get("content")
                img_p = span.get("image_path")
                t_hash = compute_text_sha256(text) if text else None
                segments.append(
                    EvidenceSegment(
                        segment_index=s_idx,
                        span_type=span.get("type", "text"),
                        text=text,
                        image_path=img_p,
                        bbox=span_box,
                        text_sha256=t_hash,
                    )
                )
            result.append(
                EvidenceLine(
                    line_index=line_seq,
                    bbox=line_box,
                    segments=segments,
                )
            )

    collect(raw_block)
    return result


def _compute_flags(
    source_type: str,
    current_kind: str,
    plain_text: str,
    preformatted_text: str | None,
    table_html: str | None,
    asset_ids: list[str],
    bbox: list[float] | None,
    page_size: list[float],
    heading_level: int | None = None,
) -> list[str]:
    """Compute deterministic review flags (M6 spec Section 6)."""
    flags: list[str] = []

    if asset_ids:
        flags.append("HAS_VISUAL_ASSET")

    if table_html:
        flags.append("HAS_STRUCTURED_TABLE")

    # Table cues
    if source_type == "table" or current_kind == "table":
        if table_html and "<th" not in table_html.lower():
            flags.append("TABLE_WITHOUT_CLEAR_HEADER")
        if preformatted_text and _detect_shell_prompt(preformatted_text):
            flags.append("TABLE_CONTAINS_SHELL_PROMPT")
        if preformatted_text and _detect_code_tokens(preformatted_text):
            flags.append("TABLE_CONTAINS_CODE_TOKENS")
        # Low cell density check (simple tag counting heuristic)
        if table_html:
            tr_count = table_html.lower().count("<tr")
            td_count = table_html.lower().count("<td") + table_html.lower().count("<th")
            if tr_count > 0 and (td_count / tr_count) <= 1.5:
                flags.append("TABLE_LOW_CELL_DENSITY")

    # Text cues
    if source_type in ("text", "paragraph") or current_kind == "paragraph":
        if preformatted_text and (
            _detect_shell_prompt(preformatted_text) or _detect_code_tokens(preformatted_text)
        ):
            flags.append("TEXT_LOOKS_PREFORMATTED")
        # List marker in text
        if re.search(r"^\s*[-*•・]\s+\S", plain_text) or re.search(
            r"^\s*\d+[\.、\)]\s+\S", plain_text
        ):
            flags.append("LIST_MARKER_IN_TEXT")
        # Callout-like language
        callout_pattern = (
            r"^(?:Note|Tip|Warning|Caution|Important|注意|警告|ヒント|コラム|補足)[:：\s]"
        )
        if re.search(callout_pattern, plain_text, re.IGNORECASE):
            flags.append("CALLOUT_LIKE_GEOMETRY")

    # Heading cues
    if source_type in ("title", "heading") or current_kind == "heading":
        if heading_level is None:
            flags.append("HEADING_LEVEL_UNKNOWN")
        if len(plain_text) > 80:
            flags.append("HEADING_TOO_LONG")
        if plain_text.rstrip().endswith(("。", ".", "!", "?", "！", "？")):
            flags.append("HEADING_ENDS_SENTENCE")

    # Page boundary proximity
    if bbox and len(bbox) == 4 and len(page_size) >= 2 and page_size[1] > 0:
        h = page_size[1]
        y0, y1 = bbox[1], bbox[3]
        if y1 > h * 0.9 or y0 < h * 0.1:
            flags.append("CROSS_PAGE_BOUNDARY_NEAR_BLOCK")

    return flags


def build_semantic_evidence(
    middle_data: dict[str, Any],
    raw_ir: BookIR,
    source_middle_sha256: str = "",
    raw_bookir_sha256: str = "",
) -> SemanticEvidenceBook:
    """
    Build canonical SemanticEvidenceBook from MinerU middle.json and Raw BookIR
    (M6 spec Section 4).
    """
    pdf_info: list[dict[str, Any]] = middle_data.get("pdf_info", [])

    # Index middle blocks by (page_idx, source_index)
    middle_blocks_by_idx: dict[tuple[int, int], dict[str, Any]] = {}
    page_sizes: dict[int, list[float]] = {}

    for page in pdf_info:
        p_idx = page.get("page_idx", 0)
        psize = page.get("page_size", [0.0, 0.0])
        w = float(psize[0]) if len(psize) >= 1 else 0.0
        h = float(psize[1]) if len(psize) >= 2 else 0.0
        page_sizes[p_idx] = [w, h]

        for b_idx, blk in enumerate(page.get("para_blocks", [])):
            middle_blocks_by_idx[(p_idx, b_idx)] = blk

    evidence_blocks: list[SemanticEvidenceBlock] = []

    for order_idx, ir_block in enumerate(raw_ir.blocks):
        b_id = ir_block.id
        s_ref: SourceRef | None = ir_block.sources[0] if ir_block.sources else None
        p_idx = s_ref.page_idx if s_ref else 0
        src_idx = s_ref.source_index if s_ref else None
        src_type = s_ref.source_type if s_ref else "unknown"

        raw_middle_block = None
        if src_idx is not None:
            raw_middle_block = middle_blocks_by_idx.get((p_idx, src_idx))

        page_size = page_sizes.get(p_idx, [0.0, 0.0])

        bbox_coords: list[float] | None = None
        if s_ref and s_ref.bbox:
            bbox_coords = [s_ref.bbox.x0, s_ref.bbox.y0, s_ref.bbox.x1, s_ref.bbox.y1]
        elif raw_middle_block and raw_middle_block.get("bbox"):
            b = raw_middle_block["bbox"]
            if isinstance(b, (list, tuple)) and len(b) == 4:
                bbox_coords = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]

        # Plain text
        preformatted_text: str | None = None
        if raw_middle_block:
            plain_text = _extract_plain_text_from_middle_block(raw_middle_block)
            preformatted_text = _extract_preformatted_text_from_middle_block(raw_middle_block)
            line_segments = _extract_evidence_lines(raw_middle_block)
        else:
            plain_text = ""
            raw_text = getattr(ir_block, "text", None)
            preformatted_text = str(raw_text) if raw_text is not None else None
            line_segments = []

        # Table HTML
        table_html: str | None = None
        if isinstance(ir_block, Table):
            table_html = ir_block.html
        table_html_available = bool(table_html)
        table_html_sha256 = compute_text_sha256(table_html) if table_html else None

        # Assets
        asset_ids: list[str] = []
        if hasattr(ir_block, "asset_id") and getattr(ir_block, "asset_id"):
            asset_ids.append(getattr(ir_block, "asset_id"))
        if hasattr(ir_block, "fallback_asset_id") and getattr(ir_block, "fallback_asset_id"):
            asset_ids.append(getattr(ir_block, "fallback_asset_id"))

        # Caption text & segments
        caption_text = None
        caption_source_segments: list[SourceTextSegment] = []
        caption_inlines_snapshot: list[dict[str, Any]] = []
        if hasattr(ir_block, "caption") and getattr(ir_block, "caption"):
            cap_inlines = getattr(ir_block, "caption")
            caption_text = extract_inline_visible_text(cap_inlines) or None
            caption_source_segments = extract_inline_source_segments(cap_inlines)
            caption_inlines_snapshot = [inl.model_dump() for inl in cap_inlines]

        # Footnote text & segments
        footnote_text = None
        footnote_source_segments: list[SourceTextSegment] = []
        footnote_inlines_snapshot: list[dict[str, Any]] = []
        if hasattr(ir_block, "footnotes") and getattr(ir_block, "footnotes"):
            footnote_text = extract_inline_visible_text(getattr(ir_block, "footnotes")) or None
            fns = getattr(ir_block, "footnotes")
            footnote_source_segments = extract_inline_source_segments(fns)
            footnote_inlines_snapshot = [inl.model_dump() for inl in fns]
        elif isinstance(ir_block, Footnote) and getattr(ir_block, "inlines", None):
            footnote_text = extract_inline_visible_text(getattr(ir_block, "inlines")) or None
            footnote_source_segments = extract_inline_source_segments(getattr(ir_block, "inlines"))

        # Source segments from Text inlines & ListBlock items
        source_segments: list[SourceTextSegment] = []
        if hasattr(ir_block, "inlines"):
            source_segments.extend(extract_inline_source_segments(getattr(ir_block, "inlines", [])))
        elif isinstance(ir_block, ListBlock):
            for it in ir_block.items:
                source_segments.extend(extract_inline_source_segments(it))

        # Content hash
        content_hash = compute_content_sha256(
            plain_text=plain_text,
            preformatted_text=preformatted_text,
            table_html_text_content=table_html,
            caption_text=caption_text,
            footnote_text=footnote_text,
        )

        flags = _compute_flags(
            source_type=src_type,
            current_kind=ir_block.kind,
            plain_text=plain_text,
            preformatted_text=preformatted_text,
            table_html=table_html,
            asset_ids=asset_ids,
            bbox=bbox_coords,
            page_size=page_size,
            heading_level=getattr(ir_block, "level", None),
        )

        source_bboxes: list[BBox] = []
        if s_ref and s_ref.bbox:
            source_bboxes.append(s_ref.bbox)

        evidence_block = SemanticEvidenceBlock(
            block_id=b_id,
            order_index=order_idx,
            page_idx=p_idx,
            page_indices=[p_idx],
            source_index=src_idx,
            source_type=src_type,
            mineru_source_types=[src_type],
            current_kind=ir_block.kind,
            current_subtype=getattr(ir_block, "subtype", None),
            raw_bookir_kind=ir_block.kind,
            raw_bookir_subtype=getattr(ir_block, "subtype", None),
            bbox=bbox_coords,
            source_bboxes=source_bboxes,
            page_size=page_size,
            plain_text=plain_text,
            exact_plain_text=plain_text,
            exact_plain_text_sha256=compute_text_sha256(plain_text),
            preformatted_text=preformatted_text,
            table_html=table_html,
            table_html_available=table_html_available,
            table_html_sha256=table_html_sha256,
            asset_ids=asset_ids,
            caption_text=caption_text,
            caption_plain_text=caption_text,
            footnote_text=footnote_text,
            footnote_plain_text=footnote_text,
            line_segments=line_segments,
            source_segments=source_segments,
            caption_source_segments=caption_source_segments,
            footnote_source_segments=footnote_source_segments,
            caption_inlines_snapshot=caption_inlines_snapshot,
            footnote_inlines_snapshot=footnote_inlines_snapshot,
            content_sha256=content_hash,
            allowed_targets=[],
            flags=flags,
            source_extensions_summary=s_ref.raw_extensions if s_ref else {},
        )
        evidence_blocks.append(
            evidence_block.model_copy(
                update={"allowed_targets": allowed_targets_for(ir_block, evidence_block)}
            )
        )

    return SemanticEvidenceBook(
        source_middle_sha256=source_middle_sha256,
        raw_bookir_sha256=raw_bookir_sha256,
        blocks=evidence_blocks,
    )
