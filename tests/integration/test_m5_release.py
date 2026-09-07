"""Integration tests for Milestone M5: QA diagnostics, evaluation CLI, and release gate."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from book2epub.cli import app
from book2epub.config import JobConfig
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
def test_m5_end_to_end_qa_report_and_evaluate(
    tmp_path: Path, comprehensive_middle_path: Path
) -> None:
    """Verify that full pipeline produces QA reports and evaluate command runs successfully."""
    work_dir = tmp_path / "work"
    out_epub = tmp_path / "m5_output.epub"

    cfg = JobConfig()
    cfg.app.work_dir = work_dir
    cfg.metadata.title = "Release Gate Book"
    cfg.metadata.authors = ["QA Lead"]

    result = run_from_middle(
        middle_json=comprehensive_middle_path,
        output_epub=out_epub,
        cfg=cfg,
    )

    assert out_epub.is_file()
    assert result.validation_report.is_valid is True

    # Find job directory
    jobs = list((work_dir / "jobs").iterdir())
    assert len(jobs) == 1
    job_dir = jobs[0]

    # Verify qa/report.json and qa/report.html exist
    qa_json = job_dir / "qa" / "report.json"
    qa_html = job_dir / "qa" / "report.html"

    assert qa_json.is_file(), f"Missing {qa_json}"
    assert qa_html.is_file(), f"Missing {qa_html}"

    qa_data = json.loads(qa_json.read_text(encoding="utf-8"))
    assert qa_data["job_id"] == job_dir.name
    assert "metrics" in qa_data
    assert "structural_checks" in qa_data

    metrics = qa_data["metrics"]
    assert metrics["math_semantic_rate"] == 1.0
    assert metrics["table_semantic_rate"] == 1.0
    assert metrics["code_text_rate"] == 1.0
    assert metrics["epubcheck_error_count"] == 0

    # Test 'book2epub evaluate' command
    eval_res = runner.invoke(app, ["evaluate", str(job_dir)])
    assert eval_res.exit_code == 0, eval_res.stdout
    assert "Structural Evaluation Metrics" in eval_res.stdout
    assert "Block Coverage" in eval_res.stdout
    assert "Math Semantic Rate" in eval_res.stdout
    assert "Table Semantic Rate" in eval_res.stdout
    assert "EPUBCheck Errors" in eval_res.stdout
