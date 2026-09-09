"""BBox coordinate mapping and image crop generation (M9 Section 4, Appendix K2)."""

import logging
from pathlib import Path

from PIL import Image

from book2epub.errors import SemanticError

logger = logging.getLogger(__name__)


def map_and_crop(
    page_img: Image.Image,
    bbox: list[float] | tuple[float, float, float, float],
    source_page_size: list[int] | tuple[int, int],
    crops_dir: Path,
    crop_name: str,
    is_segment: bool = False,
) -> tuple[Path, Image.Image]:
    """
    Map MinerU middle.json bbox coordinates to rendered page pixels, apply padding,
    clamp to page boundaries, and save as PNG.

    Padding rules:
    - Block crop: max(12 px, 0.04 * crop_dimension)
    - Segment/line crop: 8% (0.08 * crop_dimension)
    """
    rw, rh = page_img.size
    sw, sh = source_page_size[0], source_page_size[1]

    if sw <= 0 or sh <= 0:
        raise SemanticError(f"Invalid source_page_size: {source_page_size}")

    sx = rw / sw
    sy = rh / sh

    x0, y0, x1, y1 = bbox
    left = x0 * sx
    top = y0 * sy
    right = x1 * sx
    bottom = y1 * sy

    crop_w = max(1.0, right - left)
    crop_h = max(1.0, bottom - top)

    if is_segment:
        pad_x = 0.08 * crop_w
        pad_y = 0.08 * crop_h
    else:
        pad_x = max(12.0, 0.04 * crop_w)
        pad_y = max(12.0, 0.04 * crop_h)

    c_left = max(0, int(left - pad_x))
    c_top = max(0, int(top - pad_y))
    c_right = min(rw, max(c_left + 1, int(right + pad_x)))
    c_bottom = min(rh, max(c_top + 1, int(bottom + pad_y)))

    crop_img = page_img.crop((c_left, c_top, c_right, c_bottom))

    crops_dir.mkdir(parents=True, exist_ok=True)
    crop_path = crops_dir / f"{crop_name}.png"
    crop_img.save(crop_path, "PNG")

    return crop_path, crop_img
