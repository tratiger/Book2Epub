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
class PreservationLedgerEntry:
    """Disposition accounting record for a source evidence block (Appendix N2)."""

    block_id: str
    source_kind: str
    final_kind: str
    source_content_sha256: str
    final_content_sha256: str | None = None
    disposition: str = "preserved_same_type"
    source_asset_ids: list[str] = field(default_factory=list)
    final_asset_ids: list[str] = field(default_factory=list)
    semantic_decision_ids: list[str] = field(default_factory=list)
    ocr_correction_ids: list[str] = field(default_factory=list)


@dataclass
class SemanticQAMetrics:
    """Evaluation metrics for document semantic reconstruction (M12/Appendix N3)."""

    semantic_review_rate: float = 0.0
    semantic_change_rate: float = 0.0
    semantic_auto_apply_rate: float = 0.0
    semantic_visual_review_rate: float = 0.0
    semantic_conflict_rate: float = 0.0
    semantic_unresolved_rate: float = 0.0
    semantic_invalid_decision_rate: float = 0.0
    type_transitions: dict[str, int] = field(default_factory=dict)
    heading_level_known_rate: float = 1.0
    outline_coverage_rate: float = 1.0
    heading_level_change_count: int = 0
    outline_conflict_count: int = 0


@dataclass
class OCRQAMetrics:
    """Evaluation metrics for multimodal OCR correction (M12/Appendix N5)."""

    ocr_mode: str = "off"
    eligible_segment_count: int = 0
    ocr_candidate_count: int = 0
    ocr_proposal_count: int = 0
    ocr_applied_count: int = 0
    ocr_rejected_count: int = 0
    ocr_sensitive_confirmation_count: int = 0
    ocr_confirmation_disagreement_count: int = 0
    ocr_changed_codepoints: int = 0
    ocr_changed_fraction: float = 0.0
    ocr_budget_exceeded: bool = False


@dataclass
class PresentationQAMetrics:
    """Evaluation metrics for presentation and component rendering (M12/Appendix N6)."""

    presentation_mode: str = "legacy"
    style_profile_hash: str | None = None
    style_inference_confidence: float | None = None
    style_inference_fallback: bool = False
    component_counts: dict[str, int] = field(default_factory=dict)
    component_style_coverage: float = 1.0
    list_duplicate_marker_count: int = 0


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
    preservation_ledger: list[PreservationLedgerEntry] = field(default_factory=list)
    semantic_metrics: SemanticQAMetrics | None = None
    ocr_metrics: OCRQAMetrics | None = None
    presentation_metrics: PresentationQAMetrics | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
