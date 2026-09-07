"""Directory scanner and validator for source page images."""

import logging
from pathlib import Path

from PIL import Image

from book2epub.errors import IngestError
from book2epub.ingest.models import IngestManifest, PageManifestItem
from book2epub.util.hashing import file_sha256
from book2epub.util.natural_sort import natural_sort

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
IGNORED_FILENAMES = {"desktop.ini", "thumbs.db", ".ds_store"}


def is_supported_page_file(path: Path) -> bool:
    """Check if path is a recognized non-hidden book page image."""
    name = path.name
    if name.startswith(".") or name.lower() in IGNORED_FILENAMES:
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def scan_and_validate_directory(
    input_dir: Path,
    manifest_output_path: Path | None = None,
) -> IngestManifest:
    """
    Scan a directory of page images, naturally sort them, validate each, and build a manifest.

    Raises IngestError if:
    - input_dir is not a directory.
    - no supported images are found.
    - any image is corrupt, undecodable, or has zero dimension.
    """
    if not input_dir.is_dir():
        raise IngestError(f"Input directory does not exist or is not a directory: {input_dir}")

    # Gather non-recursive entries
    candidates: list[Path] = [
        p for p in input_dir.iterdir() if p.is_file() and is_supported_page_file(p)
    ]

    if not candidates:
        raise IngestError(
            f"No supported page images found in '{input_dir}'. "
            f"Supported extensions: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    # Deterministic natural sort
    ordered_paths = natural_sort(candidates)

    if logger.isEnabledFor(logging.DEBUG):
        sample_first = [p.name for p in ordered_paths[:5]]
        sample_last = [p.name for p in ordered_paths[-5:]]
        logger.debug("Ordered first 5 pages: %s", sample_first)
        logger.debug("Ordered last 5 pages: %s", sample_last)

    seen_hashes: dict[str, str] = {}
    page_items: list[PageManifestItem] = []
    warnings: list[str] = []
    duplicate_count = 0

    for idx, path in enumerate(ordered_paths):
        # 1. Read byte size
        stat = path.stat()
        byte_size = stat.st_size
        if byte_size == 0:
            raise IngestError(f"Page file '{path.name}' is empty (0 bytes).")

        # 2. Compute SHA-256
        sha = file_sha256(path)

        # 3. Read image dimensions with Pillow without re-encoding
        try:
            with Image.open(path) as img:
                width, height = img.size
                img.verify()  # verify integrity of the image file
        except Exception as e:
            raise IngestError(f"Corrupt or unreadable image '{path.name}': {e}") from e

        if width <= 0 or height <= 0:
            raise IngestError(f"Invalid dimensions for page '{path.name}': {width}x{height}")

        aspect_ratio = round(width / height, 4)
        is_extreme = aspect_ratio < 0.35 or aspect_ratio > 2.0
        if is_extreme:
            msg = (
                f"Page {idx + 1} ('{path.name}') has extreme aspect ratio: "
                f"{aspect_ratio:.4f} ({width}x{height})."
            )
            logger.warning(msg)
            warnings.append(msg)

        # Check for byte-identical duplicates
        is_dup = False
        if sha in seen_hashes:
            is_dup = True
            duplicate_count += 1
            msg = (
                f"Page {idx + 1} ('{path.name}') is byte-identical to "
                f"earlier page '{seen_hashes[sha]}'."
            )
            logger.warning(msg)
            warnings.append(msg)
        else:
            seen_hashes[sha] = path.name

        item = PageManifestItem(
            page_index=idx,
            filename=path.name,
            relative_path=path.name,
            sha256=sha,
            byte_size=byte_size,
            width=width,
            height=height,
            suffix=path.suffix.lower(),
            aspect_ratio=aspect_ratio,
            is_duplicate=is_dup,
            extreme_aspect_ratio=is_extreme,
        )
        page_items.append(item)

    manifest = IngestManifest(
        source_dir=str(input_dir.resolve()),
        total_pages=len(page_items),
        pages=page_items,
        duplicate_count=duplicate_count,
        warnings=warnings,
    )

    if manifest_output_path is not None:
        manifest_output_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_output_path.write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info("Saved manifest (%d pages) to %s", len(page_items), manifest_output_path)

    return manifest
