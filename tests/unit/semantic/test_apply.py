"""Unit tests for decision application, target materialization,
and content immutability (M8 Section 11 & 17)."""

from book2epub.ir.models import (
    Callout,
    CodeBlock,
    Heading,
    Paragraph,
    PreformattedBlock,
    Table,
    Text,
)
from book2epub.semantic.apply import (
    apply_semantic_decisions,
    apply_structure_decisions,
    extract_block_visible_text,
)
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.models import SemanticEvidenceBlock
from book2epub.semantic.reconcile import (
    ReconciledSemanticDecision,
    ReconciledStructureDecision,
)


def _make_evidence(
    block_id: str,
    plain: str = "",
    pre: str | None = None,
    table_html: str | None = None,
) -> SemanticEvidenceBlock:
    return SemanticEvidenceBlock(
        block_id=block_id,
        plain_text=plain,
        preformatted_text=pre,
        table_html=table_html,
        table_html_available=bool(table_html),
        content_sha256=compute_text_sha256(plain or pre or ""),
        allowed_targets=[
            "paragraph",
            "heading",
            "terminal_output",
            "table",
            "callout_note",
            "list",
        ],
    )


def test_apply_table_to_terminal_output() -> None:
    tbl = Table(id="blk-table", html="<table><tr><td>$ ls -la</td></tr></table>")
    ev = _make_evidence("blk-table", pre="$ ls -la\ntotal 0\n")
    evidence_lookup = {"blk-table": ev}

    dec = ReconciledSemanticDecision(
        block_id="blk-table",
        target="terminal_output",
        heading_level=None,
        confidence=0.95,
        evidence_codes=["SHELL_PROMPT_PATTERN"],
    )

    new_blocks, audits = apply_semantic_decisions(
        blocks=[tbl],
        decisions={"blk-table": dec},
        evidence_lookup=evidence_lookup,
    )

    assert len(new_blocks) == 1
    new_blk = new_blocks[0]
    assert isinstance(new_blk, PreformattedBlock)
    assert new_blk.subtype == "terminal_output"
    assert new_blk.text == "$ ls -la\ntotal 0\n"
    assert audits[0].status == "applied"


def test_apply_paragraph_to_heading_immutability() -> None:
    p = Paragraph(id="p-heading", inlines=[Text(text="1.2 Architectural Overview")])
    ev = _make_evidence("p-heading", plain="1.2 Architectural Overview")
    evidence_lookup = {"p-heading": ev}

    dec = ReconciledStructureDecision(
        block_id="p-heading",
        is_heading=True,
        heading_level=2,
        paragraph_continuation_of=None,
        confidence=0.92,
        evidence_codes=["NUMBERING_PATTERN"],
    )

    new_blocks, audits = apply_structure_decisions(
        blocks=[p],
        decisions={"p-heading": dec},
        evidence_lookup=evidence_lookup,
    )

    assert len(new_blocks) == 1
    h = new_blocks[0]
    assert isinstance(h, Heading)
    assert h.level == 2
    assert extract_block_visible_text(h) == "1.2 Architectural Overview"
    assert audits[0].status == "applied"


def test_apply_heading_demotion_to_paragraph() -> None:
    h = Heading(id="h-false", level=2, inlines=[Text(text="Just a normal sentence here.")])
    ev = _make_evidence("h-false", plain="Just a normal sentence here.")
    evidence_lookup = {"h-false": ev}

    dec = ReconciledStructureDecision(
        block_id="h-false",
        is_heading=False,
        heading_level=None,
        paragraph_continuation_of=None,
        confidence=0.90,
        evidence_codes=["AMBIGUOUS"],
    )

    new_blocks, audits = apply_structure_decisions(
        blocks=[h],
        decisions={"h-false": dec},
        evidence_lookup=evidence_lookup,
    )

    assert len(new_blocks) == 1
    p = new_blocks[0]
    assert isinstance(p, Paragraph)
    assert extract_block_visible_text(p) == "Just a normal sentence here."
    assert audits[0].status == "applied"


