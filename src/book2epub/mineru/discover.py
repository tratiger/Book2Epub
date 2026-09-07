"""Discovery of MinerU middle.json intermediate output."""

import logging
from pathlib import Path

from book2epub.errors import MinerUError

logger = logging.getLogger(__name__)


def discover_middle_json(raw_output_dir: Path) -> Path:
    """
    Recursively search the raw MinerU output tree for *_middle.json.

    Requires exactly one candidate. Raises MinerUError if 0 or >1 candidates exist.
    """
    if not raw_output_dir.is_dir():
        raise MinerUError(f"Raw MinerU output directory does not exist: {raw_output_dir}")

    candidates = list(raw_output_dir.rglob("*_middle.json"))

    if not candidates:
        raise MinerUError(
            f"No '*_middle.json' found in MinerU raw output directory '{raw_output_dir}'."
        )

    if len(candidates) > 1:
        candidate_paths = [str(p) for p in candidates]
        raise MinerUError(
            f"Found multiple candidate middle JSON files in '{raw_output_dir}': {candidate_paths}. "
            "Expected exactly one candidate for a single-book job."
        )

    middle_path = candidates[0]
    logger.info("Discovered authoritative MinerU middle.json: %s", middle_path)
    return middle_path
