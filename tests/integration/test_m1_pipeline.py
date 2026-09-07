"""Integration tests for M1 pipeline with mocked MinerU subprocess."""

import json
from pathlib import Path

import pytest
from PIL import Image

from book2epub.config import JobConfig
from book2epub.errors import NotImplementedStageError
from book2epub.pipeline import run_pipeline
from tests.fixtures.synthetic_middle import sample_middle_dict


def create_page_image(path: Path, color: str = "white") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (200, 300), color=color)
    img.save(path)


def test_m1_end_to_end_with_mock_mineru(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. Create 10 valid page images
    pages_dir = tmp_path / "pages"
    for i in range(1, 11):
        # Give each a distinct color/content
        create_page_image(pages_dir / f"page{i}.jpg", color=f"#{i*20:02x}{i*20:02x}{i*20:02x}")

    work_dir = tmp_path / "work"
    out_epub = tmp_path / "out.epub"

    cfg = JobConfig()
    cfg.app.work_dir = work_dir

    # Mock MinerU execution: writes a mock output tree into raw dir
    call_count = 0

    def mock_execute_mineru(source_pdf: Path, raw_output_dir: Path, mineru_cfg, log_file=None):
        nonlocal call_count
        call_count += 1
        # Create mock output in raw_output_dir / "source" / "book_middle.json"
        out_subdir = raw_output_dir / "source"
        images_dir = out_subdir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # Write dummy middle.json with 10 pages
        mock_data = sample_middle_dict(page_count=10)
        (out_subdir / "book_middle.json").write_text(
            json.dumps(mock_data, indent=2), encoding="utf-8"
        )
        # Also create debug files to ensure canonicalization ignores them
        (out_subdir / "book_model.json").write_text("{}", encoding="utf-8")
        (out_subdir / "book_content_list.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr("book2epub.pipeline.execute_mineru", mock_execute_mineru)

    # First run: should execute mock MinerU and reach end of M1 (NotImplementedStageError for M2)
    with pytest.raises(NotImplementedStageError) as exc_info:
        run_pipeline(pages_dir, out_epub, cfg)

    assert "Milestone M1 (Ingest and MinerU) succeeded" in str(exc_info.value)
    assert call_count == 1

    # Verify artifacts from first run
    job_dirs = list((work_dir / "jobs").iterdir())
    assert len(job_dirs) == 1
    job_dir = job_dirs[0]

    manifest_file = job_dir / "input" / "manifest.json"
    assert manifest_file.is_file()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["total_pages"] == 10
    # Natural sort order check: page1 ... page10
    assert manifest_data["pages"][0]["filename"] == "page1.jpg"
    assert manifest_data["pages"][1]["filename"] == "page2.jpg"
    assert manifest_data["pages"][9]["filename"] == "page10.jpg"

    source_pdf = job_dir / "input" / "source.pdf"
    assert source_pdf.is_file()

    canonical_middle = job_dir / "mineru" / "canonical" / "book_middle.json"
    assert canonical_middle.is_file()
    canonical_data = json.loads(canonical_middle.read_text(encoding="utf-8"))
    assert len(canonical_data["pdf_info"]) == 10

    stage_file = job_dir / "mineru" / "stage.json"
    assert stage_file.is_file()
    stage_data = json.loads(stage_file.read_text(encoding="utf-8"))
    assert stage_data["state"] == "complete"

    # Second run with same input and same job dir (or same work_dir with existing paths):
    # Pass job paths to verify caching
    from book2epub.paths import JobPaths
    existing_paths = JobPaths(job_id=job_dir.name, root=job_dir)
    from book2epub.pipeline import run_conversion_m1

    run_conversion_m1(pages_dir, cfg, force_mineru=False, existing_paths=existing_paths)
    # Subprocess must have been SKIPPED
    assert call_count == 1

    # Invalidate cache by modifying one page
    create_page_image(pages_dir / "page1.jpg", color="#ff0000")  # new hash
    # Run again: cache miss must cause MinerU to be invoked again
    run_conversion_m1(pages_dir, cfg, force_mineru=False, existing_paths=existing_paths)
    assert call_count == 2
