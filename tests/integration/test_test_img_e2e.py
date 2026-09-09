"""End-to-end integration test validating conversion on test-img directory."""

from pathlib import Path

import pytest

from book2epub.config import (
    AppConfig,
    JobConfig,
    MetadataConfig,
    MinerUConfig,
    PresentationConfig,
    RenderConfig,
    SemanticConfig,
)
from book2epub.package.validator import run_epubcheck
from book2epub.pipeline import run_pipeline


@pytest.mark.integration
@pytest.mark.epubcheck
@pytest.mark.gpu
def test_test_img_e2e_conversion(tmp_path: Path) -> None:
    try:
        import torch

        if not torch.cuda.is_available():
            pytest.skip("PyTorch CUDA is not available")
    except ImportError:
        pytest.skip("PyTorch is not installed in the current environment")

    test_img_dir = Path("test-img")
    if not test_img_dir.is_dir() or not any(test_img_dir.glob("*.jpg")):
        pytest.skip("test-img directory with images is not available")

    output_epub = tmp_path / "test_book.epub"
    work_dir = tmp_path / "work"

    job_cfg = JobConfig(
        app=AppConfig(work_dir=work_dir, strict=True),
        mineru=MinerUConfig(model_source="local"),
        render=RenderConfig(language="ja"),
        metadata=MetadataConfig(
            title="Unix-Linuxプログラミング",
            authors=["Author"],
            language="ja",
        ),
    )

    # Run full pipeline (utilizes global cache if already executed)
    result = run_pipeline(
        input_dir=test_img_dir,
        output_epub=output_epub,
        cfg=job_cfg,
    )

    # 1. Structural assertions
    assert result.epub_path.is_file()
    assert result.source_page_count == 150
    assert result.xhtml_part_count >= 1
    assert result.code_count > 0
    assert result.table_count > 0
    assert result.figure_count > 0
    assert result.fallback_count == 0

    # 2. Strict EPUBCheck validation
    check_report = run_epubcheck(output_epub, fail_on_warnings=True)
    assert check_report.is_valid, f"EPUBCheck failed: {check_report.issues}"
    assert check_report.error_count == 0
    assert check_report.warning_count == 0


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.provider_local
def test_test_img_e2e_high_quality(tmp_path: Path) -> None:
    """Optional high-quality E2E test for test-img with semantic & enhanced presentation."""
    try:
        import torch

        if not torch.cuda.is_available():
            pytest.skip("PyTorch CUDA is not available")
    except ImportError:
        pytest.skip("PyTorch is not installed in the current environment")

    test_img_dir = Path("test-img")
    if not test_img_dir.is_dir() or not any(test_img_dir.glob("*.jpg")):
        pytest.skip("test-img directory with images is not available")

    try:
        import urllib.request

        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1):
            pass
    except Exception:
        pytest.skip("Local Ollama provider is not available at http://localhost:11434")

    output_epub = tmp_path / "test_book_hq.epub"
    work_dir = tmp_path / "work_hq"

    job_cfg = JobConfig(
        app=AppConfig(work_dir=work_dir, strict=True),
        mineru=MinerUConfig(model_source="local"),
        render=RenderConfig(language="ja"),
        semantic=SemanticConfig(enabled=True, provider="ollama"),
        presentation=PresentationConfig(mode="enhanced"),
        metadata=MetadataConfig(
            title="Unix-Linuxプログラミング (Enhanced)",
            authors=["Author"],
            language="ja",
        ),
    )

    result = run_pipeline(
        input_dir=test_img_dir,
        output_epub=output_epub,
        cfg=job_cfg,
    )

    assert result.epub_path.is_file()
    assert result.source_page_count == 150
    check_report = run_epubcheck(output_epub, fail_on_warnings=True)
    assert check_report.is_valid, f"EPUBCheck failed: {check_report.issues}"
    assert check_report.error_count == 0
