"""Canonical allowed-target/materializer contract tests."""

import inspect

import pytest

from book2epub.ir.models import (
    Aside,
    CodeBlock,
    Heading,
    Hyperlink,
    InlineMath,
    Paragraph,
    PreformattedBlock,
    SourceRef,
    SourceTextSegment,
    Table,
    Text,
)
from book2epub.semantic.apply import apply_semantic_decisions, extract_block_visible_text
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.materializers import allowed_targets_for, materializer_for
from book2epub.semantic.models import SemanticEvidenceBlock
from book2epub.semantic.reconcile import ReconciledSemanticDecision


def _source() -> list[SourceRef]:
    return [SourceRef(page_idx=0, source_type="text")]


def _evidence(
    block_id: str,
    *,
    plain: str = "",
    preformatted: str | None = None,
    table_html: str | None = None,
) -> SemanticEvidenceBlock:
    return SemanticEvidenceBlock(
        block_id=block_id,
        plain_text=plain,
        preformatted_text=preformatted,
        table_html=table_html,
        table_html_available=bool(table_html),
    )


def _decision(
    block_id: str, target: str, heading_level: int | None = None
) -> ReconciledSemanticDecision:
    return ReconciledSemanticDecision(
        block_id=block_id,
        target=target,  # type: ignore[arg-type]
        heading_level=heading_level,
        confidence=0.95,
    )


def _authorized(block: object, evidence: SemanticEvidenceBlock) -> SemanticEvidenceBlock:
    return evidence.model_copy(
        update={"allowed_targets": allowed_targets_for(block, evidence)}  # type: ignore[arg-type]
    )


def _segment(segment_id: str, block_id: str, line_index: int, text: str) -> SourceTextSegment:
    return SourceTextSegment(
        segment_id=segment_id,
        page_idx=0,
        block_id=block_id,
        line_index=line_index,
        text=text,
        text_sha256=compute_text_sha256(text),
    )


@pytest.mark.parametrize(
    ("block", "evidence"),
    [
        (
            Paragraph(id="p", sources=_source(), inlines=[Text(text="one\ntwo")]),
            _evidence("p", plain="one\ntwo", preformatted="one\ntwo", table_html="<table/>"),
        ),
        (
            Heading(id="h", sources=_source(), inlines=[Text(text="Title")]),
            _evidence("h", plain="Title"),
        ),
        (
            Table(id="t", sources=_source(), html="<table><tr><td>x</td></tr></table>"),
            _evidence("t", preformatted="x", table_html="<table/>"),
        ),
        (
            CodeBlock(id="c", sources=_source(), text="echo hi"),
            _evidence("c", preformatted="echo hi"),
        ),
        (
            PreformattedBlock(id="pre", sources=_source(), subtype="source_code", text="echo hi"),
            _evidence("pre", preformatted="echo hi"),
        ),
        (
            Aside(id="a", sources=_source(), inlines=[Text(text="Note")]),
            _evidence("a", plain="Note"),
        ),
    ],
)
def test_every_advertised_target_has_a_materializer(
    block: object, evidence: SemanticEvidenceBlock
) -> None:
    assert hasattr(block, "kind")
    targets = allowed_targets_for(block, evidence)  # type: ignore[arg-type]
    assert "definition_list" not in targets
    assert all(
        target in {"keep", "keep_original"}
        or materializer_for(block, target, evidence) is not None  # type: ignore[arg-type]
        for target in targets
    )


def test_paragraph_to_terminal_output_preserves_exact_text() -> None:
    block = Paragraph(id="p", sources=_source(), inlines=[Text(text="$ ls")])
    evidence = _authorized(block, _evidence("p", plain="$ ls", preformatted="$ ls"))
    result, audits = apply_semantic_decisions(
        [block], {"p": _decision("p", "terminal_output")}, {"p": evidence}
    )
    assert result[0].kind == "preformatted"
    assert result[0].text == "$ ls"  # type: ignore[union-attr]
    assert audits[0].status == "applied"


