"""Semantic QA evaluation, preservation ledger, and outline checks (M12/Appendix N2-N4)."""

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree

from book2epub.ir.models import (
    Aside,
    Block,
    BlockQuote,
    BookIR,
    Callout,
    Chart,
    CodeBlock,
    DisplayMath,
    ExampleBlock,
    ExerciseBlock,
    Figure,
    Footnote,
    Heading,
    Inline,
    ListBlock,
    Paragraph,
    PreformattedBlock,
    Table,
    Text,
    UnknownBlock,
    extract_inline_visible_text,
)
from book2epub.qa.models import (
    DispositionStr,
    PreservationLedgerEntry,
    QAViolation,
    SemanticQAMetrics,
)
from book2epub.semantic.decisions import SemanticAuditRecord
from book2epub.semantic.hashing import compute_content_sha256, compute_text_sha256
from book2epub.semantic.models import SemanticEvidenceBook
from book2epub.semantic.structure import BookOutline
from book2epub.typography import reconstruct_text_from_source_segments
from book2epub.typography.japanese import classify_char
from book2epub.typography.models import CharClass
from book2epub.visual.models import OCRAuditRecord

logger = logging.getLogger(__name__)


def _apply_ocr_to_inline_snapshot(
    snapshot: list[dict[str, Any]],
    applied_ocr: dict[tuple[str, str], str],
    block_id: str,
) -> str:
    """
    Deserialize a caption/footnote inline snapshot, apply OCR text replacements to
    Text nodes (matching by block_id + segment_id), then extract visible text including
    InlineMath latex, LineBreak newlines, and Hyperlink children.

    This preserves non-Text inline content (InlineMath, LineBreak, Hyperlink) that
    reconstruct_text_from_source_segments() would silently drop.

    Text.text in the snapshot is the adapter-normalized (join_prose_texts-stripped) value.
    When no OCR replacement applies to a Text node, keep Text.text unchanged so that
    expected and actual both use the same stripped representation.
    When an OCR replacement applies, rebuild Text.text via join_prose_texts to stay
    consistent with adapter normalization.
    """
    from pydantic import TypeAdapter

    from book2epub.ir.text_join import join_prose_texts

    _inline_adapter: TypeAdapter[Inline] = TypeAdapter(Inline)
    updated_inlines: list[Inline] = []
    for d in snapshot:
        try:
            inl = _inline_adapter.validate_python(d)
        except Exception:
            continue
        if isinstance(inl, Text) and inl.source_segments:
            replaced_ids = {
                s.segment_id
                for s in inl.source_segments
                if (block_id, s.segment_id) in applied_ocr
            }
            if replaced_ids:
                # OCR was applied: rebuild from segment texts using same normalization
                new_segs = [
                    s.model_copy(update={"text": applied_ocr[(block_id, s.segment_id)]})
                    if (block_id, s.segment_id) in applied_ocr
                    else s
                    for s in inl.source_segments
                ]
                new_text = join_prose_texts([s.text for s in new_segs])
                inl = inl.model_copy(update={"text": new_text, "source_segments": new_segs})
            # else: keep inl.text as-is (adapter-normalized, matches actual extraction)
        updated_inlines.append(inl)
    return extract_inline_visible_text(updated_inlines)

_CJK_CLASSES = frozenset({
    CharClass.CJK_HAN_KANA,
    CharClass.OPEN_JP_PUNCT,
    CharClass.CLOSE_JP_PUNCT,
})


def _is_cjk_boundary_spacing_difference(t1: str, t2: str) -> bool:
    """
    Check if the only differences between t1 and t2 are whitespace additions/removals
    where every difference is at an immediate boundary of a CJK or Japanese punctuation char.
    Abolishes unconditional whitespace removal so Latin spacing changes (e.g. 'foo bar' -> 'foobar')
    are strictly rejected as text corruption.
    """
    tokens1 = re.findall(r"(\S)(\s*)", t1)
    tokens2 = re.findall(r"(\S)(\s*)", t2)
    if len(tokens1) != len(tokens2):
        return False

    for idx in range(len(tokens1)):
        c1, s1 = tokens1[idx]
        c2, s2 = tokens2[idx]
        if c1 != c2:
            return False
        if idx < len(tokens1) - 1:
            has_space1 = bool(s1)
            has_space2 = bool(s2)
            if has_space1 != has_space2:
                next_c = tokens1[idx + 1][0]
                cls1 = classify_char(c1)
                cls_next = classify_char(next_c)
                if cls1 not in _CJK_CLASSES and cls_next not in _CJK_CLASSES:
                    return False
    return True


