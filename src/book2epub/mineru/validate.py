"""Validation of MinerU middle.json structure, versions, and referenced assets."""

import json
import logging
from pathlib import Path
from typing import Any

from book2epub.errors import MinerUError

logger = logging.getLogger(__name__)


def validate_middle_json_root(
    data: dict[str, Any],
    expected_page_count: int | None = None,
) -> dict[str, Any]:
    """
    Validate the root structure and metadata of a parsed MinerU middle.json.

    Enforces:
    - _version_name == "3.4.5"
    - _backend == "hybrid"
    - _effort == "high" (warns if absent)
    - pdf_info is a list with expected_page_count elements
    """
    version_name = data.get("_version_name")
    if version_name != "3.4.5":
        raise MinerUError(
            f"Unsupported MinerU version: '{version_name}'. "
            "Book2Epub strictly requires MinerU 3.4.5."
        )

    backend = data.get("_backend")
    if backend != "hybrid":
        raise MinerUError(
            f"Unsupported MinerU backend: '{backend}'. "
            "Book2Epub strictly requires 'hybrid' backend in middle.json."
        )

    effort = data.get("_effort")
    if effort is not None and effort != "high":
        raise MinerUError(
            f"MinerU effort was '{effort}'. Book2Epub requires high effort for full analysis."
        )
    elif effort is None:
        logger.warning(
            "MinerU middle.json does not contain '_effort' field; "
            "continuing under hybrid 3.4.5 contract."
        )

    pdf_info = data.get("pdf_info")
    if not isinstance(pdf_info, list):
        raise MinerUError("MinerU middle.json missing valid 'pdf_info' list at root.")

    if expected_page_count is not None and len(pdf_info) != expected_page_count:
        raise MinerUError(
            f"MinerU page count mismatch: 'pdf_info' has {len(pdf_info)} pages, "
            f"expected {expected_page_count} pages from source PDF."
        )

    return data


def extract_referenced_image_paths(data: dict[str, Any]) -> list[str]:
    """Recursively find all 'image_path' string values in middle.json."""
    found: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "image_path" and isinstance(v, str) and v:
                    found.append(v)
                else:
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data.get("pdf_info", []))
    return found


def verify_referenced_images_exist(
    middle_json_path: Path,
    data: dict[str, Any] | None = None,
) -> tuple[int, list[str]]:
    """
    Verify that all image paths referenced in middle.json exist on disk.

    Returns (total_referenced_count, list_of_missing_paths).
    """
    if data is None:
        with middle_json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

    image_paths = extract_referenced_image_paths(data)
    base_dir = middle_json_path.parent

    missing: list[str] = []
    for rel_path in image_paths:
        target = base_dir / rel_path
        if not target.is_file() and (base_dir / "images" / rel_path).is_file():
            target = base_dir / "images" / rel_path
        if not target.is_file():
            missing.append(rel_path)

    return len(image_paths), missing
