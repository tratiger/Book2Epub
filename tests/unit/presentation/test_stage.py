"""Regression tests for presentation inference cache and force invalidation."""

from pathlib import Path

from book2epub.config import JobConfig
from book2epub.ir.models import BookIR, SourceDocument
from book2epub.paths import create_job_paths
from book2epub.presentation.defaults import DEFAULT_ENHANCED_PROFILE
from book2epub.presentation.stage import resolve_style_profile


class _FakeProvider:
    name = "mock-provider"
    model = "mock-model"


class _FakeVisualSource:
    has_visual = True
    source_hash = "stable-visual-hash"


def test_presentation_infer_cache_crosses_job_paths_and_force_reloads(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = JobConfig(
        app={"work_dir": tmp_path / ".work"},
        presentation={"mode": "infer"},
    )
    bookir = BookIR(source=SourceDocument(page_count=1))
    calls = 0

    def fake_infer(**kwargs):
        nonlocal calls
        calls += 1
        return DEFAULT_ENHANCED_PROFILE, []

    monkeypatch.setattr(
        "book2epub.visual.source.VisualSource.resolve",
        lambda cfg, paths: _FakeVisualSource(),
    )
    monkeypatch.setattr(
        "book2epub.providers.factory.create_provider",
        lambda cfg, purpose: _FakeProvider(),
    )
    monkeypatch.setattr("book2epub.presentation.stage.infer_style_profile", fake_infer)

    first_paths = create_job_paths(cfg.app.work_dir, job_id="job-a")
    second_paths = create_job_paths(cfg.app.work_dir, job_id="job-b")
    resolve_style_profile(bookir, cfg, first_paths)
    resolve_style_profile(bookir, cfg, second_paths)
    assert calls == 1
    assert second_paths.presentation_stage_json.is_file()
    assert "cache_hit" in second_paths.presentation_stage_json.read_text(encoding="utf-8")

    forced_cfg = cfg.model_copy(deep=True)
    forced_cfg.app.force_presentation = True
    forced_paths = create_job_paths(cfg.app.work_dir, job_id="job-c")
    resolve_style_profile(bookir, forced_cfg, forced_paths)
    assert calls == 2
