"""Lossless source PDF generation using img2pdf."""

import logging
from pathlib import Path

import img2pdf
import pypdfium2

from book2epub.errors import IngestError
from book2epub.ingest.models import IngestManifest

logger = logging.getLogger(__name__)


def create_source_pdf(
    manifest: IngestManifest,
    input_dir: Path,
    output_pdf_path: Path,
) -> Path:
    """
    Assemble naturally ordered page images into a single multi-page source PDF.

    Rules:
    - Uses img2pdf for lossless embedding.
    - Handles malformed EXIF orientation safely via Rotation.ifvalid.
    - Verifies generated PDF page count matches manifest page count.
    """
    if not manifest.pages:
        raise IngestError("Cannot create source PDF from an empty manifest.")

    image_paths: list[str] = [
        str((input_dir / page.relative_path).resolve()) for page in manifest.pages
    ]

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Generating multi-page source PDF with %d pages...", len(image_paths))

    try:
        pdf_bytes = img2pdf.convert(
            image_paths,
            rotation=img2pdf.Rotation.ifvalid,
        )
        output_pdf_path.write_bytes(pdf_bytes)
    except Exception as e:
        raise IngestError(f"Failed to generate source PDF with img2pdf: {e}") from e

    # Verify page count with pypdfium2
    try:
        pdf_doc = pypdfium2.PdfDocument(output_pdf_path)
        actual_page_count = len(pdf_doc)
        pdf_doc.close()
    except Exception as e:
        raise IngestError(f"Failed to verify generated source PDF '{output_pdf_path}': {e}") from e

    expected_page_count = len(manifest.pages)
    if actual_page_count != expected_page_count:
        raise IngestError(
            f"Source PDF page count mismatch: expected {expected_page_count} pages, "
            f"but generated PDF has {actual_page_count} pages."
        )

    logger.info(
        "Successfully created source PDF: %s (%d pages, %.2f MB)",
        output_pdf_path,
        actual_page_count,
        output_pdf_path.stat().st_size / (1024 * 1024),
    )
    return output_pdf_path