def is_acceptable_text_preservation(expected_text: str, final_text: str) -> bool:
    """
    Determine whether final_text is an acceptable preservation of expected_text.
    Allows exact match, whitespace collapse, and spacing differences exclusively at CJK boundaries.
    Strictly forbids spacing changes between Latin/ASCII word or digit characters.
    """
    if expected_text == final_text:
        return True
    norm_expected = re.sub(r"\s+", " ", expected_text).strip()
    norm_final = re.sub(r"\s+", " ", final_text).strip()
    if norm_expected == norm_final:
        return True
    return _is_cjk_boundary_spacing_difference(expected_text.strip(), final_text.strip())


# Authoritative inline visible text extractor
extract_inlines_text = extract_inline_visible_text


def compute_final_block_hashes(block: Block) -> tuple[str, str]:
    """
    Compute (canonical_text, final_content_sha256) for a BookIR block from actual node content.
    Matches the deterministic hash construction used in M6 evidence.
    """
    plain_text = None
    preformatted_text = None
    table_html = None
    caption_text = None
    footnote_text = None

    if isinstance(block, (Paragraph, Heading, Aside, Footnote)):
        plain_text = extract_inlines_text(block.inlines)
    elif isinstance(block, PreformattedBlock):
        preformatted_text = block.text
        if block.caption:
            caption_text = extract_inlines_text(block.caption)
        if block.footnotes:
            footnote_text = extract_inlines_text(block.footnotes)
    elif isinstance(block, CodeBlock):
        preformatted_text = block.text
        if block.caption:
            caption_text = extract_inlines_text(block.caption)
        if block.footnotes:
            footnote_text = extract_inlines_text(block.footnotes)
    elif isinstance(block, Table):
        table_html = block.html
        if block.caption:
            caption_text = extract_inlines_text(block.caption)
        if block.footnotes:
            footnote_text = extract_inlines_text(block.footnotes)
    elif isinstance(block, (Figure, Chart)):
        if block.caption:
            caption_text = extract_inlines_text(block.caption)
        if block.footnotes:
            footnote_text = extract_inlines_text(block.footnotes)
    elif isinstance(block, DisplayMath):
        plain_text = block.latex
    elif isinstance(block, ListBlock):
        item_texts = [extract_inlines_text(item) for item in block.items]
        plain_text = "\n".join(item_texts)
    elif isinstance(block, (Callout, BlockQuote, ExampleBlock, ExerciseBlock)):
        inner_texts: list[str] = []
        for inner in block.blocks:
            txt, _ = compute_final_block_hashes(inner)
            if txt:
                inner_texts.append(txt)
        plain_text = "\n".join(inner_texts)
    elif isinstance(block, UnknownBlock):
        plain_text = block.extracted_text or ""

    canonical_text = plain_text or preformatted_text or table_html or caption_text or ""
    content_hash = compute_content_sha256(
        plain_text=plain_text,
        preformatted_text=preformatted_text,
        table_html_text_content=table_html,
        caption_text=caption_text,
        footnote_text=footnote_text,
    )
    return canonical_text, content_hash


def flatten_ir_blocks(
    blocks: list[Block],
    parent_container_id: str | None = None,
) -> list[tuple[Block, str | None]]:
    """
    Recursively traverse BookIR blocks and return all (block, parent_container_id) pairs.
    Supports containers: Callout, BlockQuote, ExampleBlock, ExerciseBlock.
    """
    result: list[tuple[Block, str | None]] = []
    for b in blocks:
        result.append((b, parent_container_id))
        if isinstance(b, (Callout, BlockQuote, ExampleBlock, ExerciseBlock)):
            result.extend(flatten_ir_blocks(b.blocks, parent_container_id=b.id))
    return result


