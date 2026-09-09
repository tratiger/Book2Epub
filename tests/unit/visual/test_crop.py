"""Unit tests for bbox coordinate mapping, crop extraction, and raster caching (M9 Section 3-4)."""

from pathlib import Path

from PIL import Image

from book2epub.visual.crop import map_and_crop
from book2epub.visual.raster import PageRasterCache
from book2epub.visual.source import VisualSource


def test_map_and_crop_block_scaling_and_padding(tmp_path: Path) -> None:
    """Verify that bbox is scaled from middle coordinates, padded by at least 12px, and clamped."""
    # Rendered page: 600 x 800
    page_img = Image.new("RGB", (600, 800), color="white")
    source_page_size = [300, 400]  # Scale factor is 2.0

    # Middle bbox: [50, 50, 100, 100] -> unpadded rendered pixels: [100, 100, 200, 200]
    bbox = [50.0, 50.0, 100.0, 100.0]
    crops_dir = tmp_path / "crops"

    crop_path, crop_img = map_and_crop(
        page_img=page_img,
        bbox=bbox,
        source_page_size=source_page_size,
        crops_dir=crops_dir,
        crop_name="test-block-01",
        is_segment=False,
    )

    assert crop_path.is_file()
    assert crop_path.suffix == ".png"

    # Width: 200 - 100 = 100. Pad: max(12, 0.04 * 100) = 12.
    # Expected bounds: [100 - 12, 100 - 12, 200 + 12, 200 + 12] = [88, 88, 212, 212]
    # Dimensions: 124 x 124
    w, h = crop_img.size
    assert w == 124
    assert h == 124


def test_map_and_crop_clamping_to_page_boundaries(tmp_path: Path) -> None:
    """Verify that padding does not exceed page boundaries (clamped to 0 and page dimensions)."""
    page_img = Image.new("RGB", (500, 500), color="blue")
    source_page_size = [500, 500]

    # BBox touching top-left corner
    bbox = [0.0, 0.0, 50.0, 50.0]
    crops_dir = tmp_path / "crops"

    _, crop_img = map_and_crop(
        page_img=page_img,
        bbox=bbox,
        source_page_size=source_page_size,
        crops_dir=crops_dir,
        crop_name="corner-block",
        is_segment=False,
    )

    # Left and top must clamp at 0
    # Right and bottom padded by 12px -> 50 + 12 = 62
    assert crop_img.size == (62, 62)


def test_map_and_crop_segment_padding(tmp_path: Path) -> None:
    """Verify that segment/line crops use 8% padding (M9 Section 4)."""
    page_img = Image.new("RGB", (1000, 1000), color="white")
    source_page_size = [1000, 1000]

    # Dimension: 100 x 50. 8% of 100 is 8, 8% of 50 is 4.
    bbox = [200.0, 200.0, 300.0, 250.0]
    crops_dir = tmp_path / "crops"

    _, crop_img = map_and_crop(
        page_img=page_img,
        bbox=bbox,
        source_page_size=source_page_size,
        crops_dir=crops_dir,
        crop_name="segment-01",
        is_segment=True,
    )

    # Bounds: [200 - 8, 200 - 4, 300 + 8, 250 + 4] = [192, 196, 308, 254]
    # Width = 308 - 192 = 116. Height = 254 - 196 = 58.
    assert crop_img.size == (116, 58)


def test_page_raster_cache_images_source(tmp_path: Path) -> None:
    """Verify on-demand rasterization and caching from source images directory."""
    images_dir = tmp_path / "source_images"
    images_dir.mkdir()

    # Create dummy source page image (2400 x 3200)
    p0 = images_dir / "page_001.png"
    Image.new("RGB", (2400, 3200), color="yellow").save(p0)

    visual_source = VisualSource(images_dir=images_dir)
    assert visual_source.has_visual is True

    cache_dir = tmp_path / "cache"
    cache = PageRasterCache(cache_dir=cache_dir, visual_source=visual_source)

    # Request page 0 with max_edge=1800
    img_path, img = cache.get_page_image(page_idx=0, max_edge=1800)
    assert img_path.is_file()
    assert img_path.name == "page_00000_1800px.jpg"

    # Longest edge (height) scaled down to 1800
    assert img.size[1] == 1800
    assert img.size[0] == int(2400 * (1800 / 3200))

    # Second call uses disk cache
    cached_mtime = img_path.stat().st_mtime
    path2, img2 = cache.get_page_image(page_idx=0, max_edge=1800)
    assert path2 == img_path
    assert path2.stat().st_mtime == cached_mtime
