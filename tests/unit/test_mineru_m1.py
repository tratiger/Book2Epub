"""Unit tests for MinerU discovery, validation, canonicalization, and inspection."""

import json
from pathlib import Path

import pytest

from book2epub.errors import MinerUError
from book2epub.mineru.canonical import canonicalize_mineru_output
from book2epub.mineru.discover import discover_middle_json
from book2epub.mineru.inspect import analyze_middle_json
from book2epub.mineru.validate import (
    validate_middle_json_root,
    verify_referenced_images_exist,
)
from tests.fixtures.synthetic_middle import sample_middle_dict


def test_validate_middle_json_root_success() -> None:
    data = sample_middle_dict()
    res = validate_middle_json_root(data, expected_page_count=1)
    assert res["_version_name"] == "3.4.5"
    assert res["_backend"] == "hybrid"


def test_validate_middle_json_rejects_wrong_version() -> None:
    data = sample_middle_dict(version="4.0.0a0")
    with pytest.raises(MinerUError) as exc_info:
        validate_middle_json_root(data)
    assert "Unsupported MinerU version" in str(exc_info.value)


def test_validate_middle_json_rejects_wrong_backend() -> None:
    data = sample_middle_dict(backend="pipeline")
    with pytest.raises(MinerUError) as exc_info:
        validate_middle_json_root(data)
    assert "Unsupported MinerU backend" in str(exc_info.value)


def test_validate_middle_json_rejects_page_count_mismatch() -> None:
    data = sample_middle_dict(page_count=2)
    with pytest.raises(MinerUError) as exc_info:
        validate_middle_json_root(data, expected_page_count=3)
    assert "page count mismatch" in str(exc_info.value)


def test_discover_middle_json_nested(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    nested_dir = raw_dir / "source" / "hybrid"
    nested_dir.mkdir(parents=True)
    middle_file = nested_dir / "source_middle.json"
    middle_file.write_text("{}", encoding="utf-8")

    discovered = discover_middle_json(raw_dir)
    assert discovered == middle_file


def test_discover_middle_json_rejects_multiple(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    (raw_dir / "dir1").mkdir(parents=True)
    (raw_dir / "dir2").mkdir(parents=True)
    (raw_dir / "dir1" / "one_middle.json").write_text("{}", encoding="utf-8")
    (raw_dir / "dir2" / "two_middle.json").write_text("{}", encoding="utf-8")

    with pytest.raises(MinerUError) as exc_info:
        discover_middle_json(raw_dir)
    assert "multiple candidate middle JSON files" in str(exc_info.value)


def test_canonicalize_and_referenced_images(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_images = raw_dir / "images"
    raw_images.mkdir(parents=True)

    img_file = raw_images / "fig1.png"
    img_file.write_bytes(b"\x89PNG dummy")

    data = sample_middle_dict()
    # Add an image span
    data["pdf_info"][0]["para_blocks"].append(
        {
            "type": "image",
            "blocks": [
                {
                    "type": "image_body",
                    "lines": [{"spans": [{"type": "image", "image_path": "images/fig1.png"}]}],
                }
            ],
        }
    )

    middle_path = raw_dir / "test_middle.json"
    middle_path.write_text(json.dumps(data), encoding="utf-8")

    canonical_dir = tmp_path / "canonical"
    canon_middle, canon_images = canonicalize_mineru_output(middle_path, canonical_dir)

    assert canon_middle.is_file()
    assert (canon_images / "fig1.png").is_file()
    assert (canonical_dir / "canonical-map.json").is_file()

    # Verify referenced image exists in canonical
    count, missing = verify_referenced_images_exist(canon_middle)
    assert count == 1
    assert len(missing) == 0


def test_analyze_middle_json(tmp_path: Path) -> None:
    data = sample_middle_dict(page_count=2)
    test_json = tmp_path / "sample_middle.json"
    test_json.write_text(json.dumps(data), encoding="utf-8")

    metrics = analyze_middle_json(test_json)
    assert metrics["page_count"] == 2
    assert metrics["version_name"] == "3.4.5"
    assert metrics["titles_with_level"] == 2
    assert metrics["titles_without_level"] == 0