def build_preservation_ledger(
    evidence: SemanticEvidenceBook | None,
    bookir: BookIR,
    audits: list[SemanticAuditRecord] | None = None,
    ocr_audits: list[Any] | None = None,
) -> list[PreservationLedgerEntry]:
    """
    Construct disposition accounting ledger for all source evidence blocks (Appendix N2).
    Calculates real final hashes from final BookIR nodes and checks representation invariants.
    """
    ledger: list[PreservationLedgerEntry] = []
    flat_blocks = flatten_ir_blocks(bookir.blocks)
    final_blocks_by_id: dict[str, tuple[Block, str | None]] = {
        b.id: (b, parent_id) for b, parent_id in flat_blocks
    }

    # Map semantic decisions by block_id (fix: record decision_id, not block_id)
    audit_ids_by_block: dict[str, list[str]] = {}
    audits_by_block: dict[str, list[SemanticAuditRecord]] = {}
    if audits:
        for a in audits:
            dec_id = a.decision_id if a.decision_id else a.block_id
            audit_ids_by_block.setdefault(a.block_id, []).append(dec_id)
            audits_by_block.setdefault(a.block_id, []).append(a)

    # Map OCR corrections by (block_id, segment_id)
    ocr_ids_by_block: dict[str, list[str]] = {}
    applied_ocr_by_seg: dict[tuple[str, str], str] = {}
    if ocr_audits:
        for oa in ocr_audits:
            b_id = getattr(oa, "block_id", "")
            s_id = getattr(oa, "segment_id", "")
            if b_id:
                ocr_ids_by_block.setdefault(b_id, []).append(s_id or b_id)
                if getattr(oa, "status", "") == "applied":
                    applied_ocr_by_seg[(b_id, s_id)] = getattr(oa, "new_text", "")

    if evidence:
        for ev in evidence.blocks:
            found = final_blocks_by_id.get(ev.block_id)
            if found is not None:
                final_block, parent_id = found
                final_kind = final_block.kind
                final_text, final_content_hash = compute_final_block_hashes(final_block)

                final_assets: list[str] = []
                if hasattr(final_block, "asset_id") and getattr(final_block, "asset_id"):
                    final_assets.append(getattr(final_block, "asset_id"))
                if hasattr(final_block, "fallback_asset_id") and getattr(
                    final_block, "fallback_asset_id"
                ):
                    final_assets.append(getattr(final_block, "fallback_asset_id"))

                reason = ""
                if parent_id is not None:
                    disposition = DispositionStr("moved_into_container")
                    final_bids = [parent_id, final_block.id]
                    reason = f"Moved into container '{parent_id}'"
                elif (
                    final_kind == ev.source_type
                    or (ev.source_type == "title" and final_kind == "heading")
                    or (ev.source_type == "text" and final_kind == "paragraph")
                ):
                    disposition = DispositionStr("unchanged")
                    final_bids = [final_block.id]
                    reason = "Preserved with same semantic type"
                else:
                    disposition = DispositionStr("retyped")
                    final_bids = [final_block.id]
                    reason = f"Retyped from {ev.source_type} to {final_kind}"

                # Representation-aware text verification
                is_same_repr = (
                    (
                        ev.source_type in ("text", "paragraph")
                        and final_kind in ("paragraph", "heading")
                    )
                    or (
                        ev.source_type in ("title", "heading")
                        and final_kind in ("heading", "paragraph")
                    )
                    or (
                        ev.source_type in ("code", "algorithm")
                        and final_kind in ("code", "preformatted")
                    )
                    or (ev.source_type == "preformatted" and final_kind == "preformatted")
                    or (ev.source_type == "table" and final_kind == "table")
                )

                if is_same_repr:
                    if ev.source_type == "table" and final_kind == "table":
                        expected_text = ev.table_html or ""
                    else:
                        has_applied_ocr = False
                        if ev.source_segments:
                            eff_segments = []
                            for seg in ev.source_segments:
                                if (ev.block_id, seg.segment_id) in applied_ocr_by_seg:
                                    eff_segments.append(
                                        seg.model_copy(
                                            update={
                                                "text": applied_ocr_by_seg[
                                                    (ev.block_id, seg.segment_id)
                                                ]
                                            }
                                        )
                                    )
                                    has_applied_ocr = True
                                else:
                                    eff_segments.append(seg)
                            if has_applied_ocr:
                                expected_text = reconstruct_text_from_source_segments(
                                    eff_segments, block_id=ev.block_id
                                )
                            else:
                                expected_text = ev.plain_text or ev.preformatted_text or ""
                        else:
                            matched_ocr = [
                                new_t
                                for (b_id, _), new_t in applied_ocr_by_seg.items()
                                if b_id == ev.block_id
                            ]
                            if matched_ocr and len(matched_ocr) == 1:
                                expected_text = matched_ocr[0]
                            else:
                                expected_text = ev.plain_text or ev.preformatted_text or ""

                    is_code_like = (
                        ev.source_type in ("code", "algorithm", "preformatted")
                        or final_kind in ("code", "preformatted")
                    )
                    if is_code_like:
                        norm_exp = expected_text.replace("\r\n", "\n")
                        norm_fin = final_text.replace("\r\n", "\n")
                        if norm_exp != norm_fin:
                            reason = (
                                f"Text mismatch in same-representation block: "
                                f"source '{expected_text[:30]}' != final '{final_text[:30]}'"
                            )
                    else:
                        if expected_text and compute_text_sha256(final_text) != compute_text_sha256(
                            expected_text
                        ):
                            if not is_acceptable_text_preservation(expected_text, final_text):
                                reason = (
                                    f"Text mismatch in same-representation block: "
                                    f"source '{expected_text[:30]}' != final '{final_text[:30]}'"
                                )
                elif ev.source_type == "table" and final_kind in ("preformatted", "code"):
                    # Table -> terminal/code justified representation change
                    ev_pre = ev.preformatted_text or ""
                    ev_plain = ev.plain_text or ""
                    ev_tbl = ev.table_html or ""
                    if (
                        final_text == ev_pre
                        or final_text == ev_plain
                        or (final_text and final_text in ev_tbl)
                    ):
                        reason = (
                            f"Justified representation change from {ev.source_type} "
                            f"to {final_kind} derived from source evidence"
                        )
                    else:
                        reason = (
                            f"Fabricated text: content of retyped {final_kind} does not "
                            f"originate from source evidence"
                        )

                ledger.append(
                    PreservationLedgerEntry(
                        source_block_id=ev.block_id,
                        source_kind=ev.source_type,
                        source_content_sha256=ev.content_sha256,
                        final_block_ids=final_bids,
                        final_kinds=[final_kind],
                        final_content_sha256s=[final_content_hash],
                        disposition=disposition,
                        source_asset_ids=ev.asset_ids,
                        final_asset_ids=final_assets,
                        semantic_decision_ids=audit_ids_by_block.get(ev.block_id, []),
                        ocr_correction_ids=ocr_ids_by_block.get(ev.block_id, []),
                        reason=reason,
                    )
                )
            else:
                # Block not found by primary ID: trace merges, containers, boilerplate, or loss
                # 1. Trace cross-page paragraph merges
                merged_dest = None
                if ev.source_type in ("text", "paragraph"):
                    for b, _ in flat_blocks:
                        if isinstance(b, Paragraph):
                            has_seg_provenance = False
                            for inl in b.inlines:
                                if isinstance(inl, Text):
                                    if any(
                                        seg.block_id == ev.block_id for seg in inl.source_segments
                                    ):
                                        has_seg_provenance = True
                                        break
                                if any(
                                    getattr(s, "block_id", "") == ev.block_id
                                    for s in getattr(inl, "sources", [])
                                ):
                                    has_seg_provenance = True
                                    break
                            if not has_seg_provenance:
                                if any(
                                    getattr(s, "block_id", "") == ev.block_id
                                    for s in getattr(b, "sources", [])
                                ):
                                    has_seg_provenance = True

                            if has_seg_provenance:
                                merged_dest = b
                                break

                if merged_dest is not None:
                    dest_text, dest_hash = compute_final_block_hashes(merged_dest)
                    disposition = DispositionStr("paragraph_merged")
                    reason = (
                        f"Cross-page paragraph merged into '{merged_dest.id}' with text preserved"
                    )
                    ledger.append(
                        PreservationLedgerEntry(
                            source_block_id=ev.block_id,
                            source_kind=ev.source_type,
                            source_content_sha256=ev.content_sha256,
                            final_block_ids=[merged_dest.id],
                            final_kinds=[merged_dest.kind],
                            final_content_sha256s=[dest_hash],
                            disposition=disposition,
                            source_asset_ids=ev.asset_ids,
                            final_asset_ids=[],
                            semantic_decision_ids=audit_ids_by_block.get(ev.block_id, []),
                            ocr_correction_ids=ocr_ids_by_block.get(ev.block_id, []),
                            reason=reason,
                        )
                    )
                    continue

                # 2. Trace boilerplate suppression
                if ev.source_type in ("header", "footer", "page_number"):
                    disposition = DispositionStr("intentionally_suppressed_boilerplate")
                    reason = f"Source {ev.source_type} suppressed as boilerplate"
                    ledger.append(
                        PreservationLedgerEntry(
                            source_block_id=ev.block_id,
                            source_kind=ev.source_type,
                            source_content_sha256=ev.content_sha256,
                            final_block_ids=[],
                            final_kinds=[],
                            final_content_sha256s=[],
                            disposition=disposition,
                            source_asset_ids=ev.asset_ids,
                            final_asset_ids=[],
                            semantic_decision_ids=audit_ids_by_block.get(ev.block_id, []),
                            ocr_correction_ids=[],
                            reason=reason,
                        )
                    )
                    continue

                # 3. Trace semantic supersession (e.g. table fallback image -> HTML table)
                # Restrict to same-source relations: explicit audit retype, or fallback asset ID
                # matched by specific Table
                matching_replacement: Block | None = None
                if ev.source_type in ("table_fallback", "image"):
                    for b, _ in flat_blocks:
                        if isinstance(b, Table):
                            if b.fallback_asset_id and (
                                b.fallback_asset_id in ev.asset_ids
                                or b.fallback_asset_id == ev.block_id
                            ):
                                matching_replacement = b
                                break

                applied_table_retype = any(
                    a.status == "applied"
                    and (
                        a.final_target in ("table", "callout", "aside", "blockquote")
                        or getattr(a, "target", "") in ("table", "callout", "aside", "blockquote")
                    )
                    for a in audits_by_block.get(ev.block_id, [])
                )
                if matching_replacement is None and applied_table_retype:
                    # Look for resolved replacement block in flat_blocks
                    for b, _ in flat_blocks:
                        if any(
                            getattr(s, "block_id", "") == ev.block_id
                            for s in getattr(b, "sources", [])
                        ):
                            matching_replacement = b
                            break

                if matching_replacement is not None:
                    disposition = DispositionStr("semantically_superseded")
                    reason = (
                        f"Source representation superseded by structured semantic equivalent "
                        f"'{matching_replacement.id}'"
                    )
                    ledger.append(
                        PreservationLedgerEntry(
                            source_block_id=ev.block_id,
                            source_kind=ev.source_type,
                            source_content_sha256=ev.content_sha256,
                            final_block_ids=[matching_replacement.id],
                            final_kinds=[matching_replacement.kind],
                            final_content_sha256s=[],
                            disposition=disposition,
                            source_asset_ids=ev.asset_ids,
                            final_asset_ids=[],
                            semantic_decision_ids=audit_ids_by_block.get(ev.block_id, []),
                            ocr_correction_ids=[],
                            reason=reason,
                        )
                    )
                    continue

                # 4. Block genuinely lost
                disposition = DispositionStr("lost_error")
                reason = (
                    f"Source evidence block '{ev.block_id}' ({ev.source_type}) "
                    f"missing from final BookIR"
                )
                ledger.append(
                    PreservationLedgerEntry(
                        source_block_id=ev.block_id,
                        source_kind=ev.source_type,
                        source_content_sha256=ev.content_sha256,
                        final_block_ids=[],
                        final_kinds=[],
                        final_content_sha256s=[],
                        disposition=disposition,
                        source_asset_ids=ev.asset_ids,
                        final_asset_ids=[],
                        semantic_decision_ids=audit_ids_by_block.get(ev.block_id, []),
                        ocr_correction_ids=[],
                        reason=reason,
                    )
                )
    else:
        # Fallback without evidence: compute real hash for every BookIR block
        for b in bookir.blocks:
            b_assets: list[str] = getattr(b, "asset_id", None) or []
            if isinstance(b_assets, str):
                b_assets = [b_assets]
            _, real_hash = compute_final_block_hashes(b)
            ledger.append(
                PreservationLedgerEntry(
                    source_block_id=b.id,
                    source_kind=b.kind,
                    source_content_sha256=real_hash,
                    final_block_ids=[b.id],
                    final_kinds=[b.kind],
                    final_content_sha256s=[real_hash],
                    disposition=DispositionStr("unchanged"),
                    source_asset_ids=b_assets,
                    final_asset_ids=b_assets,
                    reason="Preserved without evidence baseline",
                )
            )

    return ledger


