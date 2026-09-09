"""Deterministic hashing utilities for semantic evidence and decision integrity."""

import hashlib
import json
from pathlib import Path


def compute_text_sha256(text: str) -> str:
    """Compute SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_bytes_sha256(data: bytes) -> str:
    """Compute SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest of file contents."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def compute_content_sha256(
    plain_text: str | None = None,
    preformatted_text: str | None = None,
    table_html_text_content: str | None = None,
    caption_text: str | None = None,
    footnote_text: str | None = None,
) -> str:
    """
    Compute a deterministic canonical content hash across all visible representations
    of a block (M6 spec Section 4.5).
    """
    obj = {
        "caption_text": caption_text or "",
        "footnote_text": footnote_text or "",
        "plain_text": plain_text or "",
        "preformatted_text": preformatted_text or "",
        "table_html_text_content": table_html_text_content or "",
    }
    canonical_json = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
