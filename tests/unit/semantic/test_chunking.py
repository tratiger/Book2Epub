"""Unit tests for dynamic chunking and overlap management (M8 Section 4, Appendix I5)."""

from book2epub.config import SemanticConfig
from book2epub.semantic.chunking import compute_chunk_id, create_semantic_chunks
from book2epub.semantic.models import DraftBlock, DraftGeometry, SemanticDraftBook


def _make_dummy_block(
    block_id: str,
    text: str = "Lorem ipsum dolor sit amet.",
    kind: str = "paragraph",
) -> DraftBlock:
    return DraftBlock(
        block_id=block_id,
        order_index=0,
        page_idx=0,
        pages=[0],
        source_type=kind,
        mineru_type=kind,
        current_kind=kind,
        text_preview=text,
        content_sha256=f"hash_{block_id}",
        geometry=DraftGeometry(line_count=1),
    )


def test_compute_chunk_id_deterministic() -> None:
    blocks = [_make_dummy_block("b1"), _make_dummy_block("b2")]
    id1 = compute_chunk_id(1, blocks, provider="openai", model="gpt-5.6-sol")
    id2 = compute_chunk_id(1, blocks, provider="openai", model="gpt-5.6-sol")
    id3 = compute_chunk_id(2, blocks, provider="openai", model="gpt-5.6-sol")
    assert id1 == id2
    assert id1.startswith("sem-0001-")
    assert id3.startswith("sem-0002-")


def test_chunking_empty_book() -> None:
    draft = SemanticDraftBook(book_id="empty", blocks=[])
    cfg = SemanticConfig()
    chunks = create_semantic_chunks(draft, cfg)
    assert chunks == []


def test_chunking_exceeds_max_blocks() -> None:
    # 25 blocks with max_chunk_blocks = 10
    blocks = [_make_dummy_block(f"b{i}") for i in range(25)]
    draft = SemanticDraftBook(book_id="test_book", blocks=blocks)
    cfg = SemanticConfig(max_chunk_blocks=10, max_chunk_chars=50000)

    chunks = create_semantic_chunks(draft, cfg)
    assert len(chunks) >= 3

    # First chunk has no overlap
    assert chunks[0].overlap_block_ids == []
    # Second chunk has overlap blocks from first chunk
    assert len(chunks[1].overlap_block_ids) > 0


def test_chunking_heading_boundary_split() -> None:
    # 20 blocks where block 14 is a heading
    blocks: list[DraftBlock] = []
    for i in range(20):
        kind = "heading" if i == 14 else "paragraph"
        blocks.append(_make_dummy_block(f"b{i}", kind=kind))

    draft = SemanticDraftBook(book_id="test_heading", blocks=blocks)
    cfg = SemanticConfig(max_chunk_blocks=18, max_chunk_chars=50000)

    chunks = create_semantic_chunks(draft, cfg)
    # Check that chunk split preferred heading at index 14
    first_chunk_ids = chunks[0].block_ids
    assert "b13" in first_chunk_ids
