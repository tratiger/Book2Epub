"""Stage execution tracking and state recording across conversion pipeline stages."""

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

STAGE_SCHEMA_VERSION = 1


class StageState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"
    CACHE_HIT = "cache_hit"


class StageRecord(BaseModel):
    """Execution status for a pipeline stage."""

    stage: str
    state: StageState
    timestamp_utc: str = Field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    schema_version: int = STAGE_SCHEMA_VERSION
    input_hash: str | None = None
    cache_key: str | None = None
    provider: str | None = None
    model: str | None = None
    output_artifact: str | None = None
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def record_stage_status(
    stage_file: Path,
    stage_name: str,
    state: StageState | str,
    input_hash: str | None = None,
    details: dict[str, Any] | None = None,
    cache_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    output_artifact: str | None = None,
    reason: str | None = None,
) -> StageRecord:
    """Record or update stage.json status for a pipeline stage."""
    state_enum = StageState(state) if isinstance(state, str) else state
    record = StageRecord(
        stage=stage_name,
        state=state_enum,
        input_hash=input_hash,
        cache_key=cache_key,
        provider=provider,
        model=model,
        output_artifact=output_artifact,
        reason=reason,
        details=details or {},
    )
    stage_file.parent.mkdir(parents=True, exist_ok=True)
    stage_file.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return record


def load_stage_record(stage_file: Path) -> StageRecord | None:
    """Read existing stage.json if present."""
    if not stage_file.is_file():
        return None
    try:
        data = json.loads(stage_file.read_text(encoding="utf-8"))
        return StageRecord.model_validate(data)
    except Exception as e:
        logger.warning("Failed to parse stage record %s: %s", stage_file, e)
        return None
