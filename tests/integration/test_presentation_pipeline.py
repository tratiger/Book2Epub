"""Integration tests for presentation modes (legacy, enhanced) across full pipeline (M10)."""

import json
from pathlib import Path

from book2epub.config import AppConfig, JobConfig, PresentationConfig
from book2epub.paths import create_job_paths
from book2epub.pipeline import (
    run_conversion_m2,
    run_conversion_m3,
    run_conversion_m4,
)
from book2epub.render.css import BOOK_CSS_CONTENT


def test_pipeline_presentation_enhanced(tmp_path: Path) -> None:
    """Run full pipeline with presentation='enhanced' and verify profile and CSS generation."""
    work_dir = tmp_path / ".work"
    output_epub = tmp_path / "enhanced_test.epub"

    middle_data = {
        "_version_name": "3.4.5",
        "_backend": "hybrid",
        "_effort": "high",
        "_ocr_enable": True,
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [600, 800],
                "para_blocks": [
                    {
                        "type": "title",
                        "level": 1,
                        "bbox": [50, 50, 300, 80],
                        "lines": [{"spans": [{"type": "text", "content": "Chapter 1: Intro"}]}],
                    },
                    {
                        "type": "title",
                        "level": 2,
                        "bbox": [50, 90, 300, 120],
                        "lines": [{"spans": [{"type": "text", "content": "Section 1.1"}]}],
                    },
                    {
                        "type": "text",
                        "bbox": [50, 130, 500, 160],
                        "lines": [{"spans": [{"type": "text", "content": "Body paragraph text."}]}],
                    },
                ],
                "discarded_blocks": [],
            }
        ],
    }

    raw_middle = tmp_path / "source_middle.json"
    raw_middle.write_text(json.dumps(middle_data, ensure_ascii=False), encoding="utf-8")

    paths = create_job_paths(work_dir)
    cfg = JobConfig(
        app=AppConfig(work_dir=work_dir),
        metadata={"title": "Enhanced Presentation Book"},
        presentation=PresentationConfig(mode="enhanced"),
    )

    _, normalized_ir = run_conversion_m2(raw_middle, paths, cfg)
    render_result = run_conversion_m3(normalized_ir, paths, cfg)

    # 1. Profile JSON artifact was saved
    assert paths.presentation_book_style_profile_json.is_file()
    profile_text = paths.presentation_book_style_profile_json.read_text(encoding="utf-8")
    profile_data = json.loads(profile_text)
    assert profile_data["mode_source"] == "enhanced_default"

    # 2. Enhanced CSS was generated and written to OEBPS/styles/book.css
    css_path = paths.render_oebps_dir / "styles" / "book.css"
    assert css_path.is_file()
    css_content = css_path.read_text(encoding="utf-8")
    assert "border-bottom: 0.06em solid currentColor;" in css_content
    assert "pre.terminal-output" in css_content

    # 3. Render manifest contains presentation metadata
    manifest_path = paths.render_oebps_dir / "render-manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["presentation_mode"] == "enhanced"
    assert manifest_data["style_profile_hash"] is not None
    assert manifest_data["component_counts"]["heading"] == 2
    assert manifest_data["component_counts"]["paragraph"] == 1

    # 4. Packaging succeeds
    packaging_result = run_conversion_m4(render_result, output_epub, paths, cfg)
    assert output_epub.is_file()
    assert packaging_result.file_size_bytes > 0


def test_pipeline_presentation_legacy_preserves_css(tmp_path: Path) -> None:
    """Run pipeline with presentation='legacy' and verify exact legacy CSS is emitted."""
    work_dir = tmp_path / ".work_legacy"
    output_epub = tmp_path / "legacy_test.epub"

    middle_data = {
        "_version_name": "3.4.5",
        "_backend": "hybrid",
        "_effort": "high",
        "_ocr_enable": True,
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [600, 800],
                "para_blocks": [
                    {
                        "type": "title",
                        "level": 1,
                        "bbox": [50, 50, 300, 80],
                        "lines": [{"spans": [{"type": "text", "content": "Legacy Chapter"}]}],
                    },
                ],
                "discarded_blocks": [],
            }
        ],
    }

    raw_middle = tmp_path / "source_middle.json"
    raw_middle.write_text(json.dumps(middle_data, ensure_ascii=False), encoding="utf-8")

    paths = create_job_paths(work_dir)
    cfg = JobConfig(
        app=AppConfig(work_dir=work_dir),
        metadata={"title": "Legacy Presentation Book"},
        presentation=PresentationConfig(mode="legacy"),
    )

    _, normalized_ir = run_conversion_m2(raw_middle, paths, cfg)
    render_result = run_conversion_m3(normalized_ir, paths, cfg)

    css_path = paths.render_oebps_dir / "styles" / "book.css"
    assert css_path.read_text(encoding="utf-8") == BOOK_CSS_CONTENT

    manifest_path = paths.render_oebps_dir / "render-manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["presentation_mode"] == "legacy"

    packaging_result = run_conversion_m4(render_result, output_epub, paths, cfg)
    assert output_epub.is_file()
    assert packaging_result.file_size_bytes > 0
