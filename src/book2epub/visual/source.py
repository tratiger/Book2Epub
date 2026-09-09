"""Visual evidence source discovery and validation (M9 Section 2, Appendix K1)."""

import hashlib
import logging
import re
from pathlib import Path
from typing import Self

from book2epub.config import JobConfig
from book2epub.errors import ConfigurationError
from book2epub.paths import JobPaths

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def natural_sort_key(p: Path) -> list[int | str]:
    """Generate key for natural human sorting of filenames containing numbers."""
    parts = re.split(r"(\d+)", p.name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


class VisualSource:
    """
    Encapsulates source visual evidence from PDF or rectified page image directory.
    Provides page-level resolution and cache hashing.
    """

    def __init__(
        self,
        pdf_path: Path | None = None,
        images_dir: Path | None = None,
    ) -> None:
        self.pdf_path: Path | None = pdf_path
        self.images_dir: Path | None = images_dir
        self.page_images: list[Path] = []
        self._source_hash: str | None = None

        if self.images_dir and self.images_dir.is_dir():
            files = [
                p
                for p in self.images_dir.iterdir()
                if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
            ]
            self.page_images = sorted(files, key=natural_sort_key)

    @property
    def has_visual(self) -> bool:
        """Return True if a valid visual source is available."""
        if self.pdf_path and self.pdf_path.is_file():
            return True
        if self.images_dir and len(self.page_images) > 0:
            return True
        return False

    @property
    def source_hash(self) -> str:
        """Compute SHA-256 of source file/directory for raster cache keys."""
        if self._source_hash is not None:
            return self._source_hash

        h = hashlib.sha256()
        if self.pdf_path and self.pdf_path.is_file():
            with self.pdf_path.open("rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
        elif self.page_images:
            for p in self.page_images:
                h.update(p.name.encode("utf-8"))
                h.update(str(p.stat().st_size).encode("utf-8"))
        else:
            h.update(b"none")

        self._source_hash = h.hexdigest()
        return self._source_hash

    @classmethod
    def resolve(
        cls,
        cfg: JobConfig,
        paths: JobPaths | None = None,
        source_pdf: Path | None = None,
        source_images_dir: Path | None = None,
    ) -> Self:
        """
        Discover visual source per M9 priority rules:
        1. explicit source_pdf parameter or cfg.app.source_pdf
        2. auto-discovered input/source.pdf in paths.input_dir or job workspace ancestor
        3. explicit source_images_dir parameter or cfg.app.source_images_dir
        4. none
        """
        chosen_pdf: Path | None = None
        chosen_images_dir: Path | None = None

        # 1. Explicit source PDF
        pdf_candidate = source_pdf or getattr(cfg.app, "source_pdf", None)
        if pdf_candidate and Path(pdf_candidate).is_file():
            chosen_pdf = Path(pdf_candidate)

        # 2. Auto-discovered input/source.pdf
        if not chosen_pdf and paths is not None:
            job_pdf = paths.source_pdf_file
            if job_pdf.is_file():
                chosen_pdf = job_pdf
            else:
                # Check ancestor directories (e.g. if running in subfolder)
                curr = paths.root
                for _ in range(3):
                    cand = curr / "input" / "source.pdf"
                    if cand.is_file():
                        chosen_pdf = cand
                        break
                    curr = curr.parent

        # 3. Explicit images directory
        if not chosen_pdf:
            img_candidate = source_images_dir or getattr(cfg.app, "source_images_dir", None)
            if img_candidate and Path(img_candidate).is_dir():
                chosen_images_dir = Path(img_candidate)

        visual_source = cls(pdf_path=chosen_pdf, images_dir=chosen_images_dir)

        # Enforce configuration rules (Appendix K1, M9 Section 2)
        if cfg.semantic.vision == "on" and not visual_source.has_visual:
            raise ConfigurationError(
                "Visual review is set to 'on' (--semantic-vision on), "
                "but no source PDF or source images directory was found."
            )

        if cfg.ocr_correction.mode in ("safe", "all") and not visual_source.has_visual:
            raise ConfigurationError(
                f"OCR correction mode '{cfg.ocr_correction.mode}' requires source visual evidence, "
                "but no source PDF or source images directory was found."
            )

        if cfg.semantic.vision == "auto" and not visual_source.has_visual:
            logger.warning(
                "VISUAL_SOURCE_UNAVAILABLE: No source visual evidence found. "
                "Continuing in text-only semantic mode."
            )

        return visual_source
