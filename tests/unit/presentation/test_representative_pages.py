"""Unit tests for representative source page selection (M10/Appendix L14)."""

from book2epub.ir.models import (
    BookIR,
    Callout,
    CodeBlock,
    Heading,
    Paragraph,
    PreformattedBlock,
    SourceDocument,
    SourcePage,
    SourceRef,
    Table,
    Text,
)
from book2epub.presentation.representative_pages import select_representative_pages


def test_representative_pages_priority_selection() -> None:
    """Verify slots are selected deterministically according to priority categories."""
    pages = [SourcePage(page_idx=i, width=600, height=800) for i in range(20)]
    source_doc = SourceDocument(page_count=20, pages=pages)

    # 1. H1 on page 3
    # 2. H2 on page 5
    # 3. CodeBlock on page 7
    # 4. Terminal PreformattedBlock on page 9
    # 5. Table on page 11
    # 6. Callout on page 13
    # 7. Paragraph on page 10 (middle of 20)
    blocks = [
        Heading(
            id="blk-h1",
            level=1,
            inlines=[Text(text="Chapter 1")],
            sources=[SourceRef(page_idx=3, source_type="text")],
        ),
        Heading(
            id="blk-h2",
            level=2,
            inlines=[Text(text="Section 1.1")],
            sources=[SourceRef(page_idx=5, source_type="text")],
        ),
        CodeBlock(
            id="blk-code",
            text="fn main() {}",
            sources=[SourceRef(page_idx=7, source_type="text")],
        ),
        PreformattedBlock(
            id="blk-term",
            text="$ ls",
            subtype="terminal_output",
            sources=[SourceRef(page_idx=9, source_type="text")],
        ),
        Table(
            id="blk-tbl",
            html="<table><tr><td>cell</td></tr></table>",
            sources=[SourceRef(page_idx=11, source_type="text")],
        ),
        Callout(
            id="blk-cal",
            subtype="note",
            blocks=[Paragraph(id="blk-cal-p", inlines=[Text(text="Note")])],
            sources=[SourceRef(page_idx=13, source_type="text")],
        ),
        Paragraph(
            id="blk-prose",
            inlines=[Text(text="Ordinary text")],
            sources=[SourceRef(page_idx=10, source_type="text")],
        ),
    ]

    bookir = BookIR(source=source_doc, blocks=blocks)
    selected = select_representative_pages(bookir, max_pages=8)

    assert len(selected) <= 8
    assert len(selected) == len(set(selected))
    assert selected == sorted(selected)
    # Check priority pages were selected
    assert 3 in selected  # H1
    assert 5 in selected  # H2
    assert 7 in selected  # Code
    assert 9 in selected  # Terminal
    assert 11 in selected  # Table
    assert 13 in selected  # Callout


def test_representative_pages_cap_and_fill() -> None:
    """Verify pages are evenly distributed and capped at max_pages."""
    pages = [SourcePage(page_idx=i, width=600, height=800) for i in range(50)]
    source_doc = SourceDocument(page_count=50, pages=pages)
    bookir = BookIR(source=source_doc, blocks=[])

    selected = select_representative_pages(bookir, max_pages=8)
    assert len(selected) == 8
    assert len(selected) == len(set(selected))
    assert selected == sorted(selected)
    assert all(0 <= p < 50 for p in selected)


def test_generic_preformatted_subtype_is_selected_as_source_code() -> None:
    pages = [SourcePage(page_idx=i, width=600, height=800) for i in range(4)]
    bookir = BookIR(
        source=SourceDocument(page_count=4, pages=pages),
        blocks=[
            PreformattedBlock(
                id="generic-pre",
                text="preserve this layout",
                subtype="generic_preformatted",
                sources=[SourceRef(page_idx=2, source_type="text")],
            )
        ],
    )

    assert 2 in select_representative_pages(bookir, max_pages=1)
