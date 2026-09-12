"""Unit tests for decision application, target materialization,
and content immutability (M8 Section 11 & 17).

Includes hardening tests per user specification:
- Test E: footnote preservation in Table->Preformatted
- Test F: no in-place mutation
- Test G: allowed_target violation rejection
- Test H: out-of-scope block_id filtering (via validation module)
- Test I: wrong chunk_id detection (via validation module)
"""

from book2epub.ir.models import (
    Callout,
    CodeBlock,
    Heading,
    Paragraph,
    PreformattedBlock,
    SourceRef,
    Table,
    Text,
)
from book2epub.ir.models import Text as IRText
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
    allowed_targets: list[str] | None = None,
) -> SemanticEvidenceBlock:
    default_targets = [
        "paragraph",
        "heading",
        "terminal_output",
        "table",
        "callout_note",
        "list",
        "keep",
        "keep_original",
    ]
    return SemanticEvidenceBlock(
        block_id=block_id,
        plain_text=plain,
        preformatted_text=pre,
        table_html=table_html,
        table_html_available=bool(table_html),
        content_sha256=compute_text_sha256(plain or pre or ""),
        allowed_targets=allowed_targets if allowed_targets is not None else default_targets,
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
    ev = _make_evidence("code-1", plain="git status", allowed_targets=[
        "keep", "keep_original", "paragraph", "shell_command", "terminal_output",
        "source_code", "log_output", "config_file", "generic_preformatted",
        "repl_session", "terminal_session",
    ])
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


def test_apply_rejects_same_page_command_to_prose_continuation() -> None:
    command = Paragraph(
        id="cmd",
        sources=[SourceRef(page_idx=12, source_type="text")],
        inlines=[Text(text="ls /")],
    )
    prose = Paragraph(
        id="prose",
        sources=[SourceRef(page_idx=12, source_type="text")],
        inlines=[Text(text="ルートディレクトリに格納されているファイルが表示される。")],
    )
    evidence_lookup = {
        "cmd": _make_evidence("cmd", plain="ls /"),
        "prose": _make_evidence(
            "prose", plain="ルートディレクトリに格納されているファイルが表示される。"
        ),
    }
    decision = ReconciledStructureDecision(
        block_id="prose",
        is_heading=None,
        heading_level=None,
        paragraph_continuation_of="cmd",
        confidence=0.99,
        evidence_codes=["CROSS_PAGE_SENTENCE_CONTINUITY"],
    )

    new_blocks, audits = apply_structure_decisions(
        blocks=[command, prose],
        decisions={"prose": decision},
        evidence_lookup=evidence_lookup,
    )

    assert [block.id for block in new_blocks] == ["cmd", "prose"]
    assert audits[0].status == "rejected_invalid_continuation"
    assert "source page" in (audits[0].rejection_reason or "")


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


# ===========================================================================
# Hardening Tests
# ===========================================================================


# Test E: Table->Preformatted preserves footnotes and caption
def test_table_to_preformatted_preserves_footnotes_and_caption() -> None:
    """Test E: caption and footnotes are carried over in Table->Preformatted conversion."""
    caption_inline = IRText(text="Table 1: Command output")
    footnote_inline = IRText(text="a) Exit code 0 means success")

    tbl = Table(
        id="blk-tbl-fn",
        html="<table><tr><td>$ make install</td></tr></table>",
        caption=[caption_inline],
        footnotes=[footnote_inline],
    )
    ev = _make_evidence("blk-tbl-fn", pre="$ make install\n")
    evidence_lookup = {"blk-tbl-fn": ev}

    dec = ReconciledSemanticDecision(
        block_id="blk-tbl-fn",
        target="terminal_output",
        heading_level=None,
        confidence=0.97,
        evidence_codes=["SHELL_PROMPT_PATTERN"],
    )

    new_blocks, audits = apply_semantic_decisions(
        blocks=[tbl],
        decisions={"blk-tbl-fn": dec},
        evidence_lookup=evidence_lookup,
    )

    assert len(new_blocks) == 1
    pf = new_blocks[0]
    assert isinstance(pf, PreformattedBlock)
    assert pf.subtype == "terminal_output"
    # Caption and footnotes must be preserved
    assert len(pf.caption) == 1
    assert pf.caption[0].text == "Table 1: Command output"  # type: ignore[attr-defined]
    assert len(pf.footnotes) == 1
    assert pf.footnotes[0].text == "a) Exit code 0 means success"  # type: ignore[attr-defined]
    assert audits[0].status == "applied"


# Test F: No in-place mutation — Heading level change uses model_copy
def test_heading_level_change_no_in_place_mutation() -> None:
    """Test F: Heading level adjustment via apply_structure_decisions must not mutate
    the original block object; instead a new object via model_copy is returned."""
    original_heading = Heading(id="h-mut", level=3, inlines=[Text(text="Section Title")])
    original_level = original_heading.level

    ev = _make_evidence("h-mut", plain="Section Title")
    evidence_lookup = {"h-mut": ev}

    dec = ReconciledStructureDecision(
        block_id="h-mut",
        is_heading=True,
        heading_level=2,
        paragraph_continuation_of=None,
        confidence=0.92,
        evidence_codes=["NUMBERING_PATTERN"],
    )

    new_blocks, audits = apply_structure_decisions(
        blocks=[original_heading],
        decisions={"h-mut": dec},
        evidence_lookup=evidence_lookup,
    )

    assert len(new_blocks) == 1
    new_h = new_blocks[0]
    # New object has updated level
    assert new_h.level == 2
    # Original object is NOT mutated
    assert original_heading.level == original_level, (
        "apply_structure_decisions must not mutate the original block"
    )
    assert audits[0].status == "applied"


# Test F (continuation merge): No in-place mutation of prior block in continuation merge
def test_continuation_merge_no_in_place_mutation() -> None:
    """Test F (cont): paragraph_continuation merge must not mutate the prior paragraph block."""
    p1 = Paragraph(id="p-c1", inlines=[Text(text="First part ")])
    p2 = Paragraph(id="p-c2", inlines=[Text(text="second part.")])
    original_p1_inlines_len = len(p1.inlines)

    ev1 = _make_evidence("p-c1", plain="First part ")
    ev2 = _make_evidence("p-c2", plain="second part.")
    evidence_lookup = {"p-c1": ev1, "p-c2": ev2}

    dec = ReconciledStructureDecision(
        block_id="p-c2",
        is_heading=None,
        heading_level=None,
        paragraph_continuation_of="p-c1",
        confidence=0.91,
        evidence_codes=["CROSS_PAGE_SENTENCE_CONTINUITY"],
    )

    new_blocks, _ = apply_structure_decisions(
        blocks=[p1, p2],
        decisions={"p-c2": dec},
        evidence_lookup=evidence_lookup,
    )

    assert len(new_blocks) == 1
    merged = new_blocks[0]
    # Original p1 object must NOT have been mutated
    assert len(p1.inlines) == original_p1_inlines_len, (
        "Original p1.inlines must not be mutated by continuation merge"
    )
    # Merged block has more inlines (p1 + PageBoundary + p2)
    assert len(merged.inlines) > original_p1_inlines_len


# Test G: allowed_target violation — target not in evidence.allowed_targets
def test_allowed_target_violation_rejected() -> None:
    """Test G: A target not in evidence.allowed_targets must be rejected as
    rejected_invalid_target before any case branch executes."""
    tbl = Table(id="blk-tbl-gate", html="<table><tr><td>data</td></tr></table>")
    # Evidence: allowed_targets does NOT include 'terminal_output'
    ev = _make_evidence(
        "blk-tbl-gate",
        plain="data",
        pre="data",
        allowed_targets=["keep", "keep_original", "table", "paragraph"],
    )
    evidence_lookup = {"blk-tbl-gate": ev}

    dec = ReconciledSemanticDecision(
        block_id="blk-tbl-gate",
        target="terminal_output",
        heading_level=None,
        confidence=0.95,
        evidence_codes=["SHELL_PROMPT_PATTERN"],
    )

    new_blocks, audits = apply_semantic_decisions(
        blocks=[tbl],
        decisions={"blk-tbl-gate": dec},
        evidence_lookup=evidence_lookup,
    )

    # Must keep original Table, not convert to PreformattedBlock
    assert isinstance(new_blocks[0], Table)
    assert audits[0].status == "rejected_invalid_target"
    assert "not in allowed_targets" in (audits[0].rejection_reason or "")


# Test G (no evidence): No evidence block → rejected_invalid_target
def test_no_evidence_block_rejected() -> None:
    """Test G (no-ev): If no SemanticEvidenceBlock exists for a block, the decision
    must be rejected immediately at the hard gate."""
    p = Paragraph(id="p-no-ev", inlines=[Text(text="Orphan paragraph.")])
    # Evidence lookup is empty
    evidence_lookup: dict[str, SemanticEvidenceBlock] = {}

    dec = ReconciledSemanticDecision(
        block_id="p-no-ev",
        target="callout_note",
        heading_level=None,
        confidence=0.91,
        evidence_codes=[],
    )

    new_blocks, audits = apply_semantic_decisions(
        blocks=[p],
        decisions={"p-no-ev": dec},
        evidence_lookup=evidence_lookup,
    )

    assert isinstance(new_blocks[0], Paragraph)
    assert audits[0].status == "rejected_invalid_target"
    assert "No evidence block" in (audits[0].rejection_reason or "")


# Test H / Test I: Scope validation tests are in test_validation.py
# Tests J: pipeline-level final IR match is covered in integration tests


# Test: CodeBlock->Preformatted preserves footnotes
def test_code_to_preformatted_preserves_footnotes() -> None:
    """CodeBlock->Preformatted must preserve footnotes field."""
    footnote_inline = IRText(text="1. See man page for details.")
    code = CodeBlock(
        id="code-fn",
        text="ls -la /etc",
        language="bash",
        footnotes=[footnote_inline],
    )
    ev = _make_evidence("code-fn", plain="ls -la /etc", allowed_targets=[
        "keep", "keep_original", "paragraph", "shell_command", "terminal_output",
        "source_code", "log_output", "config_file", "generic_preformatted",
        "repl_session", "terminal_session",
    ])
    evidence_lookup = {"code-fn": ev}

    dec = ReconciledSemanticDecision(
        block_id="code-fn",
        target="shell_command",
        heading_level=None,
        confidence=0.96,
        evidence_codes=["SHELL_PROMPT_PATTERN"],
    )

    new_blocks, audits = apply_semantic_decisions(
        blocks=[code],
        decisions={"code-fn": dec},
        evidence_lookup=evidence_lookup,
    )

    pf = new_blocks[0]
    assert isinstance(pf, PreformattedBlock)
    assert len(pf.footnotes) == 1
    assert pf.footnotes[0].text == "1. See man page for details."  # type: ignore[attr-defined]
    assert audits[0].status == "applied"