def evaluate_preservation_qa(
    ledger: list[PreservationLedgerEntry],
    evidence: SemanticEvidenceBook | None,
    bookir: BookIR,
    ocr_audits: list[OCRAuditRecord] | None = None,
) -> list[QAViolation]:
    """
    Assert preservation invariants across ledger entries (Appendix N2).
    Checks for content loss, fabricated text, unexplained asset loss,
    footnote loss, caption loss, and footnote/caption corruption.
    """
    violations: list[QAViolation] = []
    evidence_lookup = {b.block_id: b for b in evidence.blocks} if evidence else {}
    flat_blocks = flatten_ir_blocks(bookir.blocks)
    final_blocks_by_id: dict[str, tuple[Block, str | None]] = {
        b.id: (b, pid) for b, pid in flat_blocks
    }

    applied_ocr: dict[tuple[str, str], str] = {}
    if ocr_audits:
        for a in ocr_audits:
            if a.status == "applied":
                applied_ocr[(a.block_id, a.segment_id)] = a.new_text

    for entry in ledger:
        # 1. Content Loss
        if entry.disposition == "lost_error":
            violations.append(
                QAViolation(
                    category="preservation",
                    severity="fatal",
                    code="CONTENT_LOSS",
                    message=entry.reason or f"Source block '{entry.source_block_id}' lost",
                    block_id=entry.source_block_id,
                )
            )

        # 2. Fabricated Text or Corruption
        if "Fabricated text" in entry.reason:
            violations.append(
                QAViolation(
                    category="preservation",
                    severity="fatal",
                    code="FABRICATED_REPRESENTATION_TEXT",
                    message=entry.reason,
                    block_id=entry.source_block_id,
                )
            )
        elif "Text mismatch" in entry.reason:
            violations.append(
                QAViolation(
                    category="preservation",
                    severity="fatal",
                    code="TEXT_FABRICATION_OR_CORRUPTION",
                    message=entry.reason,
                    block_id=entry.source_block_id,
                )
            )

        # 3. Unexplained Asset Loss
        if (
            entry.source_kind in ("image", "chart", "figure")
            and entry.source_asset_ids
            and not entry.final_asset_ids
            and entry.disposition != "semantically_superseded"
        ):
            violations.append(
                QAViolation(
                    category="preservation",
                    severity="fatal",
                    code="UNEXPLAINED_ASSET_LOSS",
                    message=(
                        f"Asset(s) {entry.source_asset_ids} from '{entry.source_block_id}' "
                        f"disappeared without semantic supersession"
                    ),
                    block_id=entry.source_block_id,
                )
            )

        # 4. Footnote loss & corruption (per-block)
        ev = evidence_lookup.get(entry.source_block_id)
        if ev and (ev.footnote_text or ev.footnote_plain_text):
            expected_fn = ev.footnote_plain_text or ev.footnote_text or ""
            fn_segs = ev.footnote_source_segments or [
                s
                for s in (ev.source_segments or [])
                if s.source_span_type == "footnote" or "fn" in s.segment_id.lower()
            ]
            if ev.footnote_inlines_snapshot:
                # Preferred path: apply OCR replacements to the full inline structure
                # (preserves InlineMath, LineBreak, Hyperlink that segments miss)
                expected_fn = _apply_ocr_to_inline_snapshot(
                    ev.footnote_inlines_snapshot, applied_ocr, ev.block_id
                )
            elif fn_segs:
                eff_fn_segs = [
                    s.model_copy(update={"text": applied_ocr[(ev.block_id, s.segment_id)]})
                    if (ev.block_id, s.segment_id) in applied_ocr
                    else s
                    for s in fn_segs
                ]
                expected_fn = reconstruct_text_from_source_segments(
                    eff_fn_segs, block_id=ev.block_id
                )

            final_fn_block: Footnote | None = None
            final_fn_container: Block | None = None
            for bid in entry.final_block_ids:
                fb_entry = final_blocks_by_id.get(bid)
                if fb_entry:
                    fb, _ = fb_entry
                    if isinstance(fb, Footnote):
                        final_fn_block = fb
                        break
                    if getattr(fb, "footnotes", None):
                        final_fn_container = fb
                        break
            if final_fn_block is None and final_fn_container is None:
                for b, _ in flat_blocks:
                    if isinstance(b, Footnote):
                        if b.id == entry.source_block_id or any(
                            getattr(s, "block_id", "") == entry.source_block_id
                            for s in getattr(b, "sources", [])
                        ):
                            final_fn_block = b
                            break

            if final_fn_block is None and final_fn_container is None:
                violations.append(
                    QAViolation(
                        category="preservation",
                        severity="error",
                        code="FOOTNOTE_LOSS",
                        message=f"Footnote text for block '{entry.source_block_id}' was lost",
                        block_id=entry.source_block_id,
                    )
                )
            else:
                actual_fn_text = ""
                if final_fn_block:
                    actual_fn_text = extract_inlines_text(final_fn_block.inlines)
                elif final_fn_container:
                    actual_fn_text = extract_inlines_text(getattr(final_fn_container, "footnotes"))

                if not actual_fn_text.strip():
                    violations.append(
                        QAViolation(
                            category="preservation",
                            severity="error",
                            code="FOOTNOTE_LOSS",
                            message=f"Footnote text for block '{entry.source_block_id}' was empty",
                            block_id=entry.source_block_id,
                        )
                    )
                elif not is_acceptable_text_preservation(expected_fn, actual_fn_text):
                    violations.append(
                        QAViolation(
                            category="preservation",
                            severity="error",
                            code="FOOTNOTE_CORRUPTION",
                            message=(
                                f"Footnote content corrupted for block '{entry.source_block_id}': "
                                f"expected '{expected_fn[:30]}', got '{actual_fn_text[:30]}'"
                            ),
                            block_id=entry.source_block_id,
                        )
                    )

        # 5. Caption loss & corruption (per-block)
        if ev and (ev.caption_text or ev.caption_plain_text):
            expected_cap = ev.caption_plain_text or ev.caption_text or ""
            cap_segs = ev.caption_source_segments or [
                s
                for s in (ev.source_segments or [])
                if s.source_span_type == "caption" or "caption" in s.segment_id.lower()
            ]
            if ev.caption_inlines_snapshot:
                # Preferred path: apply OCR replacements to the full inline structure
                # (preserves InlineMath, LineBreak, Hyperlink that segments miss)
                expected_cap = _apply_ocr_to_inline_snapshot(
                    ev.caption_inlines_snapshot, applied_ocr, ev.block_id
                )
            elif cap_segs:
                eff_cap_segs = [
                    s.model_copy(update={"text": applied_ocr[(ev.block_id, s.segment_id)]})
                    if (ev.block_id, s.segment_id) in applied_ocr
                    else s
                    for s in cap_segs
                ]
                expected_cap = reconstruct_text_from_source_segments(
                    eff_cap_segs, block_id=ev.block_id
                )

            final_cap_block: Block | None = None
            for bid in entry.final_block_ids:
                fb_entry = final_blocks_by_id.get(bid)
                if fb_entry:
                    fb, _ = fb_entry
                    if getattr(fb, "caption", None):
                        final_cap_block = fb
                        break
            if final_cap_block is None:
                for b, _ in flat_blocks:
                    if getattr(b, "caption", None):
                        if b.id == entry.source_block_id or any(
                            getattr(s, "block_id", "") == entry.source_block_id
                            for s in getattr(b, "sources", [])
                        ):
                            final_cap_block = b
                            break

            if final_cap_block is None:
                violations.append(
                    QAViolation(
                        category="preservation",
                        severity="error",
                        code="CAPTION_LOSS",
                        message=f"Caption text for block '{entry.source_block_id}' was lost",
                        block_id=entry.source_block_id,
                    )
                )
            else:
                actual_cap_text = extract_inlines_text(getattr(final_cap_block, "caption"))
                if not actual_cap_text.strip():
                    violations.append(
                        QAViolation(
                            category="preservation",
                            severity="error",
                            code="CAPTION_LOSS",
                            message=f"Caption text for block '{entry.source_block_id}' was empty",
                            block_id=entry.source_block_id,
                        )
                    )
                elif not is_acceptable_text_preservation(expected_cap, actual_cap_text):
                    violations.append(
                        QAViolation(
                            category="preservation",
                            severity="error",
                            code="CAPTION_CORRUPTION",
                            message=(
                                f"Caption content corrupted for block '{entry.source_block_id}': "
                                f"expected '{expected_cap[:30]}', got '{actual_cap_text[:30]}'"
                            ),
                            block_id=entry.source_block_id,
                        )
                    )

    return violations


