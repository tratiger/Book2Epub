"""Regression tests for run-independent downstream cache identities."""

from pathlib import Path

from book2epub.cache import (
    compute_ocr_cache_key,
    hash_bookir_relevant,
    materialize_global_stage_cache,
    persist_global_stage_cache,
    rebase_cached_bookir_blocks,
)
from book2epub.ir.models import Asset, BookIR, Paragraph, SourceDocument, Text


def _bookir_with_asset(path: Path) -> BookIR:
    return BookIR(
        source=SourceDocument(page_count=1),
        assets={
            "asset-1": Asset(
                asset_id="asset-1",
                source_path=path,
                media_type="image/png",
                sha256="image-sha",
                byte_size=10,
                width=10,
                height=10,
                role="figure",
            )
        },
    )


def test_bookir_hash_ignores_job_local_asset_path(tmp_path: Path) -> None:
    first = hash_bookir_relevant(_bookir_with_asset(tmp_path / "job-a" / "image.png"))
    second = hash_bookir_relevant(_bookir_with_asset(tmp_path / "job-b" / "image.png"))
    assert first == second


def test_cached_bookir_rebase_retains_current_run_asset_path(tmp_path: Path) -> None:
    current = _bookir_with_asset(tmp_path / "job-b" / "image.png").model_copy(
        update={"blocks": [Paragraph(id="current", inlines=[Text(text="current")])]}
    )
    cached = _bookir_with_asset(tmp_path / "job-a" / "image.png").model_copy(
        update={"blocks": [Paragraph(id="cached", inlines=[Text(text="cached")])]}
    )

    rebased = rebase_cached_bookir_blocks(current, cached)
    assert rebased.blocks[0].id == "cached"
    assert rebased.assets["asset-1"].source_path == tmp_path / "job-b" / "image.png"


def test_global_stage_cache_materializes_into_a_different_job(tmp_path: Path) -> None:
    source = tmp_path / "job-a" / "stage.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"state":"complete"}', encoding="utf-8")
    output = tmp_path / "job-a" / "result.json"
    output.write_text("result", encoding="utf-8")

    persist_global_stage_cache(
        tmp_path,
        "visual",
        "stable-key",
        {"stage.json": source, "result.json": output},
    )

    destination_stage = tmp_path / "job-b" / "stage.json"
    destination_output = tmp_path / "job-b" / "result.json"
    assert materialize_global_stage_cache(
        tmp_path,
        "visual",
        "stable-key",
        {"stage.json": destination_stage, "result.json": destination_output},
    )
    assert destination_stage.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert destination_output.read_text(encoding="utf-8") == "result"


def test_ocr_cache_key_changes_when_visual_recommendation_changes() -> None:
    common = {
        "pre_ocr_ir_hash": "ir",
        "candidate_old_hash": "candidates",
        "visual_hash": "visual",
        "mode": "safe",
        "provider": "mock",
        "model": "mock-1",
        "prompt": "prompt",
        "schema": {},
        "policy_version": "policy-1",
    }
    without_recommendation = compute_ocr_cache_key(
        **common, ocr_recommendation_hash="[]"
    )
    with_recommendation = compute_ocr_cache_key(
        **common, ocr_recommendation_hash='["blk-10"]'
    )
    assert without_recommendation != with_recommendation