def test_heading_to_paragraph_reuses_exact_inlines() -> None:
    block = Heading(id="h", sources=_source(), level=2, inlines=[Text(text="Title")])
    evidence = _authorized(block, _evidence("h", plain="Title"))
    result, _ = apply_semantic_decisions(
        [block], {"h": _decision("h", "paragraph")}, {"h": evidence}
    )
    assert result[0].kind == "paragraph"
    assert extract_block_visible_text(result[0]) == "Title"


def test_table_to_terminal_output_uses_evidence_text() -> None:
    block = Table(id="t", sources=_source(), html="<table><tr><td>$ ls</td></tr></table>")
    evidence = _authorized(block, _evidence("t", preformatted="$ ls\n", table_html=block.html))
    result, _ = apply_semantic_decisions(
        [block], {"t": _decision("t", "terminal_output")}, {"t": evidence}
    )
    assert result[0].text == "$ ls\n"  # type: ignore[union-attr]


def test_code_and_preformatted_subtype_materializers_preserve_text() -> None:
    code = CodeBlock(id="c", sources=_source(), text="print(1)")
    code_result, _ = apply_semantic_decisions(
        [code],
        {"c": _decision("c", "shell_command")},
        {"c": _authorized(code, _evidence("c"))},
    )
    assert code_result[0].text == code.text  # type: ignore[union-attr]

    pre = PreformattedBlock(id="pre", sources=_source(), subtype="source_code", text="x\n")
    pre_result, _ = apply_semantic_decisions(
        [pre],
        {"pre": _decision("pre", "terminal_output")},
        {"pre": _authorized(pre, _evidence("pre"))},
    )
    assert pre_result[0].subtype == "terminal_output"  # type: ignore[union-attr]
    assert pre_result[0].text == pre.text  # type: ignore[union-attr]


def test_paragraph_callout_blockquote_and_list_are_deterministic() -> None:
    callout = Paragraph(id="callout", sources=_source(), inlines=[Text(text="Note")])
    callout_result, _ = apply_semantic_decisions(
        [callout],
        {"callout": _decision("callout", "callout_note")},
        {"callout": _authorized(callout, _evidence("callout", plain="Note"))},
    )
    assert callout_result[0].kind == "callout"
    assert callout_result[0].id != "callout"
    assert callout_result[0].blocks[0].id == "callout"  # type: ignore[union-attr]

    quote = Paragraph(id="quote", sources=_source(), inlines=[Text(text="Quoted")])
    quote_result, _ = apply_semantic_decisions(
        [quote],
        {"quote": _decision("quote", "block_quote")},
        {"quote": _authorized(quote, _evidence("quote", plain="Quoted"))},
    )
    assert quote_result[0].kind == "block_quote"
    assert quote_result[0].blocks[0].id == "quote"  # type: ignore[union-attr]

    lines = Paragraph(id="list", sources=_source(), inlines=[Text(text="one\ntwo")])
    list_result, _ = apply_semantic_decisions(
        [lines],
        {"list": _decision("list", "unordered_list")},
        {"list": _authorized(lines, _evidence("list", plain="one\ntwo"))},
    )
    assert list_result[0].kind == "list"
    assert extract_block_visible_text(list_result[0]) == "one\ntwo"

    aside = Aside(id="aside", sources=_source(), inlines=[Text(text="Aside text")])
    aside_result, _ = apply_semantic_decisions(
        [aside],
        {"aside": _decision("aside", "paragraph")},
        {"aside": _authorized(aside, _evidence("aside", plain="Aside text"))},
    )
    assert aside_result[0].kind == "paragraph"
    assert extract_block_visible_text(aside_result[0]) == "Aside text"