def evaluate_semantic_transitions(
    evidence: SemanticEvidenceBook | None,
    bookir: BookIR,
    audits: list[SemanticAuditRecord] | None,
    outline: BookOutline | None = None,
) -> SemanticQAMetrics:
    """Evaluate semantic reconstruction rates, transitions, and outline coverage."""
    metrics = SemanticQAMetrics()
    if not audits:
        return metrics

    total_audits = len(audits)
    if total_audits == 0:
        return metrics

    metrics.semantic_review_rate = 1.0
    applied_audits = [a for a in audits if a.status in ("applied", "visual_override_applied")]
    metrics.semantic_auto_apply_rate = round(len(applied_audits) / total_audits, 4)

    changed_count = 0
    transitions: Counter[str] = Counter()

    for a in audits:
        if a.source_kind != a.final_target:
            changed_count += 1
            if a.status in ("applied", "visual_override_applied"):
                transitions[f"{a.source_kind} -> {a.final_target}"] += 1

    metrics.semantic_change_rate = round(changed_count / total_audits, 4)
    metrics.type_transitions = dict(transitions)

    conflict_count = sum(1 for a in audits if a.status == "preserved_original_conflict")
    metrics.semantic_conflict_rate = round(conflict_count / total_audits, 4)

    unres_count = sum(1 for a in audits if a.status.startswith("preserved_original"))
    metrics.semantic_unresolved_rate = round(unres_count / total_audits, 4)

    invalid_count = sum(1 for a in audits if a.status.startswith("rejected_"))
    metrics.semantic_invalid_decision_rate = round(invalid_count / total_audits, 4)

    visual_reviews = sum(
        1 for a in audits if a.status in ("queued_visual_review", "visual_override_applied")
    )
    metrics.semantic_visual_review_rate = round(visual_reviews / total_audits, 4)

    # Heading / Outline checks
    flat_blocks = [b for b, _ in flatten_ir_blocks(bookir.blocks)]
    headings = [b for b in flat_blocks if isinstance(b, Heading)]
    known_levels = sum(1 for h in headings if h.level is not None)
    metrics.heading_level_known_rate = round(known_levels / max(1, len(headings)), 4)

    if outline:
        _, outline_violations = evaluate_outline_qa(outline, bookir)
        metrics.outline_cycle_count = sum(
            1 for v in outline_violations if v.code == "OUTLINE_CYCLE_DETECTED"
        )
        metrics.outline_monotonic_error_count = sum(
            1 for v in outline_violations if v.code == "OUTLINE_NON_MONOTONIC"
        )
        metrics.outline_unresolved_target_count = sum(
            1
            for v in outline_violations
            if v.code in ("OUTLINE_UNRESOLVED_HEADING", "BROKEN_TOC_TARGET")
        )
        all_h_ids = {h.id for h in headings}
        covered_h_ids = {
            n.heading_block_id for n in outline.nodes.values() if n.heading_block_id in all_h_ids
        }
        metrics.outline_coverage_rate = (
            round(len(covered_h_ids) / len(all_h_ids), 4) if all_h_ids else 1.0
        )

    return metrics


