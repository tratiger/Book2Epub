"""Unit tests for M6 SemanticEvidence and SemanticDraft extraction."""

from pathlib import Path

from book2epub.ir.adapter import MiddleJsonAdapter
from book2epub.semantic.apply import (
    materialize_preformatted_from_evidence,
    validate_semantic_target,
    verify_block_hash,
)
from book2epub.semantic.draft import build_semantic_draft
from book2epub.semantic.evidence import build_semantic_evidence
from book2epub.semantic.hashing import compute_content_sha256


def _create_synthetic_middle_dict() -> dict:
    """Create synthetic middle.json fixture covering all M6 test cases."""
    return {
        "_version_name": "3.4.5",
        "_backend": "hybrid",
        "_effort": "high",
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [600, 800],
                "para_blocks": [
                    # 1. Heading unknown level
                    {
                        "type": "title",
                        "bbox": [50, 50, 550, 90],
                        "lines": [
                            {
                                "bbox": [50, 50, 550, 90],
                                "spans": [{"type": "text", "content": "1. Introduction"}],
                            }
                        ],
                    },
                    # 2. Ordinary paragraph
                    {
                        "type": "text",
                        "bbox": [50, 100, 550, 150],
                        "lines": [
                            {
                                "bbox": [50, 100, 550, 120],
                                "spans": [
                                    {"type": "text", "content": "This is an ordinary paragraph."}
                                ],
                            }
                        ],
                    },
                    # 3. Real table with header
                    {
                        "type": "table",
                        "bbox": [50, 160, 550, 240],
                        "blocks": [
                            {
                                "type": "table_body",
                                "lines": [
                                    {
                                        "spans": [
                                            {
                                                "type": "table",
                                                "html": (
                                                    "<table><tr><th>Header A</th><th>Header B</th>"
                                                    "</tr><tr><td>1</td><td>2</td></tr></table>"
                                                ),
                                                "content": "Header A Header B\n1 2",
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    },
                    # 4. MinerU-table-looking shell output
                    {
                        "type": "table",
                        "bbox": [50, 250, 550, 330],
                        "blocks": [
                            {
                                "type": "table_body",
                                "lines": [
                                    {
                                        "spans": [
                                            {
                                                "type": "table",
                                                "html": (
                                                    "<table><tr><td>$ ps -ef</td></tr>"
                                                    "<tr><td>root 1 0 0:00 init</td></tr></table>"
                                                ),
                                                "content": "$ ps -ef\nroot 1 0 0:00 init",
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    },
                    # 5. Code block with indentation
                    {
                        "type": "code",
                        "bbox": [50, 340, 550, 420],
                        "language": "python",
                        "lines": [
                            {
                                "bbox": [50, 340, 550, 360],
                                "spans": [
                                    {"type": "code", "content": "def add(a: int, b: int) -> int:"}
                                ],
                            },
                            {
                                "bbox": [50, 360, 550, 380],
                                "spans": [{"type": "code", "content": "    return a + b"}],
                            },
                        ],
                    },
                    # 6. Unordered list with '-' marker
                    {
                        "type": "text",
                        "bbox": [50, 430, 550, 480],
                        "lines": [
                            {
                                "bbox": [50, 430, 550, 450],
                                "spans": [{"type": "text", "content": "- First bullet item"}],
                            }
                        ],
                    },
                    # 7. Aside-like block with Callout cue
                    {
                        "type": "text",
                        "bbox": [50, 490, 550, 540],
                        "lines": [
                            {
                                "bbox": [50, 490, 550, 510],
                                "spans": [
                                    {"type": "text", "content": "Note: Remember to save your work."}
                                ],
                            }
                        ],
                    },
                    # 8. Math formula
                    {
                        "type": "interline_equation",
                        "bbox": [50, 550, 550, 600],
                        "lines": [
                            {
                                "bbox": [50, 550, 550, 600],
                                "spans": [{"type": "equation", "content": "$$E = mc^2$$"}],
                            }
                        ],
                    },
                ],
            }
        ],
    }


def test_synthetic_evidence_extraction(tmp_path: Path) -> None:
    """Validate extraction of evidence from synthetic middle fixture."""
    middle_dict = _create_synthetic_middle_dict()
    adapter = MiddleJsonAdapter(base_dir=tmp_path, strict=False)
    raw_ir = adapter.convert_middle_json(middle_dict)

    evidence_book = build_semantic_evidence(
        middle_data=middle_dict,
        raw_ir=raw_ir,
        source_middle_sha256="mid-hash",
        raw_bookir_sha256="raw-hash",
    )

    assert len(evidence_book.blocks) == 8

    # Block 1: Heading unknown level
    h_block = evidence_book.blocks[0]
    assert h_block.current_kind == "heading"
    assert "HEADING_LEVEL_UNKNOWN" in h_block.flags
    assert "heading" in h_block.allowed_targets
    assert "paragraph" in h_block.allowed_targets

    # Block 2: Ordinary paragraph
    p_block = evidence_book.blocks[1]
    assert p_block.current_kind == "paragraph"
    assert "paragraph" in p_block.allowed_targets
    assert "heading" in p_block.allowed_targets
    assert p_block.plain_text == "This is an ordinary paragraph."

    # Block 3: Real table with header
    tbl_block = evidence_book.blocks[2]
    assert tbl_block.current_kind == "table"
    assert tbl_block.table_html_available is True
    assert "HAS_STRUCTURED_TABLE" in tbl_block.flags
    assert "TABLE_WITHOUT_CLEAR_HEADER" not in tbl_block.flags
    assert "table" in tbl_block.allowed_targets

    # Block 4: MinerU-table-looking shell output
    shell_block = evidence_book.blocks[3]
    assert shell_block.current_kind == "table"
    # Assertion 1: table shell block has both table_html and exact preformatted_text
    assert shell_block.table_html is not None
    assert "$ ps -ef" in shell_block.preformatted_text
    assert "TABLE_CONTAINS_SHELL_PROMPT" in shell_block.flags
    # Assertion 2: allowed_targets permits terminal_output
    assert "terminal_output" in shell_block.allowed_targets
    assert "shell_command" in shell_block.allowed_targets

    # Block 5: Code block with exact indentation
    code_block = evidence_book.blocks[4]
    assert code_block.current_kind == "code"
    # Assertion 4: code whitespace in preformatted_text is exact
    assert "    return a + b" in code_block.preformatted_text
    assert "source_code" in code_block.allowed_targets

    # Block 6: Unordered list containing '-'
    list_cue_block = evidence_book.blocks[5]
    assert "LIST_MARKER_IN_TEXT" in list_cue_block.flags

    # Block 7: Callout-like note
    callout_cue_block = evidence_book.blocks[6]
    assert "CALLOUT_LIKE_GEOMETRY" in callout_cue_block.flags
    assert "callout_note" in callout_cue_block.allowed_targets

    # Block 8: Math block
    math_block = evidence_book.blocks[7]
    assert math_block.current_kind == "display_math"
    # Math can only keep / display_math in M6-M12
    assert "display_math" in math_block.allowed_targets
    assert "source_code" not in math_block.allowed_targets
    assert "table" not in math_block.allowed_targets

    # Assertion 5: Evidence hash is deterministic
    computed_hash = compute_content_sha256(
        plain_text=shell_block.plain_text,
        preformatted_text=shell_block.preformatted_text,
        table_html_text_content=shell_block.table_html,
        caption_text=shell_block.caption_text,
        footnote_text=shell_block.footnote_text,
    )
    assert shell_block.content_sha256 == computed_hash
    assert verify_block_hash(shell_block, computed_hash) is True


def test_draft_building_and_truncation(tmp_path: Path) -> None:
    """Verify SemanticDraftBook construction and deterministic truncation."""
    middle_dict = _create_synthetic_middle_dict()
    adapter = MiddleJsonAdapter(base_dir=tmp_path, strict=False)
    raw_ir = adapter.convert_middle_json(middle_dict)
    evidence_book = build_semantic_evidence(middle_dict, raw_ir)

    draft_book = build_semantic_draft(evidence_book, book_id="synth-book")
    assert len(draft_book.blocks) == len(evidence_book.blocks)
    assert draft_book.book_id == "synth-book"

    # Verify geometry was computed
    first_draft = draft_book.blocks[0]
    assert first_draft.geometry.line_count >= 1
    assert first_draft.geometry.alignment_hint in ("left", "center", "right")

    # Test truncation determinism on large text
    large_text = "A" * 5_000
    evidence_book.blocks[1].plain_text = large_text
    truncated_draft = build_semantic_draft(evidence_book, book_id="large-book")
    p_draft = truncated_draft.blocks[1]
    assert p_draft.preview_truncated is True
    assert p_draft.plain_text is not None
    assert len(p_draft.plain_text) <= 4_050
    assert "...[truncated]..." in p_draft.plain_text


def test_semantic_apply_skeleton() -> None:
    """Verify apply skeleton validation and materialization."""
    middle_dict = _create_synthetic_middle_dict()
    adapter = MiddleJsonAdapter(base_dir=Path("."), strict=False)
    raw_ir = adapter.convert_middle_json(middle_dict)
    evidence_book = build_semantic_evidence(middle_dict, raw_ir)

    shell_ev = evidence_book.blocks[3]
    # Validate allowed target
    assert validate_semantic_target(shell_ev, "terminal_output") is True
    # Disallowed target
    assert validate_semantic_target(shell_ev, "figure") is False

    # Materialize preformatted block without LLM-generated text
    pre_block = materialize_preformatted_from_evidence(shell_ev, subtype="terminal_output")
    assert pre_block.kind == "preformatted"
    assert pre_block.subtype == "terminal_output"
    assert "$ ps -ef" in pre_block.text
