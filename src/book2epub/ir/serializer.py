"""Serialization, deserialization, and plain-text extraction for BookIR."""

import json
import logging
from pathlib import Path

from book2epub.ir.models import (
    Aside,
    Block,
    BookIR,
    Chart,
    CodeBlock,
    DisplayMath,
    Figure,
    Footnote,
    Heading,
    IndexBlock,
    Inline,
    InlineMath,
    ListBlock,
    PageBoundary,
    PageBreak,
    Paragraph,
    Table,
    Text,
    UnknownBlock,
)

logger = logging.getLogger(__name__)


def extract_plain_text_from_inline(inline: Inline) -> str:
    """Extract human-readable plain text from an inline node."""
    if isinstance(inline, Text):
        return inline.text
    elif isinstance(inline, InlineMath):
        return inline.latex
    elif isinstance(inline, (PageBoundary,)):
        return ""
    return ""


def extract_plain_text_from_block(block: Block) -> str:
    """Extract plain text from any block for TOC, captions, and reports."""
    if isinstance(block, (Heading, Paragraph)):
        return " ".join(extract_plain_text_from_inline(i) for i in block.inlines)
    elif isinstance(block, (Figure, Chart, Table)):
        return " ".join(extract_plain_text_from_inline(i) for i in block.caption)
    elif isinstance(block, CodeBlock):
        return block.text
    elif isinstance(block, DisplayMath):
        return block.latex
    elif isinstance(block, ListBlock):
        items_text = []
        for item in block.items:
            items_text.append(" ".join(extract_plain_text_from_inline(i) for i in item))
        return " \n".join(items_text)
    elif isinstance(block, Aside):
        return " ".join(extract_plain_text_from_inline(i) for i in block.inlines)
    elif isinstance(block, Footnote):
        return " ".join(extract_plain_text_from_inline(i) for i in block.inlines)
    elif isinstance(block, IndexBlock):
        items_text = []
        for item in block.items:
            items_text.append(" ".join(extract_plain_text_from_inline(i) for i in item))
        return " \n".join(items_text)
    elif isinstance(block, UnknownBlock):
        return block.extracted_text or ""
    elif isinstance(block, PageBreak):
        return ""
    return ""


def save_bookir(bookir: BookIR, output_path: Path) -> Path:
    """Serialize BookIR to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_str = bookir.model_dump_json(indent=2)
    output_path.write_text(json_str, encoding="utf-8")
    logger.info("Saved BookIR (%d blocks) to %s", len(bookir.blocks), output_path)
    return output_path


def load_bookir(input_path: Path) -> BookIR:
    """Deserialize BookIR from JSON file."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    return BookIR.model_validate(data)
