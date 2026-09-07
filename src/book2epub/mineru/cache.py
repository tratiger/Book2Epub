"""Stage caching logic for MinerU stage."""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from book2epub.mineru.validate import verify_referenced_images_exist
from book2epub.util.hashing import file_sha256

logger = logging.getLogger(__name__)


class MinerUStageInfo(BaseModel):
    """Metadata recorded in mineru/stage.json."""

    state: str = Field(description="Stage state: complete or failed")
    cache_key: str = Field(description="SHA-256 cache identity key")
    mineru_version: str = Field(default="3.4.5")
    backend: str = Field(default="hybrid-engine")
    middle_json_sha256: str = Field(description="SHA-256 of canonical book_middle.json")
    page_count: int = Field(description="Page count parsed from middle.json")


def load_stage_info(stage_file: Path) -> MinerUStageInfo | None:
    """Load and parse mineru/stage.json if it exists and is valid."""
    if not stage_file.is_file():
        return None
    try:
        data = json.loads(stage_file.read_text(encoding="utf-8"))
        return MinerUStageInfo.model_validate(data)
    except Exception as e:
        logger.warning("Failed to parse existing stage file %s: %e", stage_file, e)
        return None


def is_mineru_cache_valid(
    stage_file: Path,
    expected_cache_key: str,
    canonical_middle_json: Path,
) -> bool:
    """
    Check if the MinerU stage can be safely skipped.

    Conditions:
    1. stage.json exists and state is 'complete'
    2. cache_key matches expected_cache_key
    3. canonical book_middle.json exists and sha256 matches
    4. all referenced image assets exist on disk
    """
    stage_info = load_stage_info(stage_file)
    if not stage_info:
        logger.debug("Cache miss: stage.json does not exist or is invalid.")
        return False

    if stage_info.state != "complete":
        logger.debug("Cache miss: stage state is '%s' (not complete).", stage_info.state)
        return False

    if stage_info.cache_key != expected_cache_key:
        logger.debug(
            "Cache miss: cache_key mismatch (recorded=%s, expected=%s).",
            stage_info.cache_key,
            expected_cache_key,
        )
        return False

    if not canonical_middle_json.is_file():
        logger.debug(
            "Cache miss: canonical middle.json does not exist at %s.", canonical_middle_json
        )
        return False

    actual_hash = file_sha256(canonical_middle_json)
    if actual_hash != stage_info.middle_json_sha256:
        logger.debug("Cache miss: canonical middle.json SHA-256 mismatch.")
        return False

    # Check referenced images
    total_imgs, missing = verify_referenced_images_exist(canonical_middle_json)
    if missing:
        logger.debug("Cache miss: %d referenced images missing: %s", len(missing), missing[:3])
        return False

    logger.info(
        "MinerU stage cache hit! (key=%s, pages=%d)",
        expected_cache_key[:12],
        stage_info.page_count,
    )
    return True


def record_mineru_stage_complete(
    stage_file: Path,
    cache_key: str,
    mineru_version: str,
    backend: str,
    canonical_middle_json: Path,
    page_count: int,
) -> None:
    """Record successful completion of MinerU stage in mineru/stage.json."""
    stage_file.parent.mkdir(parents=True, exist_ok=True)
    middle_hash = file_sha256(canonical_middle_json)
    stage_info = MinerUStageInfo(
        state="complete",
        cache_key=cache_key,
        mineru_version=mineru_version,
        backend=backend,
        middle_json_sha256=middle_hash,
        page_count=page_count,
    )
    stage_file.write_text(stage_info.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Recorded complete MinerU stage to %s", stage_file)


def record_mineru_stage_failed(
    stage_file: Path,
    cache_key: str,
    mineru_version: str,
    backend: str,
) -> None:
    """Record failure of MinerU stage in mineru/stage.json."""
    stage_file.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "state": "failed",
        "cache_key": cache_key,
        "mineru_version": mineru_version,
        "backend": backend,
    }
    stage_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Recorded failed MinerU stage to %s", stage_file)
