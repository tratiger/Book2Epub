"""Integration tests for M4 native EPUB 3.3 packaging and EPUBCheck validation."""

import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from book2epub.cli import app
from book2epub.config import JobConfig
from book2epub.package.validator import run_epubcheck
from book2epub.paths import get_epubcheck_jar_path
from book2epub.pipeline import run_from_middle

runner = CliRunner()


@pytest.fixture
def comprehensive_middle_path() -> Path:
    fixture_path = (
        Path(__file__).parent.parent / "fixtures" / "middle" / "hybrid-3.4.5-comprehensive.json"
    )
    assert fixture_path.is_file(), f"Fixture not found: {fixture_path}"
    return fixture_path


@pytest.mark.epubcheck
def test_m4_end_to_end_from_middle(tmp_path: Path, comprehensive_middle_path: Path) -> None:
    """Verify that comprehensive technical book middle.json generates an EPUB
    that passes EPUBCheck 5.3.0.
    """
    work_dir = tmp_path / "work"
    out_epub = tmp_path / "comprehensive.epub"

    cfg = JobConfig()
    cfg.app.work_dir = work_dir
    cfg.metadata.title = "Comprehensive Technical Handbook"
    cfg.metadata.authors = ["Dr. Test Author", "Prof. Synthetic Expert"]
    cfg.metadata.publisher = "Test Tech Press"

    result = run_from_middle(
        middle_json=comprehensive_middle_path,
        output_epub=out_epub,
        cfg=cfg,
    )

    # 1. Verify PackagingResult
    assert out_epub.is_file()
    assert result.file_size_bytes > 0
    assert result.source_page_count == 2
    assert result.xhtml_part_count >= 1
    assert result.math_count >= 1
    assert result.table_count >= 1
    assert result.code_count >= 1
    assert result.figure_count + result.chart_count >= 1

    # 2. Verify EPUBCheck 5.3.0 report
    report = result.validation_report
    assert report.is_valid is True
    assert report.fatal_count == 0
    assert report.error_count == 0
    assert report.epubcheck_exit_code == 0

    # 3. Verify ZIP internal structure
    with zipfile.ZipFile(out_epub, "r") as zf:
        namelist = zf.namelist()
        # mimetype must be first and uncompressed
        assert namelist[0] == "mimetype"
        m_info = zf.getinfo("mimetype")
        assert m_info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"

        # No backslashes
        for name in namelist:
            assert "\\" not in name

        # container.xml exists
        assert "META-INF/container.xml" in namelist
        assert "OEBPS/package.opf" in namelist
        assert "OEBPS/nav.xhtml" in namelist
        assert "OEBPS/styles/book.css" in namelist

        # Images copied into images/
        assert any(n.startswith("OEBPS/images/") for n in namelist)

        # Nav document contains TOC, page-list, and landmarks
        nav_content = zf.read("OEBPS/nav.xhtml").decode("utf-8")
        assert 'epub:type="toc"' in nav_content
        assert 'epub:type="page-list"' in nav_content
        assert 'epub:type="landmarks"' in nav_content

        # OPF contains mathml property
        opf_content = zf.read("OEBPS/package.opf").decode("utf-8")
        assert 'properties="mathml"' in opf_content


@pytest.mark.epubcheck
def test_m4_cli_from_middle_and_validate(tmp_path: Path, comprehensive_middle_path: Path) -> None:
    """Test CLI commands: from-middle and validate."""
    out_epub = tmp_path / "cli_output.epub"
    work_dir = tmp_path / "cli_work"

    # Test from-middle CLI
    res = runner.invoke(
        app,
        [
            "from-middle",
            str(comprehensive_middle_path),
            "-o",
            str(out_epub),
            "--title",
            "CLI Comprehensive Book",
            "--work-dir",
            str(work_dir),
        ],
    )
    assert res.exit_code == 0, res.stdout
    assert "Conversion completed successfully!" in res.stdout
    assert "EPUBCheck PASS" in res.stdout
    assert out_epub.is_file()

    # Test validate CLI command
    val_res = runner.invoke(
        app,
        ["validate", str(out_epub)],
    )
    assert val_res.exit_code == 0, val_res.stdout
    assert "Overall Status" in val_res.stdout
    assert "PASS" in val_res.stdout


@pytest.mark.epubcheck
def test_epubcheck_fails_on_malformed_epub(tmp_path: Path) -> None:
    """EPUBCheck execution must detect errors and report failure on a malformed archive."""
    jar_path = get_epubcheck_jar_path()
    if not jar_path.is_file():
        pytest.skip("epubcheck.jar not available")

    # Create a corrupted/malformed EPUB
    bad_epub = tmp_path / "bad.epub"
    with zipfile.ZipFile(bad_epub, "w") as zf:
        zf.writestr("mimetype", "bad/mimetype\n")
        zf.writestr("META-INF/container.xml", "<invalid-xml")

    report = run_epubcheck(bad_epub, epubcheck_jar=jar_path)
    assert report.is_valid is False
    assert report.fatal_count > 0 or report.error_count > 0
