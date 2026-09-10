"""Deterministic cache identities shared by optional downstream stages."""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def stable_hash(value: Any) -> str:
    """Hash JSON-compatible data with a stable UTF-8 representation."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hash_model(value: Any) -> str:
    """Hash a Pydantic model without depending on its pretty-print formatting."""
    return stable_hash(value.model_dump(mode="json"))


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
) -> str:
    return stable_hash(
        {
            "stage": "ocr_correction",
            "pre_ocr_ir_hash": pre_ocr_ir_hash,
            "candidate_old_hash": candidate_old_hash,
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


def stage_cache_hit(stage_file: Path, cache_key: str, outputs: Iterable[Path]) -> bool:
    """Return true only for a completed matching record with all outputs present."""
    if not stage_file.is_file() or any(not path.is_file() for path in outputs):
        return False
    try:
        data = json.loads(stage_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("state") in {"complete", "cache_hit"} and data.get("cache_key") == cache_key
