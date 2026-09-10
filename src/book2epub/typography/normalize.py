"""BookIR typography and whitespace normalization stage (M11/Appendix M)."""

import logging
from collections.abc import Sequence

from book2epub.ir.models import (
    Aside,
    Block,
    BlockQuote,
    BookIR,
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
    LineBreak,
    ListBlock,
    PageBoundary,
    PageBreak,
    Paragraph,
    PreformattedBlock,
    SourceTextSegment,
    Table,
    Text,
    UnknownBlock,
    replace_source_segment_text,
)
from book2epub.presentation.models import BookStyleProfile

from .boundaries import classify_boundary
from .lists import normalize_list_block
from .models import BoundaryType, NormalizationReport
from .spacing import (
    collapse_intra_segment_spaces,
    decide_inter_segment_separator,
)

logger = logging.getLogger(__name__)


def reconstruct_text_inline(
    inline: Text,
    block_id: str,
    report: NormalizationReport,
) -> Text:
    """
    Reconstruct visible prose text from SourceTextSegment evidence (Appendix M2).
    If source_segments is empty, returns inline unchanged and records fallback.
    """
    if not inline.source_segments:
        report.fallback_text_nodes_without_segments += 1
        return inline

    segments = inline.source_segments
    pieces: list[str] = []
    updated_segments: list[SourceTextSegment] = []

    # 1. First segment
    first_seg = segments[0]
    first_text, coll_count = collapse_intra_segment_spaces(first_seg.text)
    pieces.append(first_text)
    updated_segments.append(replace_source_segment_text(first_seg, first_text))

    # 2. Subsequent segments
    for i in range(1, len(segments)):
        seg_prev = updated_segments[-1]
        seg_curr = segments[i]

        curr_text, c_count = collapse_intra_segment_spaces(seg_curr.text)
        seg_curr_clean = replace_source_segment_text(seg_curr, curr_text)

        boundary = classify_boundary(seg_prev, seg_curr_clean)
        adj_prev, sep, adj_curr, is_dehyphen, reason = decide_inter_segment_separator(
            seg_prev, seg_curr_clean, boundary
        )

        # Update preceding segment if adjusted (e.g. trailing hyphen stripped)
        if adj_prev != seg_prev.text:
            pieces[-1] = adj_prev
            updated_segments[-1] = replace_source_segment_text(seg_prev, adj_prev)

        # Track metrics
        if sep == " ":
            if reason == "same_line_bbox_gap":
                report.spaces_inserted_same_line_bbox += 1
            elif boundary in (BoundaryType.NEW_LINE, BoundaryType.PAGE_CONTINUATION):
                report.new_line_spaces_inserted += 1

        if is_dehyphen:
            report.dehyphenations += 1
            report.record_change(
                block_id=block_id,
                change_type="dehyphenation",
                before=f"{seg_prev.text} + {seg_curr.text}",
                after=f"{adj_prev}{adj_curr}",
            )

        if sep:
            pieces.append(sep)
        pieces.append(adj_curr)
        updated_segments.append(replace_source_segment_text(seg_curr_clean, adj_curr))

    reconstructed_text = "".join(pieces)
    report.source_segment_reconstructions += 1

    # Record space differences vs legacy join if fewer spaces
    old_spaces = inline.text.count(" ")
    new_spaces = reconstructed_text.count(" ")
    if old_spaces > new_spaces:
        report.spaces_removed_vs_legacy_join += (old_spaces - new_spaces)

    if reconstructed_text != inline.text:
        report.record_change(
            block_id=block_id,
            change_type="whitespace_reconstruction",
            before=inline.text,
            after=reconstructed_text,
        )

    return inline.model_copy(
        update={"text": reconstructed_text, "source_segments": updated_segments}
    )


def normalize_inlines(
    inlines: Sequence[Inline],
    block_id: str,
    report: NormalizationReport,
) -> list[Inline]:
    """Normalize a sequence of inline elements recursively."""
    result: list[Inline] = []
    for inline in inlines:
        if isinstance(inline, Text):
            result.append(reconstruct_text_inline(inline, block_id, report))
        elif isinstance(inline, Hyperlink):
            # Target URL is strictly immutable; normalize children display text
            norm_children = normalize_inlines(inline.children, block_id, report)
            result.append(inline.model_copy(update={"children": norm_children}))
        elif isinstance(inline, (InlineMath, LineBreak, PageBoundary)):
            # Immutable
            result.append(inline)
        else:
            result.append(inline)
    return result


