"""Deterministic SHA-256 hashing utilities."""

import hashlib
import json
from pathlib import Path
from typing import Any

INGEST_SCHEMA_VERSION = "1.0"


def file_sha256(path: Path, chunk_size: int = 65536) -> str:
    """Compute hex-encoded SHA-256 digest of a file by streaming in chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def bytes_sha256(data: bytes) -> str:
    """Compute hex-encoded SHA-256 digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def string_sha256(text: str) -> str:
    """Compute hex-encoded SHA-256 digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_mineru_cache_key(
    file_hashes: list[str],
    relative_names: list[str],
    mineru_version: str,
    backend: str,
    effort: str,
    ocr: bool,
    formula: bool,
    table: bool,
    image_analysis: bool,
    ingest_schema_version: str = INGEST_SCHEMA_VERSION,
) -> str:
    """
    Compute MinerU stage cache key according to the architecture contract.

    Components:
    - ordered input-file SHA-256 values
    - ordered relative input names
    - MinerU version
    - backend
    - effort
    - OCR/formula/table/image-analysis settings
    - Book2Epub ingest schema version
    """
    payload: dict[str, Any] = {
        "file_hashes": file_hashes,
        "relative_names": relative_names,
        "mineru_version": mineru_version,
        "backend": backend,
        "effort": effort,
        "ocr": ocr,
        "formula": formula,
        "table": table,
        "image_analysis": image_analysis,
        "ingest_schema_version": ingest_schema_version,
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return string_sha256(canonical_json)
