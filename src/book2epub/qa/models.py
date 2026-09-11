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
class QAViolation:
    """A specific quality or safety violation recorded during QA evaluation."""

    category: str
    # category: "semantic", "preservation", "ocr", "presentation", "outline", "render", "package"
    severity: str  # "fatal", "error", "warning", "info"
    code: str
    message: str
    block_id: str | None = None
    page_idx: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


class DispositionStr(str):
    """String subclass that allows backward-compatible disposition comparisons."""

    _ALIASES: dict[str, str] = {
        "unchanged": "preserved_same_type",
        "preserved_same_type": "unchanged",
        "retyped": "preserved_retyped",
        "preserved_retyped": "retyped",
        "intentionally_suppressed_boilerplate": "suppressed_boilerplate",
        "suppressed_boilerplate": "intentionally_suppressed_boilerplate",
        "semantically_superseded": "preserved_semantic_supersession",
        "preserved_semantic_supersession": "semantically_superseded",
    }

    def __eq__(self, other: object) -> bool:
        if super().__eq__(other):
            return True
        if isinstance(other, str):
            return self._ALIASES.get(str(self)) == other
        return False

    def __hash__(self) -> int:
        return super().__hash__()


@dataclass
class PreservationLedgerEntry:
    """Disposition accounting record for a source evidence block (Appendix N2, M12 hardening)."""

    source_block_id: str
    source_kind: str
    source_content_sha256: str
    final_block_ids: list[str] = field(default_factory=list)
    final_kinds: list[str] = field(default_factory=list)
    final_content_sha256s: list[str] = field(default_factory=list)
    disposition: DispositionStr = field(default_factory=lambda: DispositionStr("unchanged"))
    source_asset_ids: list[str] = field(default_factory=list)
    final_asset_ids: list[str] = field(default_factory=list)
    semantic_decision_ids: list[str] = field(default_factory=list)
    ocr_correction_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def __init__(
        self,
        source_block_id: str = "",
        source_kind: str = "unknown",
        source_content_sha256: str = "",
        final_block_ids: list[str] | None = None,
        final_kinds: list[str] | None = None,
        final_content_sha256s: list[str] | None = None,
        disposition: str = "unchanged",
        source_asset_ids: list[str] | None = None,
        final_asset_ids: list[str] | None = None,
        semantic_decision_ids: list[str] | None = None,
        ocr_correction_ids: list[str] | None = None,
        reason: str = "",
        # Backward-compatibility arguments:
        block_id: str | None = None,
        final_kind: str | None = None,
        final_content_sha256: str | None = None,
    ) -> None:
        self.source_block_id = source_block_id or block_id or ""
        self.source_kind = source_kind
        self.source_content_sha256 = source_content_sha256
        if final_block_ids is not None:
            self.final_block_ids = final_block_ids
        elif block_id:
            self.final_block_ids = [block_id]
        else:
            self.final_block_ids = []

        if final_kinds is not None:
            self.final_kinds = final_kinds
        elif final_kind is not None and final_kind != "none":
            self.final_kinds = [final_kind]
        else:
            self.final_kinds = []

        if final_content_sha256s is not None:
            self.final_content_sha256s = final_content_sha256s
        elif final_content_sha256 is not None:
            self.final_content_sha256s = [final_content_sha256]
        else:
            self.final_content_sha256s = []

        self.disposition = DispositionStr(disposition)
        self.source_asset_ids = source_asset_ids or []
        self.final_asset_ids = final_asset_ids or []
        self.semantic_decision_ids = semantic_decision_ids or []
        self.ocr_correction_ids = ocr_correction_ids or []
        self.reason = reason

    @property
    def block_id(self) -> str:
        """Alias for backward compatibility."""
        return self.source_block_id

    @property
    def final_kind(self) -> str:
        """Single-kind alias for backward compatibility."""
        return self.final_kinds[0] if self.final_kinds else "none"

    @property
    def final_content_sha256(self) -> str | None:
        """Single-hash alias for backward compatibility."""
        return self.final_content_sha256s[0] if self.final_content_sha256s else None


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
    outline_cycle_count: int = 0
    outline_monotonic_error_count: int = 0
    outline_unresolved_target_count: int = 0
    relation_proposed_count: int = 0
    relation_applied_count: int = 0
    relation_rejected_count: int = 0
    relation_conflict_count: int = 0
    relation_queued_visual_count: int = 0


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
    violations: list[QAViolation] = field(default_factory=list)
    semantic_metrics: SemanticQAMetrics | None = None
    ocr_metrics: OCRQAMetrics | None = None
    presentation_metrics: PresentationQAMetrics | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