def test_invalid_text_to_table_is_not_advertised_or_applied() -> None:
    block = Paragraph(id="p", sources=_source(), inlines=[Text(text="plain")])
    evidence = _evidence("p", plain="plain")
    assert "table" not in allowed_targets_for(block, evidence)
    evidence = evidence.model_copy(update={"allowed_targets": ["table"]})
    result, audits = apply_semantic_decisions(
        [block], {"p": _decision("p", "table")}, {"p": evidence}
    )
    assert result[0].id == "p"
    assert audits[0].status == "rejected_invalid_target"


def test_allowed_unsupported_target_is_explicitly_rejected() -> None:
    block = Paragraph(id="p", sources=_source(), inlines=[Text(text="plain")])
    evidence = _evidence("p", plain="plain").model_copy(
        update={"allowed_targets": ["definition_list"]}
    )
    result, audits = apply_semantic_decisions(
        [block], {"p": _decision("p", "definition_list")}, {"p": evidence}
    )
    assert result[0].id == "p"
    assert audits[0].status == "rejected_invalid_target"
    assert "No deterministic materializer" in (audits[0].rejection_reason or "")


@pytest.mark.parametrize(
    "inline",
    [
        Hyperlink(url="https://example.invalid", children=[Text(text="link")]),
        InlineMath(latex="x^2"),
    ],
)
def test_rich_inline_multiline_paragraph_is_not_flattened_to_list(inline: object) -> None:
    block = Paragraph(
        id="rich-list",
        sources=_source(),
        inlines=[Text(text="one\n"), inline, Text(text="\ntwo")],  # type: ignore[list-item]
    )
    evidence = _evidence("rich-list", plain="one\nlink\ntwo")
    assert "unordered_list" not in allowed_targets_for(block, evidence)

    forced_evidence = evidence.model_copy(update={"allowed_targets": ["unordered_list"]})
    result, audits = apply_semantic_decisions(
        [block],
        {"rich-list": _decision("rich-list", "unordered_list")},
        {"rich-list": forced_evidence},
    )
    assert result[0].model_dump() == block.model_dump()
    assert audits[0].status == "rejected_invalid_target"


def test_text_only_list_reconstruction_retains_source_provenance() -> None:
    block = Paragraph(
        id="source-list",
        sources=_source(),
        inlines=[
            Text(
                text="one\ntwo",
                source_segments=[
                    _segment("seg-1", "source-list", 0, "one"),
                    _segment("seg-2", "source-list", 1, "two"),
                ],
            )
        ],
    )
    evidence = _authorized(block, _evidence("source-list", plain="one\ntwo"))
    result, audits = apply_semantic_decisions(
        [block],
        {"source-list": _decision("source-list", "unordered_list")},
        {"source-list": evidence},
    )
    assert audits[0].status == "applied"
    assert result[0].items[0][0].source_segments[0].segment_id == "seg-1"  # type: ignore[union-attr]
    assert result[0].items[1][0].source_segments[0].segment_id == "seg-2"  # type: ignore[union-attr]
    assert extract_block_visible_text(result[0]) == "one\ntwo"


def test_structural_materializer_fingerprint_matches_source() -> None:
    block = Paragraph(id="p", sources=_source(), inlines=[Text(text="same")])
    before = compute_text_sha256(extract_block_visible_text(block))
    evidence = _authorized(block, _evidence("p", plain="same"))
    result, _ = apply_semantic_decisions(
        [block], {"p": _decision("p", "heading", heading_level=2)}, {"p": evidence}
    )
    assert compute_text_sha256(extract_block_visible_text(result[0])) == before


def test_apply_has_only_registry_materialization_path() -> None:
    source = inspect.getsource(apply_semantic_decisions)
    assert source.count("materializer_for(") == 1
    assert "if isinstance(blk, Table) and target" not in source
    assert "target in (\"list\", \"unordered_list\", \"ordered_list\")" not in source
    assert "target.startswith(\"callout_\")" in source
