"""Data models for provider-neutral structured inference and usage tracking."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ImageInput(BaseModel):
    """Input image for multimodal provider requests."""

    path: Path
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    label: str | None = None


class StructuredInferenceRequest(BaseModel):
    """Provider-neutral request for structured inference (M7 spec Section 3)."""

    request_id: str
    system_instruction: str
    user_text: str
    response_model_name: str
    response_schema: dict[str, Any]
    images: list[ImageInput] = Field(default_factory=list)
    max_output_tokens: int = 8192
    reasoning_effort: Literal["low", "medium", "high"] = "high"


class ProviderUsage(BaseModel):
    """Token accounting metadata returned by provider APIs."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    raw_provider_request_id: str | None = None


class StructuredInferenceResult(BaseModel):
    """Auditable result of a structured inference call."""

    request_id: str
    provider: str
    model: str
    raw_text: str
    parsed_json: dict[str, Any]
    usage: ProviderUsage
    latency_ms: int


class ProviderUsageRecord(BaseModel):
    """Audit record persisted to semantic/provider-usage.json (Appendix G11)."""

    request_id: str
    provider: str
    model: str
    purpose: str
    schema_name: str
    prompt_contract_version: str = "1.0"
    input_sha256: str
    image_sha256: list[str] = Field(default_factory=list)
    started_at_utc: str
    finished_at_utc: str
    latency_ms: int
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    provider_request_id: str | None = None
    status: str
