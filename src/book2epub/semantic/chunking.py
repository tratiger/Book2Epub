"""Dynamic document chunking with overlap and heading boundary awareness
(M8 spec Section 4, Appendix I5)."""

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from book2epub.config import SemanticConfig
from book2epub.semantic.book_state import BookState, get_book_state_prompt_view
from book2epub.semantic.models import DraftBlock, SemanticDraftBook
from book2epub.semantic.structure import BookOutline, OutlineContextItem, get_outline_prompt_view

PROMPT_CONTRACT_VERSION = "1.0"


class SemanticChunkInput(BaseModel):
    """Compact model-facing input for a single semantic chunk (Appendix H5)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    chunk_id: str
    block_ids: list[str]
    blocks: list[DraftBlock]
    preceding_outline: list[OutlineContextItem] = Field(default_factory=list)
    book_state: dict[str, Any] = Field(default_factory=dict)
    overlap_block_ids: list[str] = Field(default_factory=list)


def _compute_block_length(blk: DraftBlock) -> int:
    """Calculate codepoint length of a draft block's previews."""
    return (
        len(blk.text_preview or "")
        + len(blk.preformatted_preview or "")
        + len(blk.table_summary or "")
        + len(blk.caption_preview or "")
    )


def compute_chunk_id(
    index: int,
    blocks: list[DraftBlock],
    provider: str = "ollama",
    model: str = "default",
    prompt_contract_version: str = PROMPT_CONTRACT_VERSION,
) -> str:
    """Compute deterministic chunk ID: sem-{index:04d}-{sha256[:12]}."""
    hasher = hashlib.sha256()
    hasher.update(prompt_contract_version.encode("utf-8"))
    hasher.update(provider.encode("utf-8"))
    hasher.update(model.encode("utf-8"))
    for b in blocks:
        hasher.update(b.block_id.encode("utf-8"))
        hasher.update(b.content_sha256.encode("utf-8"))
    digest_12 = hasher.hexdigest()[:12]
    return f"sem-{index:04d}-{digest_12}"


def create_semantic_chunks(
    draft_book: SemanticDraftBook,
    cfg: SemanticConfig,
    outline: BookOutline | None = None,
    book_state: BookState | None = None,
    provider: str = "ollama",
    model: str = "default",
    save_dir: Path | None = None,
) -> list[SemanticChunkInput]:
    """
    Partition SemanticDraftBook into dynamic, overlapping chunks according to
    M8 spec Section 4 and Appendix I5.
    """
    all_blocks = draft_book.blocks
    if not all_blocks:
        return []

    max_chars = cfg.max_chunk_chars
    max_blocks = cfg.max_chunk_blocks
    overlap_target = 8

    chunks: list[SemanticChunkInput] = []
    chunk_index = 0
    curr_start_idx = 0
    total_blocks = len(all_blocks)

    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    while curr_start_idx < total_blocks:
        chunk_index += 1
        curr_chars = 0
        end_idx = curr_start_idx

        while end_idx < total_blocks:
            blk = all_blocks[end_idx]
            blk_len = _compute_block_length(blk)
            blk_count = end_idx - curr_start_idx + 1

            if (blk_count > max_blocks or (curr_chars + blk_len > max_chars)) and blk_count > 1:
                break

            curr_chars += blk_len
            end_idx += 1

        # Prefer a nearby heading boundary within the last 8 non-overlap blocks
        # when it keeps chunk size >= 50% of target
        non_overlap_start = (
            curr_start_idx + overlap_target if chunk_index > 1 else curr_start_idx
        )
        min_preferred_blocks = max_blocks // 2

        if (end_idx - curr_start_idx) >= min_preferred_blocks and end_idx < total_blocks:
            search_start = max(non_overlap_start, end_idx - 8)
            for cand_idx in range(end_idx - 1, search_start - 1, -1):
                cand_blk = all_blocks[cand_idx]
                if (
                    cand_blk.current_kind == "heading"
                    and (cand_idx - curr_start_idx) >= min_preferred_blocks
                ):
                    end_idx = cand_idx
                    break

        chunk_blocks = all_blocks[curr_start_idx:end_idx]
        block_ids = [b.block_id for b in chunk_blocks]

        # Calculate overlap blocks
        if chunk_index == 1:
            overlap_ids = []
        else:
            overlap_count = min(overlap_target, end_idx - curr_start_idx - 1)
            overlap_ids = [b.block_id for b in chunk_blocks[:overlap_count]]

        chunk_id = compute_chunk_id(
            index=chunk_index,
            blocks=chunk_blocks,
            provider=provider,
            model=model or "default",
        )

        outline_items: list[OutlineContextItem] = []
        if outline:
            outline_items = get_outline_prompt_view(
                outline=outline,
                current_block_id=chunk_blocks[0].block_id,
            )

        state_view: dict[str, Any] = {}
        if book_state:
            state_view = get_book_state_prompt_view(book_state)

        chunk_input = SemanticChunkInput(
            schema_version="1.0",
            chunk_id=chunk_id,
            block_ids=block_ids,
            blocks=chunk_blocks,
            preceding_outline=outline_items,
            book_state=state_view,
            overlap_block_ids=overlap_ids,
        )
        chunks.append(chunk_input)

        if save_dir:
            out_file = save_dir / f"{chunk_id}.input.json"
            out_file.write_text(chunk_input.model_dump_json(indent=2), encoding="utf-8")

        if end_idx >= total_blocks:
            break

        # Next chunk starts with final overlap_blocks of prior chunk
        next_start = max(curr_start_idx + 1, end_idx - overlap_target)
        curr_start_idx = next_start

    return chunks
