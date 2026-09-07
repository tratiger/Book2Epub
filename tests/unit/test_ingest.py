"""Unit tests for ingest scanning, validation, and PDF creation."""

from pathlib import Path

import pytest
from PIL import Image

from book2epub.errors import IngestError
from book2epub.ingest.pdf import create_source_pdf
from book2epub.ingest.scanner import scan_and_validate_directory


def create_dummy_image(
    path: Path, width: int = 100, height: int = 150, color: str = "white"
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=color)
    img.save(path)


def test_scan_and_validate_basic_ordering(tmp_path: Path) -> None:
    img_dir = tmp_path / "pages"
    img_dir.mkdir()

    create_dummy_image(img_dir / "p10.png")
    create_dummy_image(img_dir / "p2.jpg")
    create_dummy_image(img_dir / "p1.png")

    manifest = scan_and_validate_directory(img_dir, manifest_output_path=tmp_path / "manifest.json")
    assert manifest.total_pages == 3
    assert [p.filename for p in manifest.pages] == ["p1.png", "p2.jpg", "p10.png"]
    assert (tmp_path / "manifest.json").is_file()


def test_scan_and_validate_ignores_system_files(tmp_path: Path) -> None:
    img_dir = tmp_path / "pages"
    img_dir.mkdir()

    create_dummy_image(img_dir / "p1.jpg")
    (img_dir / "desktop.ini").write_text("system", encoding="utf-8")
    (img_dir / "Thumbs.db").write_text("system", encoding="utf-8")
    (img_dir / ".hidden_page.png").write_text("hidden", encoding="utf-8")

    manifest = scan_and_validate_directory(img_dir)
    assert manifest.total_pages == 1
    assert manifest.pages[0].filename == "p1.jpg"


def test_scan_and_validate_no_images_raises(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(IngestError) as exc_info:
        scan_and_validate_directory(empty_dir)
    assert "No supported page images found" in str(exc_info.value)


def test_scan_and_validate_duplicate_detection(tmp_path: Path) -> None:
    img_dir = tmp_path / "pages"
    img_dir.mkdir()

    create_dummy_image(img_dir / "page1.png", color="blue")
    create_dummy_image(img_dir / "page2.png", color="blue")  # identical content

    manifest = scan_and_validate_directory(img_dir)
    assert manifest.total_pages == 2
    assert manifest.duplicate_count == 1
    assert manifest.pages[0].is_duplicate is False
    assert manifest.pages[1].is_duplicate is True
    assert len(manifest.warnings) >= 1


def test_scan_and_validate_extreme_aspect_ratio(tmp_path: Path) -> None:
    img_dir = tmp_path / "pages"
    img_dir.mkdir()

    # Extreme ratio: 100 x 500 (ratio 0.2 < 0.35)
    create_dummy_image(img_dir / "tall.jpg", width=100, height=500)

    manifest = scan_and_validate_directory(img_dir)
    assert manifest.pages[0].extreme_aspect_ratio is True
    assert len(manifest.warnings) >= 1


def test_create_source_pdf_success(tmp_path: Path) -> None:
    img_dir = tmp_path / "pages"
    img_dir.mkdir()

    create_dummy_image(img_dir / "p1.jpg", width=100, height=120)
    create_dummy_image(img_dir / "p2.jpg", width=100, height=120)
    create_dummy_image(img_dir / "p3.jpg", width=100, height=120)

    manifest = scan_and_validate_directory(img_dir)
    pdf_path = tmp_path / "source.pdf"

    result_path = create_source_pdf(manifest, img_dir, pdf_path)
    assert result_path.is_file()
    assert result_path.stat().st_size > 0
