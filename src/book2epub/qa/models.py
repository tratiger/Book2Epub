"""Data models for QA diagnostics, structural quality checks, and evaluation metrics."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PageQASummary:
    """Diagnostic entry for a single source page."""

    page_idx: int
    printed_label: str
    source_image_rel: str | None = None
    source_blocks_count: int = 0
    source_block_types: list[str] = field(default_factory=list)
    bookir_block_ids: list[str] = field(default_factory=list)
    rendered_target_hrefs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class StructuralCheckResult:
    """Outcome of a single reconciliation check."""

    name: str
    passed: bool
    source_count: int
    target_count: int
    details: str


@dataclass
class EvaluationMetrics:
    """Standard evaluation metrics for structural quality and losslessness."""

    block_coverage: float
    math_semantic_rate: float
    table_semantic_rate: float
    code_text_rate: float
    caption_retention_rate: float
    heading_level_known_rate: float
    unknown_block_count: int
    unknown_block_rate_per_100_pages: float
    epubcheck_error_count: int
    epubcheck_warning_count: int


@dataclass
class QAReportData:
    """Complete diagnostic report combining pipeline metrics, checks, and page QA."""

    job_id: str
    timestamp_utc: str
    environment: dict[str, Any]
    input_manifest: dict[str, Any]
    mineru_config: dict[str, Any]
    bookir_block_counts: dict[str, int]
    fallback_counts: dict[str, int]
    title_level_distribution: dict[str, int]
    page_number_table: list[dict[str, Any]]
    missing_caption_warnings: list[str]
    unknown_block_warnings: list[str]
    cross_page_merges_count: int
    dehyphenations_count: int
    table_sanitizer_fallbacks_count: int
    math_conversion_fallbacks_count: int
    epub_internal_validation: dict[str, Any]
    epubcheck_validation: dict[str, Any]
    structural_checks: list[StructuralCheckResult]
    metrics: EvaluationMetrics
    pages: list[PageQASummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
