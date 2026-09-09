"""Data models for visual semantic arbitration and OCR correction (M9 & Appendix K)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from book2epub.semantic.models import SemanticTarget

VisualEvidenceCode = Literal[
    "MONOSPACE_VISUAL_STYLE",
    "CODE_INDENTATION_VISIBLE",
    "SHELL_PROMPT_VISIBLE",
    "TABLE_GRID_OR_COLUMNS_SEMANTIC",
    "TABLE_HEADER_VISIBLE",
    "CALLOUT_BOX_VISIBLE",
    "HEADING_VISUAL_HIERARCHY",
    "CAPTION_PROXIMITY",
    "PAGE_CONTINUATION_VISIBLE",
    "VISUAL_AMBIGUOUS",
]


class VisualSemanticDecision(BaseModel):
    """
    Multimodal visual adjudication decision (M9 Section 8, Appendix K3).
    A visual model may only reclassify structure or reject; no replacement text allowed.
    """

    model_config = ConfigDict(extra="forbid")

    block_id: str
    decision: Literal["confirm_proposed", "reject_keep_original", "replace_with_alternate"] = (
        "confirm_proposed"
    )
    target: SemanticTarget | None = None
    target_type: str | None = None
    subtype: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(ge=0.0, le=1.0)
    visual_evidence_codes: list[VisualEvidenceCode] = Field(default_factory=list)
    evidence_codes: list[str] = Field(default_factory=list)
    confirms_text_decision: bool = True
    rationale: str = Field(max_length=240)
    ocr_review_recommended: bool = False


class VisualSemanticBatch(BaseModel):
    """Batch container for visual semantic decisions."""

    schema_version: Literal["1.0"] = "1.0"
    decisions: list[VisualSemanticDecision]


VisibleErrorType = Literal[
    "character_substitution",
    "missing_character",
    "extra_character",
    "spacing_inside_segment",
    "punctuation",
    "case",
    "no_clear_error",
]


class OCRCorrectionProposal(BaseModel):
    """
    Proposal for single-segment OCR correction (M9 Section 11, Appendix K8).
    This is the only provider output permitted to carry proposed text.
    """

    model_config = ConfigDict(extra="forbid")

    block_id: str
    segment_id: str
    old_text_sha256: str
    proposed_text: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    visible_error_type: VisibleErrorType = "character_substitution"
    rationale: str = Field(max_length=200)


class OCRCorrectionBatch(BaseModel):
    """Batch of OCR correction proposals."""

    schema_version: Literal["1.0"] = "1.0"
    proposals: list[OCRCorrectionProposal]


class OCRSensitiveConfirmation(BaseModel):
    """
    Independent second-pass confirmation for sensitive OCR proposals (Appendix K11).
    """

    model_config = ConfigDict(extra="forbid")

    confirm: bool
    exact_visible_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str | None = Field(default=None, max_length=200)


class OCRAuditRecord(BaseModel):
    """
    Audit record for every proposed/applied OCR correction (Appendix K15).
    Enables complete auditing and full reversibility.
    """

    block_id: str
    segment_id: str
    page_idx: int
    bbox: list[float] | None = None
    old_text: str
    new_text: str
    old_sha256: str
    new_sha256: str
    provider: str
    model: str
    request_ids: list[str] = Field(default_factory=list)
    first_confidence: float
    confirmation_confidence: float | None = None
    confirmation_result: bool | None = None
    visible_error_type: str
    mode: Literal["safe", "all"]
    status: Literal[
        "applied",
        "rejected",
        "suggested_below_threshold",
        "budget_exceeded",
        "mapping_ambiguous",
    ]
    rejection_reasons: list[str] = Field(default_factory=list)