def test_apply_code_to_shell_command() -> None:
    code = CodeBlock(id="code-1", text="git status", language="bash")
    ev = _make_evidence("code-1", plain="git status")
    evidence_lookup = {"code-1": ev}

    dec = ReconciledSemanticDecision(
        block_id="code-1",
        target="shell_command",
        heading_level=None,
        confidence=0.95,
        evidence_codes=["SHELL_PROMPT_PATTERN"],
    )

    new_blocks, audits = apply_semantic_decisions(
        blocks=[code],
        decisions={"code-1": dec},
        evidence_lookup=evidence_lookup,
    )

    assert len(new_blocks) == 1
    pf = new_blocks[0]
    assert isinstance(pf, PreformattedBlock)
    assert pf.subtype == "shell_command"
    assert pf.text == "git status"
    assert audits[0].status == "applied"


def test_apply_paragraph_to_callout() -> None:
    p = Paragraph(id="p-note", inlines=[Text(text="Note: This is an important detail.")])
    ev = _make_evidence("p-note", plain="Note: This is an important detail.")
    evidence_lookup = {"p-note": ev}

    dec = ReconciledSemanticDecision(
        block_id="p-note",
        target="callout_note",
        heading_level=None,
        confidence=0.89,
        evidence_codes=["CALLOUT_LANGUAGE_PATTERN"],
    )

    new_blocks, audits = apply_semantic_decisions(
        blocks=[p],
        decisions={"p-note": dec},
        evidence_lookup=evidence_lookup,
    )

    assert len(new_blocks) == 1
    callout = new_blocks[0]
    assert isinstance(callout, Callout)
    assert callout.subtype == "note"
    assert extract_block_visible_text(callout) == "Note: This is an important detail."
    assert audits[0].status == "applied"


def test_apply_cross_page_continuation() -> None:
    p1 = Paragraph(id="p-1", inlines=[Text(text="Sentence starts on page 1 ")])
    p2 = Paragraph(id="p-2", inlines=[Text(text="and continues on page 2.")])
    ev1 = _make_evidence("p-1", plain="Sentence starts on page 1 ")
    ev2 = _make_evidence("p-2", plain="and continues on page 2.")
    evidence_lookup = {"p-1": ev1, "p-2": ev2}

    dec = ReconciledStructureDecision(
        block_id="p-2",
        is_heading=None,
        heading_level=None,
        paragraph_continuation_of="p-1",
        confidence=0.94,
        evidence_codes=["CROSS_PAGE_SENTENCE_CONTINUITY"],
    )

    new_blocks, audits = apply_structure_decisions(
        blocks=[p1, p2],
        decisions={"p-2": dec},
        evidence_lookup=evidence_lookup,
    )

    # Merged into single block p1
    assert len(new_blocks) == 1
    merged = new_blocks[0]
    assert isinstance(merged, Paragraph)
    assert "Sentence starts on page 1" in extract_block_visible_text(merged)
    assert "and continues on page 2." in extract_block_visible_text(merged)


def test_apply_hallucinated_table_target_rejected() -> None:
    p = Paragraph(id="p-no-tbl", inlines=[Text(text="Some prose text.")])
    # Evidence has NO table_html
    ev = _make_evidence("p-no-tbl", plain="Some prose text.", table_html=None)
    evidence_lookup = {"p-no-tbl": ev}

    dec = ReconciledSemanticDecision(
        block_id="p-no-tbl",
        target="table",
        heading_level=None,
        confidence=0.90,
    )

    new_blocks, audits = apply_semantic_decisions(
        blocks=[p],
        decisions={"p-no-tbl": dec},
        evidence_lookup=evidence_lookup,
    )

    # Must preserve original Paragraph
    assert len(new_blocks) == 1
    assert isinstance(new_blocks[0], Paragraph)
    assert audits[0].status == "rejected_invalid_target"
