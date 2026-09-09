"""Unit tests for M6 semantic models and BookIR extensions."""


from book2epub.ir.models import (
    BlockQuote,
    BookIR,
    Callout,
    DefinitionItem,
    DefinitionList,
    ExampleBlock,
    ExerciseBlock,
    ListBlock,
    Paragraph,
    PreformattedBlock,
    SourceDocument,
    SourcePage,
    SourceTextSegment,
    Text,
)
from book2epub.semantic.hashing import (
    compute_content_sha256,
    compute_text_sha256,
)
from book2epub.semantic.models import (
    DraftBlock,
    DraftGeometry,
    SemanticDraftBook,
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)


def test_new_bookir_block_models() -> None:
    """Verify that all new M6 block types can be constructed, serialized, and deserialized."""
    # 1. PreformattedBlock
    pre = PreformattedBlock(
        id="blk-00001",
        subtype="terminal_output",
        text="$ ls -la\ntotal 0\n",
    )
    assert pre.kind == "preformatted"
    assert pre.subtype == "terminal_output"

    # 2. Callout
    callout = Callout(
        id="blk-00002",
        subtype="warning",
        title=[Text(text="Warning Title")],
        blocks=[Paragraph(id="blk-00003", inlines=[Text(text="Pay attention.")])],
    )
    assert callout.kind == "callout"
    assert callout.subtype == "warning"

    # 3. BlockQuote
    quote = BlockQuote(
        id="blk-00004",
        blocks=[Paragraph(id="blk-00005", inlines=[Text(text="Quote body")])],
        attribution=[Text(text="Famous Author")],
    )
    assert quote.kind == "block_quote"

    # 4. DefinitionList
    dl = DefinitionList(
        id="blk-00006",
        items=[
            DefinitionItem(
                term=[Text(text="CPU")],
                definitions=[[Text(text="Central Processing Unit")]],
            )
        ],
    )
    assert dl.kind == "definition_list"

    # 5. Example & Exercise
    ex = ExampleBlock(
        id="blk-00007",
        label=[Text(text="Example 1.1")],
        blocks=[Paragraph(id="blk-00008", inlines=[Text(text="Example text")])],
    )
    assert ex.kind == "example"

    exercise = ExerciseBlock(
        id="blk-00009",
        label=[Text(text="Exercise 1.1")],
        blocks=[Paragraph(id="blk-00010", inlines=[Text(text="Solve this.")])],
    )
    assert exercise.kind == "exercise"

    # 6. ListBlock with new marker metadata
    lb = ListBlock(
        id="blk-00011",
        ordered=False,
        items=[[Text(text="Item 1")], [Text(text="Item 2")]],
        marker_style="disc",
        source_markers=["-", "-"],
    )
    assert lb.marker_style == "disc"
    assert lb.source_markers == ["-", "-"]


def test_source_text_segment_on_text() -> None:
    """Verify that Text inlines correctly store SourceTextSegment metadata."""
    seg = SourceTextSegment(
        segment_id="blk-00001-p000-l000-s000",
        page_idx=0,
        block_id="blk-00001",
        line_index=0,
        span_index=0,
        text="Hello world",
        boundary_before="start",
        source_span_type="text",
        text_sha256=compute_text_sha256("Hello world"),
    )
    t = Text(text="Hello world", source_segments=[seg])
    assert len(t.source_segments) == 1
    assert t.source_segments[0].segment_id == "blk-00001-p000-l000-s000"
    assert t.source_segments[0].text_sha256 == compute_text_sha256("Hello world")

    # Round trip Text
    dumped = t.model_dump_json()
    loaded = Text.model_validate_json(dumped)
    assert loaded.text == "Hello world"
    assert len(loaded.source_segments) == 1
    assert loaded.source_segments[0].segment_id == seg.segment_id


def test_bookir_schema_version_compatibility() -> None:
    """Verify that BookIR 1.0 JSON loads cleanly and BookIR 1.1 round-trips."""
    # 1.0 JSON payload without new fields
    doc_1_0 = {
        "schema_version": "1.0",
        "source": {
            "mineru_version": "3.4.5",
            "mineru_backend": "hybrid",
            "page_count": 1,
            "pages": [{"page_idx": 0, "width": 600, "height": 800}],
        },
        "metadata": {"title": "Legacy Book"},
        "blocks": [
            {
                "id": "blk-00001",
                "kind": "paragraph",
                "inlines": [{"kind": "text", "text": "Legacy paragraph"}],
            }
        ],
        "assets": {},
        "warnings": [],
    }
    loaded_1_0 = BookIR.model_validate(doc_1_0)
    assert loaded_1_0.schema_version == "1.0"
    assert len(loaded_1_0.blocks) == 1

    # New BookIR default is 1.1
    new_ir = BookIR(
        source=SourceDocument(page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]),
        blocks=[
            PreformattedBlock(
                id="blk-00001",
                subtype="shell_command",
                text="uv run pytest",
            )
        ],
    )
    assert new_ir.schema_version == "1.1"
    json_str = new_ir.model_dump_json()
    loaded_new = BookIR.model_validate_json(json_str)
    assert loaded_new.schema_version == "1.1"
    assert loaded_new.blocks[0].kind == "preformatted"


def test_semantic_evidence_and_draft_roundtrip() -> None:
    """Verify Pydantic serialization round-trip for SemanticEvidenceBook and SemanticDraftBook."""
    ev_block = SemanticEvidenceBlock(
        block_id="blk-00100",
        order_index=0,
        page_idx=1,
        source_type="table",
        current_kind="table",
        plain_text="Table plain text",
        preformatted_text="$ ps aux\nroot 1\n",
        table_html="<table><tr><td>Output</td></tr></table>",
        table_html_available=True,
        allowed_targets=["table", "terminal_output", "keep"],
        content_sha256=compute_content_sha256(
            plain_text="Table plain text",
            preformatted_text="$ ps aux\nroot 1\n",
            table_html_text_content="<table><tr><td>Output</td></tr></table>",
        ),
        flags=["TABLE_CONTAINS_SHELL_PROMPT"],
    )

    ev_book = SemanticEvidenceBook(
        source_middle_sha256="abc123",
        raw_bookir_sha256="def456",
        blocks=[ev_block],
    )

    ev_json = ev_book.model_dump_json()
    ev_loaded = SemanticEvidenceBook.model_validate_json(ev_json)
    assert ev_loaded.blocks[0].block_id == "blk-00100"
    assert ev_loaded.blocks[0].preformatted_text == "$ ps aux\nroot 1\n"
    assert ev_loaded.blocks[0].content_sha256 == ev_block.content_sha256

    draft_block = DraftBlock(
        block_id="blk-00100",
        order_index=0,
        page_idx=1,
        source_type="table",
        current_kind="table",
        plain_text="Table plain text",
        preformatted_preview="$ ps aux\nroot 1\n",
        has_table_html=True,
        allowed_targets=["table", "terminal_output", "keep"],
        geometry=DraftGeometry(bbox_width_ratio=0.8, alignment_hint="center"),
        content_sha256=ev_block.content_sha256,
    )
    draft_book = SemanticDraftBook(
        book_id="test-job",
        blocks=[draft_block],
    )
    draft_json = draft_book.model_dump_json()
    draft_loaded = SemanticDraftBook.model_validate_json(draft_json)
    assert draft_loaded.blocks[0].block_id == "blk-00100"
    assert draft_loaded.blocks[0].geometry.alignment_hint == "center"
