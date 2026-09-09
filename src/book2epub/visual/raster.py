"""Page rasterization with on-demand local disk caching (M9 Section 3, Appendix K2)."""

import logging
from pathlib import Path

from PIL import Image

from book2epub.errors import SemanticError
from book2epub.visual.source import VisualSource

logger = logging.getLogger(__name__)


class PageRasterCache:
    """
    On-demand page rasterizer with disk caching under semantic/visual/pages/.
    Renders RGB images with specified maximum edge dimension.
    """

    def __init__(self, cache_dir: Path, visual_source: VisualSource) -> None:
        self.cache_dir = cache_dir
        self.visual_source = visual_source
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._pdf_doc: object | None = None

    def _get_pdf_doc(self) -> object:
        if self._pdf_doc is None:
            if not self.visual_source.pdf_path or not self.visual_source.pdf_path.is_file():
                raise SemanticError("No valid source PDF available for page rasterization.")
            import pypdfium2

            self._pdf_doc = pypdfium2.PdfDocument(self.visual_source.pdf_path)
        return self._pdf_doc

    def get_page_image(
        self,
        page_idx: int,
        max_edge: int = 1800,
    ) -> tuple[Path, Image.Image]:
        """
        Retrieve rendered RGB PIL Image and cached path for requested page_idx.
        Current page uses max_edge <= 1800 px, neighbor context uses max_edge <= 1200 px.
        """
        cached_path = self.cache_dir / f"page_{page_idx:05d}_{max_edge}px.jpg"
        if cached_path.is_file():
            img = Image.open(cached_path).convert("RGB")
            return cached_path, img

        # Not cached -> rasterize on-demand
        if self.visual_source.pdf_path and self.visual_source.pdf_path.is_file():
            doc = self._get_pdf_doc()
            try:
                page = doc[page_idx]  # type: ignore[index]
            except Exception as exc:
                raise SemanticError(f"Failed to access PDF page {page_idx}: {exc}") from exc

            orig_w, orig_h = page.get_width(), page.get_height()
            longest = max(orig_w, orig_h)
            scale = (max_edge / longest) if longest > 0 else 1.0

            rendered = page.render(scale=scale).to_pil().convert("RGB")
            rendered.save(cached_path, "JPEG", quality=90)
            return cached_path, rendered

        elif self.visual_source.page_images:
            if page_idx < 0 or page_idx >= len(self.visual_source.page_images):
                raise SemanticError(
                    f"Page index {page_idx} out of bounds for source images "
                    f"(total {len(self.visual_source.page_images)})."
                )

            src_img_path = self.visual_source.page_images[page_idx]
            raw_img = Image.open(src_img_path).convert("RGB")
            w, h = raw_img.size
            longest = max(w, h)

            if longest > max_edge:
                ratio = max_edge / longest
                new_w = max(1, int(w * ratio))
                new_h = max(1, int(h * ratio))
                img = raw_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            else:
                img = raw_img

            img.save(cached_path, "JPEG", quality=90)
            return cached_path, img

        raise SemanticError(f"No visual source available to render page {page_idx}.")