def normalize_block(
    block: Block,
    report: NormalizationReport,
    profile: BookStyleProfile | None = None,
) -> Block:
    """Normalize whitespace and typography inside a single BookIR block."""
    if isinstance(block, Paragraph):
        inlines = normalize_inlines(block.inlines, block.id, report)

        # M11 Section 8: Leading Japanese print indentation (U+3000)
        first_indent = getattr(profile.body, "first_line_indent", "none") if profile else "none"
        if first_indent != "none" and inlines and isinstance(inlines[0], Text):
            first_text = inlines[0].text
            if first_text.startswith("\u3000"):
                # Strip up to 2 leading ideographic spaces
                num_strip = 2 if first_text.startswith("\u3000\u3000") else 1
                stripped_text = first_text[num_strip:]
                report.leading_print_indents_normalized += 1
                report.record_change(
                    block_id=block.id,
                    change_type="leading_print_indent_normalized",
                    before=first_text[:10],
                    after=stripped_text[:10],
                )

                # Also adjust first source_segment if present
                updated_segs: list[SourceTextSegment] = []
                if inlines[0].source_segments:
                    rem = num_strip
                    for seg in inlines[0].source_segments:
                        if rem > 0 and seg.text.startswith("\u3000"):
                            s_count = 2 if rem >= 2 and seg.text.startswith("\u3000\u3000") else 1
                            rem -= s_count
                            updated_segs.append(
                                replace_source_segment_text(seg, seg.text[s_count:])
                            )
                        else:
                            updated_segs.append(seg)
                inlines[0] = inlines[0].model_copy(
                    update={"text": stripped_text, "source_segments": updated_segs}
                )

        return block.model_copy(update={"inlines": inlines})

    elif isinstance(block, Heading):
        inlines = normalize_inlines(block.inlines, block.id, report)
        return block.model_copy(update={"inlines": inlines})

    elif isinstance(block, ListBlock):
        # 1. Extract markers and infer marker style
        norm_list, count_extracted = normalize_list_block(block)
        report.list_markers_extracted += count_extracted
        current_count = report.marker_style_distribution.get(norm_list.marker_style, 0)
        report.marker_style_distribution[norm_list.marker_style] = current_count + 1

        # 2. Reconstruct inlines inside list items
        norm_items: list[list[Inline]] = []
        for item in norm_list.items:
            norm_items.append(normalize_inlines(item, block.id, report))

        return norm_list.model_copy(update={"items": norm_items})

    elif isinstance(block, Callout):
        norm_blocks = [normalize_block(b, report, profile) for b in block.blocks]
        return block.model_copy(update={"blocks": norm_blocks})

    elif isinstance(block, BlockQuote):
        norm_blocks = [normalize_block(b, report, profile) for b in block.blocks]
        norm_attr = normalize_inlines(block.attribution, block.id, report)
        return block.model_copy(update={"blocks": norm_blocks, "attribution": norm_attr})

    elif isinstance(block, ExampleBlock):
        norm_blocks = [normalize_block(b, report, profile) for b in block.blocks]
        return block.model_copy(update={"blocks": norm_blocks})

    elif isinstance(block, ExerciseBlock):
        norm_blocks = [normalize_block(b, report, profile) for b in block.blocks]
        norm_label = normalize_inlines(block.label, block.id, report)
        return block.model_copy(update={"blocks": norm_blocks, "label": norm_label})

    elif isinstance(block, Aside):
        norm_inlines = normalize_inlines(block.inlines, block.id, report)
        return block.model_copy(update={"inlines": norm_inlines})

    elif isinstance(block, Footnote):
        norm_inlines = normalize_inlines(block.inlines, block.id, report)
        return block.model_copy(update={"inlines": norm_inlines})

    elif isinstance(block, DefinitionList):
        new_def_items = []
        for def_item in block.items:
            norm_term = normalize_inlines(def_item.term, block.id, report)
            norm_defs = [normalize_inlines(d, block.id, report) for d in def_item.definitions]
            new_def_items.append(
                def_item.model_copy(update={"term": norm_term, "definitions": norm_defs})
            )
        return block.model_copy(update={"items": new_def_items})

    elif isinstance(block, IndexBlock):
        new_items = [normalize_inlines(it, block.id, report) for it in block.items]
        return block.model_copy(update={"items": new_items})

    elif isinstance(block, Figure):
        norm_caption = normalize_inlines(block.caption, block.id, report)
        norm_notes = normalize_inlines(block.footnotes, block.id, report)
        return block.model_copy(update={"caption": norm_caption, "footnotes": norm_notes})

    elif isinstance(
        block,
        (CodeBlock, PreformattedBlock, DisplayMath, Table, UnknownBlock, PageBreak, Chart),
    ):
        # Explicitly excluded from text mutation (Section 3 / Appendix M2)
        return block

    return block


def typography_normalize_bookir(
    bookir: BookIR,
    profile: BookStyleProfile | None = None,
) -> tuple[BookIR, NormalizationReport]:
    """
    Run typography, whitespace reconstruction, and list normalization on BookIR.
    Returns (normalized_bookir, normalization_report).
    """
    report = NormalizationReport()
    normalized_blocks: list[Block] = []

    for block in bookir.blocks:
        normalized_blocks.append(normalize_block(block, report, profile))

    normalized_ir = bookir.model_copy(update={"blocks": normalized_blocks})
    return normalized_ir, report


def reconstruct_text_from_source_segments(
    segments: Sequence[SourceTextSegment],
    block_id: str = "",
) -> str:
    """
    Reconstruct visible text from a sequence of SourceTextSegments using authoritative
    M11 boundary classification and spacing rules.
    """
    if not segments:
        return ""
    temp_inline = Text(text="", source_segments=list(segments))
    report = NormalizationReport()
    normalized = reconstruct_text_inline(temp_inline, block_id=block_id, report=report)
    return normalized.text
