"""Deterministic metadata inference for EPUB packaging."""

import re
import uuid
from collections.abc import Sequence

from book2epub.ir.models import (
    Block,
    BookIR,
    BookMetadata,
    Heading,
    Paragraph,
    Text,
)

# Regex for Japanese Kana (Hiragana and Katakana)
KANA_PATTERN = re.compile(r"[\u3040-\u309F\u30A0-\u30FF]")
# Regex for Latin letters
LATIN_PATTERN = re.compile(r"[a-zA-Z]")
# Regex for CJK Unified Ideographs
CJK_PATTERN = re.compile(r"[\u4E00-\u9FFF]")


def infer_language_from_text(sample_text: str) -> str:
    """
    Deterministic language heuristic over sample text.

    - If Japanese kana is significant -> "ja"
    - Predominantly ASCII/Latin -> "en"
    - Otherwise -> "und"
    """
    if not sample_text:
        return "und"

    kana_count = len(KANA_PATTERN.findall(sample_text))
    latin_count = len(LATIN_PATTERN.findall(sample_text))
    cjk_count = len(CJK_PATTERN.findall(sample_text))
    total_letters = kana_count + latin_count + cjk_count

    if total_letters == 0:
        return "und"

    # If Japanese kana is significant (> 1% or >= 5 characters) -> Japanese
    if kana_count >= 5 or (kana_count > 0 and (kana_count / total_letters) > 0.01):
        return "ja"

    # Predominantly Latin (> 60% of total letters) -> English
    if latin_count / total_letters > 0.6:
        return "en"

    return "und"


def extract_sample_text(blocks: Sequence[Block], max_chars: int = 10000) -> str:
    """Extract up to max_chars letters/text from BookIR prose blocks."""
    collected: list[str] = []
    total = 0

    for block in blocks:
        if isinstance(block, (Paragraph, Heading)):
            for inline in block.inlines:
                if isinstance(inline, Text):
                    collected.append(inline.text)
                    total += len(inline.text)
                    if total >= max_chars:
                        break
        if total >= max_chars:
            break

    return "".join(collected)[:max_chars]


def infer_metadata(
    bookir: BookIR,
    cli_title: str | None = None,
    cli_language: str | None = None,
    cli_identifier: str | None = None,
    fallback_dir_name: str | None = None,
) -> BookMetadata:
    """
    Resolve final publication metadata using deterministic priority rules.

    Title priority:
    1. explicit CLI title
    2. IR metadata title
    3. first level-1 heading text
    4. fallback directory name or "Untitled Book"

    Language priority:
    1. explicit CLI language
    2. IR metadata language
    3. deterministic text heuristic over first 10,000 letters
    4. "und"

    Identifier priority:
    1. explicit CLI identifier
    2. IR metadata identifier
    3. generated urn:uuid:<uuid4>
    """
    meta = bookir.metadata

    # 1. Title
    final_title: str
    if cli_title and cli_title.strip():
        final_title = cli_title.strip()
    elif meta.title and meta.title.strip():
        final_title = meta.title.strip()
    else:
        # Search for first level-1 heading
        first_h1: str | None = None
        for block in bookir.blocks:
            if isinstance(block, Heading) and block.level == 1:
                heading_text = "".join(
                    i.text for i in block.inlines if isinstance(i, Text)
                ).strip()
                if heading_text:
                    first_h1 = heading_text
                    break

        if first_h1:
            final_title = first_h1
        elif fallback_dir_name and fallback_dir_name.strip():
            final_title = fallback_dir_name.strip()
        else:
            final_title = "Untitled Book"

    # 2. Language
    final_lang: str
    if cli_language and cli_language.strip():
        final_lang = cli_language.strip()
    elif meta.language and meta.language.strip() and meta.language != "auto":
        final_lang = meta.language.strip()
    else:
        sample = extract_sample_text(bookir.blocks, max_chars=10000)
        final_lang = infer_language_from_text(sample)

    # 3. Identifier
    final_id: str
    if cli_identifier and cli_identifier.strip():
        final_id = cli_identifier.strip()
    elif meta.identifier and meta.identifier.strip():
        final_id = meta.identifier.strip()
    else:
        final_id = f"urn:uuid:{uuid.uuid4()}"

    return BookMetadata(
        title=final_title,
        language=final_lang,
        identifier=final_id,
        authors=list(meta.authors),
        publisher=meta.publisher,
        cover_image_id=meta.cover_image_id,
    )
