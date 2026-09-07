"""Unit tests for SHA-256 hashing utilities."""

from pathlib import Path

from book2epub.util.hashing import (
    bytes_sha256,
    compute_mineru_cache_key,
    file_sha256,
    string_sha256,
)


def test_string_sha256_deterministic() -> None:
    h1 = string_sha256("hello world")
    h2 = string_sha256("hello world")
    assert h1 == h2
    assert h1 == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_bytes_sha256_deterministic() -> None:
    data = b"sample byte content"
    h1 = bytes_sha256(data)
    h2 = bytes_sha256(data)
    assert h1 == h2


def test_file_sha256(tmp_path: Path) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"deterministic file content")
    digest = file_sha256(test_file)
    assert digest == bytes_sha256(b"deterministic file content")


def test_mineru_cache_key_stability_and_sensitivity() -> None:
    key1 = compute_mineru_cache_key(
        file_hashes=["hash1", "hash2"],
        relative_names=["page1.jpg", "page2.jpg"],
        mineru_version="3.4.5",
        backend="hybrid-engine",
        effort="high",
        ocr=True,
        formula=True,
        table=True,
        image_analysis=True,
    )
    # Exactly identical inputs yield identical key
    key2 = compute_mineru_cache_key(
        file_hashes=["hash1", "hash2"],
        relative_names=["page1.jpg", "page2.jpg"],
        mineru_version="3.4.5",
        backend="hybrid-engine",
        effort="high",
        ocr=True,
        formula=True,
        table=True,
        image_analysis=True,
    )
    assert key1 == key2

    # Changing any component changes the cache key
    key_diff_hash = compute_mineru_cache_key(
        file_hashes=["hash1", "hash_different"],
        relative_names=["page1.jpg", "page2.jpg"],
        mineru_version="3.4.5",
        backend="hybrid-engine",
        effort="high",
        ocr=True,
        formula=True,
        table=True,
        image_analysis=True,
    )
    assert key1 != key_diff_hash

    key_diff_effort = compute_mineru_cache_key(
        file_hashes=["hash1", "hash2"],
        relative_names=["page1.jpg", "page2.jpg"],
        mineru_version="3.4.5",
        backend="hybrid-engine",
        effort="medium",
        ocr=True,
        formula=True,
        table=True,
        image_analysis=True,
    )
    assert key1 != key_diff_effort
