"""Unit tests verifying legacy backward compatibility and M6 semantic evidence gate."""

import json
from pathlib import Path

import pytest

from book2epub.config import JobConfig
from book2epub.paths import create_job_paths
from book2epub.pipeline import run_conversion_m2, run_from_middle
from book2epub.semantic.models import SemanticDraftBook, SemanticEvidenceBook


@pytest.fixture
def comprehensive_middle_path() -> Path:
    fixture_path = (
        Path(__file__).parent.parent / "fixtures" / "middle" / "hybrid-3.4.5-comprehensive.json"
    )
    assert fixture_path.is_file(), f"Fixture not found: {fixture_path}"
    return fixture_path


def test_legacy_defaults_create_no_semantic_files(
    tmp_path: Path, comprehensive_middle_path: Path
) -> None:
    """With default configuration, no semantic evidence files should be generated."""
    work_dir = tmp_path / "work"
    paths = create_job_paths(work_dir, "test-legacy-job")
    cfg = JobConfig()

    assert cfg.semantic.enabled is False
    assert cfg.ocr_correction.mode == "off"
    assert cfg.presentation.mode == "legacy"

    raw_ir, norm_ir = run_conversion_m2(
        canonical_middle_json=comprehensive_middle_path,
        paths=paths,
        cfg=cfg,
    )

    assert len(raw_ir.blocks) > 0
    assert len(norm_ir.blocks) > 0

    # Verify no semantic evidence or draft was written
    assert not paths.semantic_evidence_json.is_file()
    assert not paths.semantic_draft_json.is_file()


def test_semantic_enabled_creates_evidence_and_draft(
    tmp_path: Path, comprehensive_middle_path: Path
) -> None:
    """When semantic is enabled, evidence.json and draft.json are created and valid."""
    work_dir = tmp_path / "work"
    paths = create_job_paths(work_dir, "test-semantic-job")
    cfg = JobConfig()
    cfg.semantic.enabled = True

    from unittest.mock import MagicMock, patch

    with patch(
        "book2epub.semantic.stage.run_semantic_reconstruction",
        side_effect=lambda raw_ir, **kwargs: MagicMock(
            bookir=raw_ir,
            applied_changes_count=0,
            preserved_originals_count=len(raw_ir.blocks),
            conflict_count=0,
        ),
    ):
        raw_ir, norm_ir = run_conversion_m2(
            canonical_middle_json=comprehensive_middle_path,
            paths=paths,
            cfg=cfg,
        )

    # Evidence and draft must exist
    assert paths.semantic_evidence_json.is_file()
    assert paths.semantic_draft_json.is_file()

    # Load and validate with Pydantic
    ev_data = json.loads(paths.semantic_evidence_json.read_text(encoding="utf-8"))
    ev_book = SemanticEvidenceBook.model_validate(ev_data)
    assert len(ev_book.blocks) == len(raw_ir.blocks)
    assert ev_book.schema_version == "1.0"

    draft_data = json.loads(paths.semantic_draft_json.read_text(encoding="utf-8"))
    draft_book = SemanticDraftBook.model_validate(draft_data)
    assert len(draft_book.blocks) == len(raw_ir.blocks)
    assert draft_book.schema_version == "1.0"


def test_legacy_end_to_end_output_unchanged(
    tmp_path: Path, comprehensive_middle_path: Path
) -> None:
    """
    Verify that full pipeline with default config produces valid EPUB
    with no semantic artifacts.
    """
    work_dir = tmp_path / "work"
    out_epub = tmp_path / "legacy_out.epub"

    cfg = JobConfig()
    cfg.app.work_dir = work_dir

    result = run_from_middle(
        middle_json=comprehensive_middle_path,
        output_epub=out_epub,
        cfg=cfg,
    )

    assert out_epub.is_file()
    assert result.validation_report.is_valid is True

    # Job dir must have no semantic files
    job_dirs = list((work_dir / "jobs").iterdir())
    assert len(job_dirs) == 1
    job_dir = job_dirs[0]
    assert not (job_dir / "semantic" / "evidence.json").is_file()
