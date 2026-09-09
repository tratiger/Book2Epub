"""Unit tests for Pass A StructureDecision schemas and BookOutline construction
(Appendix H6, J6-J8)."""

import pytest
from pydantic import ValidationError

from book2epub.ir.models import Heading, Paragraph, Text
from book2epub.semantic.structure import (
    StructureDecision,
    build_book_outline,
    get_outline_prompt_view,
)


def test_structure_decision_validation_success() -> None:
    dec = StructureDecision(
        block_id="b1",
        is_heading=True,
        heading_level=2,
        confidence=0.95,
        evidence_codes=["NUMBERING_PATTERN", "BOOK_HIERARCHY_CONSISTENCY"],
        rationale="Clear section heading 1.2",
    )
    assert dec.block_id == "b1"
    assert dec.heading_level == 2


def test_structure_decision_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        StructureDecision.model_validate({
            "block_id": "b1",
            "is_heading": True,
            "heading_level": 2,
            "confidence": 0.9,
            "extra_field": "not_allowed",
        })


def test_structure_decision_level_range() -> None:
    with pytest.raises(ValidationError):
        StructureDecision(
            block_id="b1",
            heading_level=7,  # invalid: must be 1..6
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        StructureDecision(
            block_id="b1",
            heading_level=0,  # invalid: must be 1..6
            confidence=0.9,
        )


def test_build_book_outline_hierarchy() -> None:
    # Sequence: H1 -> P -> H2 -> P -> H3 -> P -> H1 -> P
    h1_a = Heading(id="h1_a", level=1, inlines=[Text(text="Chapter 1")])
    p1 = Paragraph(id="p1", inlines=[Text(text="Introduction")])
    h2_a = Heading(id="h2_a", level=2, inlines=[Text(text="Section 1.1")])
    p2 = Paragraph(id="p2", inlines=[Text(text="Content 1.1")])
    h3_a = Heading(id="h3_a", level=3, inlines=[Text(text="Subsection 1.1.1")])
    p3 = Paragraph(id="p3", inlines=[Text(text="Deep content")])
    h1_b = Heading(id="h1_b", level=1, inlines=[Text(text="Chapter 2")])
    p4 = Paragraph(id="p4", inlines=[Text(text="Chapter 2 intro")])

    blocks = [h1_a, p1, h2_a, p2, h3_a, p3, h1_b, p4]
    outline = build_book_outline(blocks)

    assert len(outline.root_node_ids) == 2
    root_1_id = outline.root_node_ids[0]
    root_2_id = outline.root_node_ids[1]

    node_1 = outline.nodes[root_1_id]
    assert node_1.heading_block_id == "h1_a"
    assert node_1.level == 1
    assert len(node_1.child_node_ids) == 1

    child_h2_id = node_1.child_node_ids[0]
    node_h2 = outline.nodes[child_h2_id]
    assert node_h2.heading_block_id == "h2_a"
    assert node_h2.level == 2
    assert len(node_h2.child_node_ids) == 1

    child_h3_id = node_h2.child_node_ids[0]
    node_h3 = outline.nodes[child_h3_id]
    assert node_h3.heading_block_id == "h3_a"
    assert node_h3.level == 3

    node_2 = outline.nodes[root_2_id]
    assert node_2.heading_block_id == "h1_b"
    assert node_2.last_block_id == "p4"


def test_get_outline_prompt_view() -> None:
    h1 = Heading(id="h1", level=1, inlines=[Text(text="Chapter 1")])
    h2 = Heading(id="h2", level=2, inlines=[Text(text="Section 1.1")])
    outline = build_book_outline([h1, h2])

    view = get_outline_prompt_view(outline, max_items=10)
    assert len(view) == 2
    assert view[0].block_id == "h1"
    assert view[0].level == 1
    assert view[0].text_preview == "Chapter 1"
