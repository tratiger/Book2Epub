"""Deterministic cache identities shared by optional downstream stages."""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _without_job_paths(value: Any) -> Any:
    """Return JSON data with per-run filesystem paths removed."""
    if isinstance(value, dict):
        return {
            key: _without_job_paths(item)
            for key, item in value.items()
            if key not in {"source_path", "image_path"}
        }
    if isinstance(value, list):
        return [_without_job_paths(item) for item in value]
    return value


def stable_hash(value: Any) -> str:
    """Hash JSON-compatible data with a stable UTF-8 representation."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_model(value: Any) -> str:
    """Hash a Pydantic model without depending on its pretty-print formatting."""
    return stable_hash(value.model_dump(mode="json"))


def hash_model_without_job_paths(value: Any) -> str:
    """Hash a model while ignoring paths that are regenerated for each job."""
    return stable_hash(_without_job_paths(value.model_dump(mode="json")))


def hash_bookir_relevant(bookir: Any) -> str:
    """Hash BookIR content and asset identity without per-job asset paths."""
    payload = bookir.model_dump(mode="json")
    for asset in payload.get("assets", {}).values():
        asset.pop("source_path", None)
    return stable_hash(payload)


def rebase_cached_bookir_blocks(current_bookir: Any, cached_bookir: Any) -> Any:
    """Apply cached stage blocks while retaining current-run root/assets."""
    return current_bookir.model_copy(update={"blocks": cached_bookir.blocks})


def compute_semantic_cache_key(
    *,
    evidence: Any,
    raw_ir: Any,
    provider: str,
    model: str,
    system_prompt: str,
    response_schemas: Iterable[dict[str, Any]],
    thresholds: dict[str, Any],
    chunk_settings: dict[str, Any],
    observation_contract: dict[str, Any],
) -> str:
    # BookIR assets contain per-job absolute source paths.  They are not semantic
    # evidence and would make an otherwise identical rerun miss the cache.
    raw_ir_relevant = {
        "source": raw_ir.source.model_dump(mode="json"),
        "blocks": [block.model_dump(mode="json") for block in raw_ir.blocks],
    }
    return stable_hash(
        {
            "stage": "semantic_structure",
            "evidence_hash": hash_model(evidence),
            "raw_ir_hash": stable_hash(raw_ir_relevant),
            "source_middle_hash": getattr(evidence, "source_middle_sha256", ""),
            "provider": provider,
            "model": model,
            "prompt_contract_hash": stable_hash(system_prompt),
            "response_schema_hash": stable_hash(list(response_schemas)),
            "thresholds": thresholds,
            "chunk_settings": chunk_settings,
            "observation_contract": observation_contract,
        }
    )


def compute_visual_cache_key(
    *,
    semantic_decision_hash: str,
    evidence_hash: str,
    visual_hash: str,
    provider: str,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    mode: str,
    thresholds: dict[str, Any],
) -> str:
    return stable_hash(
        {
            "stage": "semantic_visual",
            "semantic_decision_hash": semantic_decision_hash,
            "target_evidence_hash": evidence_hash,
            "source_visual_hash": visual_hash,
            "provider": provider,
            "model": model,
            "prompt_version_hash": stable_hash(prompt),
            "schema_hash": stable_hash(schema),
            "mode": mode,
            "thresholds": thresholds,
        }
    )


def compute_ocr_cache_key(
    *,
    pre_ocr_ir_hash: str,
    candidate_old_hash: str,
    visual_hash: str,
    mode: str,
    provider: str,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    policy_version: str,
    ocr_recommendation_hash: str = "",
) -> str:
    return stable_hash(
        {
            "stage": "ocr_correction",
            "pre_ocr_ir_hash": pre_ocr_ir_hash,
            "candidate_old_hash": candidate_old_hash,
            "ocr_recommendation_hash": ocr_recommendation_hash,
            "source_visual_hash": visual_hash,
            "mode": mode,
            "provider": provider,
            "model": model,
            "prompt_version_hash": stable_hash(prompt),
            "schema_hash": stable_hash(schema),
            "policy_version": policy_version,
        }
    )


def compute_presentation_cache_key(
    *,
    representative_pages: list[int],
    visual_hash: str,
    relevant_ir_hash: str,
    provider: str,
    model: str,
    profile_schema: dict[str, Any],
    prompt: str,
) -> str:
    return stable_hash(
        {
            "stage": "presentation_profile",
            "representative_pages": representative_pages,
            "source_visual_hash": visual_hash,
            "relevant_ir_hash": relevant_ir_hash,
            "provider": provider,
            "model": model,
            "profile_schema_hash": stable_hash(profile_schema),
            "prompt_version_hash": stable_hash(prompt),
        }
    )


def stage_cache_hit(
    stage_file: Path,
    cache_key: str,
    outputs: Iterable[Path],
    *,
    require_cacheable: bool = False,
) -> bool:
    """Return true only for a matching, optionally cacheable stage record."""
    if not stage_file.is_file() or any(not path.is_file() for path in outputs):
        return False
    try:
        data = json.loads(stage_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if data.get("state") not in {"complete", "cache_hit"}:
        return False
    if data.get("cache_key") != cache_key:
        return False
    if require_cacheable and data.get("details", {}).get("cacheable") is not True:
        return False
    return True


def materialize_global_stage_cache(
    work_dir: Path,
    stage_name: str,
    cache_key: str,
    artifacts: dict[str, Path],
) -> bool:
    """Copy a complete run-independent stage cache into the current job."""
    cache_dir = work_dir / "cache" / stage_name / cache_key
    if any(not (cache_dir / name).is_file() for name in artifacts):
        return False
    for name, destination in artifacts.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((cache_dir / name).read_bytes())
    return True


def persist_global_stage_cache(
    work_dir: Path,
    stage_name: str,
    cache_key: str,
    artifacts: dict[str, Path],
) -> None:
    """Persist current-job stage artifacts under a stable global cache key."""
    cache_dir = work_dir / "cache" / stage_name / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, source in artifacts.items():
        if source.is_file():
            (cache_dir / name).write_bytes(source.read_bytes())