def evaluate_outline_qa(
    outline: BookOutline,
    bookir: BookIR,
    oebps_dir: Path | None = None,
    toc_entries: list[Any] | None = None,
) -> tuple[bool, list[QAViolation]]:
    """
    Perform rigorous verification of BookOutline and TOC integrity.

    Verifies resolution, duplicates, hierarchy, cycle detection, monotonicity,
    and XHTML TOC targets.
    """
    violations: list[QAViolation] = []
    flat_blocks = [b for b, _ in flatten_ir_blocks(bookir.blocks)]
    headings_in_order = [b for b in flat_blocks if isinstance(b, Heading)]
    heading_ids = {h.id for h in headings_in_order}
    heading_order_map = {h.id: idx for idx, h in enumerate(headings_in_order)}

    seen_headings: set[str] = set()

    for node_id, node in outline.nodes.items():
        # 1. Unresolved heading ID
        if node.heading_block_id not in heading_ids:
            violations.append(
                QAViolation(
                    category="outline",
                    severity="error",
                    code="OUTLINE_UNRESOLVED_HEADING",
                    message=f"Outline heading_id '{node.heading_block_id}' not found in BookIR",
                    block_id=node.heading_block_id,
                )
            )

        # 2. Duplicate heading in outline
        if node.heading_block_id in seen_headings:
            violations.append(
                QAViolation(
                    category="outline",
                    severity="error",
                    code="OUTLINE_DUPLICATE_HEADING",
                    message=f"Duplicate heading in outline: '{node.heading_block_id}'",
                    block_id=node.heading_block_id,
                )
            )
        seen_headings.add(node.heading_block_id)

        # 3. Parent level < child level
        if node.parent_node_id:
            parent = outline.nodes.get(node.parent_node_id)
            if parent and parent.level >= node.level:
                violations.append(
                    QAViolation(
                        category="outline",
                        severity="error",
                        code="OUTLINE_INVALID_HIERARCHY",
                        message=(
                            f"Parent level ({parent.level}) must be less than child level "
                            f"({node.level}) for node '{node_id}'"
                        ),
                        block_id=node.heading_block_id,
                    )
                )

        # 4. Cycle detection
        visited_ancestors: set[str] = set()
        curr: str | None = node_id
        while curr:
            if curr in visited_ancestors:
                violations.append(
                    QAViolation(
                        category="outline",
                        severity="fatal",
                        code="OUTLINE_CYCLE_DETECTED",
                        message=f"Cycle detected in outline hierarchy involving node '{curr}'",
                        block_id=node.heading_block_id,
                    )
                )
                break
            visited_ancestors.add(curr)
            curr_node = outline.nodes.get(curr)
            curr = curr_node.parent_node_id if curr_node else None

    # 5. Monotonicity check (outline sequence matches document reading order)
    last_pos = -1
    for node_id, node in outline.nodes.items():
        pos = heading_order_map.get(node.heading_block_id)
        if pos is not None:
            if pos < last_pos:
                violations.append(
                    QAViolation(
                        category="outline",
                        severity="error",
                        code="OUTLINE_NON_MONOTONIC",
                        message=(
                            f"Outline node '{node_id}' (heading '{node.heading_block_id}') "
                            f"appears non-monotonically in document order (pos {pos} < {last_pos})"
                        ),
                        block_id=node.heading_block_id,
                    )
                )
            last_pos = pos

    # 6. TOC target fragment resolution in XHTML
    if oebps_dir and oebps_dir.is_dir() and toc_entries:
        for entry in toc_entries:
            href = getattr(entry, "href", "")
            if "#" in href:
                file_part, frag_id = href.split("#", 1)
                xhtml_file = oebps_dir / file_part
                if not xhtml_file.is_file():
                    violations.append(
                        QAViolation(
                            category="outline",
                            severity="fatal",
                            code="BROKEN_TOC_TARGET",
                            message=(
                                f"TOC target file '{file_part}' does not exist in rendered EPUB"
                            ),
                        )
                    )
                else:
                    try:
                        tree = etree.parse(str(xhtml_file))
                        found_target = tree.xpath(f"//*[@id='{frag_id}']")
                        if not found_target:
                            violations.append(
                                QAViolation(
                                    category="outline",
                                    severity="fatal",
                                    code="BROKEN_TOC_TARGET",
                                    message=(
                                        f"TOC target fragment '#{frag_id}' not found "
                                        f"in '{file_part}'"
                                    ),
                                )
                            )
                    except Exception as e:
                        violations.append(
                            QAViolation(
                                category="outline",
                                severity="fatal",
                                code="BROKEN_TOC_TARGET",
                                message=f"Failed to parse XHTML for TOC validation: {e}",
                            )
                        )

    passed = len(violations) == 0
    return passed, violations


def validate_outline_qa(outline: BookOutline, bookir: BookIR) -> tuple[bool, list[str]]:
    """Legacy compatibility adapter returning (passed, warnings as strings)."""
    passed, violations = evaluate_outline_qa(outline, bookir)
    return passed, [v.message for v in violations]
