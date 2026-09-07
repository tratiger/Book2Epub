"""Canonicalization of MinerU artifacts into stable directory layout."""

import json
import logging
import shutil
from pathlib import Path

from book2epub.errors import MinerUError

logger = logging.getLogger(__name__)


def canonicalize_mineru_output(
    raw_middle_json: Path,
    canonical_dir: Path,
) -> tuple[Path, Path]:
    """
    Copy authoritative MinerU output to canonical area without modifying raw tree.

    Destination layout:
      canonical_dir/
        book_middle.json
        images/
        canonical-map.json

    Returns (canonical_middle_json_path, canonical_images_dir_path).
    """
    if not raw_middle_json.is_file():
        raise MinerUError(f"Raw middle JSON does not exist: {raw_middle_json}")

    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical_middle_json = canonical_dir / "book_middle.json"
    canonical_images_dir = canonical_dir / "images"
    canonical_images_dir.mkdir(parents=True, exist_ok=True)

    # 1. Byte-for-byte copy of middle.json
    shutil.copy2(raw_middle_json, canonical_middle_json)
    logger.info("Copied canonical middle JSON to: %s", canonical_middle_json)

    # 2. Copy image assets
    raw_parent = raw_middle_json.parent
    raw_images_dir = raw_parent / "images"

    copy_map: dict[str, str] = {
        str(raw_middle_json.resolve()): str(canonical_middle_json.resolve())
    }

    if raw_images_dir.is_dir():
        for item in raw_images_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(raw_images_dir)
                dest = canonical_images_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
                copy_map[str(item.resolve())] = str(dest.resolve())
        logger.info("Copied image assets from %s to %s", raw_images_dir, canonical_images_dir)
    else:
        logger.warning("No 'images' directory found at %s", raw_images_dir)

    # 3. Store canonical-map.json
    map_file = canonical_dir / "canonical-map.json"
    manifest_info = {
        "raw_middle_json": str(raw_middle_json.resolve()),
        "canonical_middle_json": str(canonical_middle_json.resolve()),
        "canonical_images_dir": str(canonical_images_dir.resolve()),
        "file_copies": copy_map,
    }
    map_file.write_text(json.dumps(manifest_info, indent=2), encoding="utf-8")

    return canonical_middle_json, canonical_images_dir
