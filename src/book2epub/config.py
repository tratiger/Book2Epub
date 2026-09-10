"""Configuration models for Book2Epub."""

from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field, field_validator


def normalize_provider_alias(value: str) -> Literal["ollama", "openai", "google", "anthropic"]:
    """Normalize CLI provider aliases to the canonical provider enum."""
    normalized = {"gemini": "google"}.get(value.lower(), value.lower())
    return cast(Literal["ollama", "openai", "google", "anthropic"], normalized)


def normalize_vision_alias(value: str) -> Literal["off", "auto", "on"]:
    """Normalize the historical CLI alias ``always`` to canonical ``on``."""
    normalized = {"always": "on"}.get(value.lower(), value.lower())
    return cast(Literal["off", "auto", "on"], normalized)


class AppConfig(BaseModel):
    """Application-level runtime configuration."""

    work_dir: Path = Field(default=Path(".work"), description="Base working directory")
    strict: bool = Field(
        default=True, description="Fail on warnings originating from generated markup"
    )
    logging_level: str = Field(default="INFO", description="Logging level")
    source_pdf: Path | None = Field(default=None, description="Explicit source PDF path")
    source_images_dir: Path | None = Field(
        default=None, description="Explicit source page images directory"
    )
    force_semantic: bool = Field(
        default=False, description="Force re-running semantic reconstruction"
    )
    force_visual: bool = Field(
        default=False, description="Force re-running visual arbitration and OCR"
    )
    force_presentation: bool = Field(
        default=False, description="Force re-running presentation style inference"
    )

    @field_validator("logging_level")
    @classmethod
    def validate_logging_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL"}
        normalized = v.upper()
        if normalized not in valid:
            raise ValueError(f"Invalid logging_level '{v}'. Must be one of {sorted(valid)}")
        return "WARNING" if normalized == "WARN" else normalized


class MinerUConfig(BaseModel):
    """MinerU execution and contract configuration."""

    version: str = Field(default="3.4.5", description="Frozen MinerU version")
    backend: Literal[
        "hybrid-engine",
        "pipeline",
        "vlm-engine",
        "vlm-http-client",
        "hybrid-http-client",
    ] = Field(default="hybrid-engine", description="MinerU backend")
    effort: Literal["high", "medium"] = Field(default="high", description="MinerU effort level")
    method: Literal["ocr", "auto", "txt"] = Field(default="ocr", description="Extraction method")
    formula: bool = Field(default=True, description="Enable formula parsing")
    table: bool = Field(default=True, description="Enable table parsing")
    image_analysis: bool = Field(default=True, description="Enable image and chart analysis")
    model_source: Literal["local", "huggingface", "modelscope"] = Field(
        default="local", description="Model source"
    )

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if v != "3.4.5":
            raise ValueError(f"MinerU version must be frozen at '3.4.5', got '{v}'")
        return v


class RenderConfig(BaseModel):
    """Reflow rendering and content splitting configuration."""

    language: str = Field(default="auto", description="Primary language BCP 47 or 'auto'")
    math_mode: Literal["mathml"] = Field(default="mathml", description="Formula render mode")
    table_mode: Literal["auto", "html", "image"] = Field(
        default="auto", description="Table render preference"
    )
    preserve_page_list: bool = Field(
        default=True, description="Generate EPUB page-list navigation and anchors"
    )
    max_xhtml_chars: int = Field(
        default=100_000,
        ge=1_000,
        description="Max rendered text characters per XHTML content document",
    )
    max_source_pages_per_xhtml: int = Field(
        default=50, ge=1, description="Max source pages per XHTML content document"
    )


class MetadataConfig(BaseModel):
    """Book publication metadata configuration."""

    title: str | None = Field(default=None, description="Book title override")
    authors: list[str] = Field(default_factory=list, description="Book authors")
    language: str = Field(default="auto", description="Book language override")
    identifier: str | None = Field(
        default=None, description="Book unique identifier (e.g. URN UUID)"
    )
    publisher: str | None = Field(default=None, description="Publisher name")
    cover_image: Path | None = Field(default=None, description="Explicit cover image path")


class SemanticConfig(BaseModel):
    """Configuration for LLM-based semantic document reconstruction (M6-M8)."""

    enabled: bool = Field(default=False, description="Enable semantic reconstruction")
    provider: Literal["ollama", "openai", "google", "anthropic"] = Field(
        default="ollama", description="Semantic provider backend"
    )
    model: str | None = Field(default=None, description="Model identifier override")
    allow_cloud: bool = Field(
        default=False, description="Explicit opt-in required for cloud provider requests"
    )
    vision: Literal["off", "auto", "on"] = Field(
        default="auto", description="Multimodal visual review policy"
    )
    auto_apply_threshold: float = Field(
        default=0.80, ge=0.0, le=1.0, description="Confidence threshold for automatic application"
    )
    review_floor: float = Field(
        default=0.45, ge=0.0, le=1.0, description="Minimum confidence to queue for visual review"
    )
    max_chunk_chars: int = Field(
        default=24_000, ge=1_000, description="Maximum characters per semantic chunk"
    )
    max_chunk_blocks: int = Field(
        default=60, ge=1, description="Maximum blocks per semantic chunk"
    )
    overlap_blocks: int = Field(
        default=8, ge=0, description="Context overlap blocks between chunks"
    )


class OCRCorrectionConfig(BaseModel):
    """Configuration for visual-evidence-gated OCR correction (M9)."""

    mode: Literal["off", "safe", "all"] = Field(
        default="off", description="OCR correction mode (default off)"
    )


class PresentationConfig(BaseModel):
    """Configuration for EPUB styling and presentation (M10)."""

    mode: Literal["legacy", "enhanced", "infer"] = Field(
        default="legacy", description="Presentation mode (default legacy)"
    )


class JobConfig(BaseModel):
    """Composite configuration for a single Book2Epub execution."""

    app: AppConfig = Field(default_factory=AppConfig)
    mineru: MinerUConfig = Field(default_factory=MinerUConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    semantic: SemanticConfig = Field(default_factory=SemanticConfig)
    ocr_correction: OCRCorrectionConfig = Field(default_factory=OCRCorrectionConfig)
    presentation: PresentationConfig = Field(default_factory=PresentationConfig)

