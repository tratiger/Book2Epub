"""Data models for visual semantic arbitration and OCR correction (M9 & Appendix K)."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    target_type: SemanticTarget | None = None
    subtype: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[VisualEvidenceCode] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)
    ocr_review_recommended: bool = False

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        if isinstance(obj, dict) and any(
            key in obj for key in ("target", "visual_evidence_codes", "confirms_text_decision")
        ):
            obj = {**obj, "__legacy_provider_field_rejected__": True}
        return super().model_validate(obj, **kwargs)

    def __init__(self, **data: object) -> None:
        """Accept old in-memory fixtures without exposing old fields to providers."""
        if "target_type" not in data and "target" in data:
            data["target_type"] = data.pop("target")
        if "evidence_codes" not in data and "visual_evidence_codes" in data:
            data["evidence_codes"] = data.pop("visual_evidence_codes")
        # This field was redundant with the decision enum and is ignored only for
        # legacy in-memory callers. Dict/provider validation remains extra-forbid.
        data.pop("confirms_text_decision", None)
        super().__init__(**data)

    @property
    def target(self) -> SemanticTarget | None:
        """Compatibility view for the existing visual arbitration application."""
        return self.target_type

    @property
    def visual_evidence_codes(self) -> list[VisualEvidenceCode]:
        """Compatibility view for pre-1.1 in-memory callers."""
        return self.evidence_codes


class VisualSemanticBatch(BaseModel):
    """Batch container for visual semantic decisions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    decisions: list[VisualSemanticDecision]

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_decision_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and any(
            isinstance(item, dict)
            and any(
                key in item
                for key in ("target", "visual_evidence_codes", "confirms_text_decision")
            )
            for item in data.get("decisions", [])
        ):
            raise ValueError("legacy visual response fields are not accepted")
        return data


class OCRCorrectionProposal(BaseModel):
    """
    Proposal for single-segment OCR correction (M9 Section 11, Appendix K8).
    This is the only provider output permitted to carry proposed text.
    """

    model_config = ConfigDict(extra="forbid")

    block_id: str
    segment_id: str
    line_index: int | None = None
    span_index: int | None = None
    old_text_sha256: str
    proposed_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason_code: Literal[
        "GLYPH_CONFUSION",
        "MISSING_CHARACTER",
        "EXTRA_CHARACTER",
        "BROKEN_WORD",
        "BROKEN_JAPANESE_TOKEN",
        "CODE_IDENTIFIER_GLYPH",
        "PUNCTUATION_GLYPH",
        "OTHER_VISUALLY_CLEAR",
    ]
    visually_verified: bool

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        if isinstance(obj, dict) and "visible_error_type" in obj:
            obj = {**obj, "__legacy_provider_field_rejected__": True}
        return super().model_validate(obj, **kwargs)

    def __init__(self, **data: object) -> None:
        """Keep old test/provider fixtures usable without widening provider JSON."""
        if "reason_code" not in data and "visible_error_type" in data:
            legacy_reason = str(data.pop("visible_error_type"))
            data["reason_code"] = {
                "character_substitution": "GLYPH_CONFUSION",
                "character_confusion": "GLYPH_CONFUSION",
                "missing_character": "MISSING_CHARACTER",
                "extra_character": "EXTRA_CHARACTER",
                "spacing_inside_segment": "BROKEN_WORD",
                "punctuation": "PUNCTUATION_GLYPH",
                "case": "GLYPH_CONFUSION",
                "no_clear_error": "OTHER_VISUALLY_CLEAR",
            }.get(legacy_reason, legacy_reason)
        if "visually_verified" not in data:
            data["visually_verified"] = True
        if data.get("proposed_text") is None:
            data["proposed_text"] = ""
        # Rationale was not part of the canonical OCR proposal contract.
        data.pop("rationale", None)
        super().__init__(**data)

    @property
    def visible_error_type(self) -> str:
        """Compatibility view for audit/application code using the old name."""
        return {
            "GLYPH_CONFUSION": "character_substitution",
            "MISSING_CHARACTER": "missing_character",
            "EXTRA_CHARACTER": "extra_character",
            "BROKEN_WORD": "spacing_inside_segment",
            "BROKEN_JAPANESE_TOKEN": "spacing_inside_segment",
            "CODE_IDENTIFIER_GLYPH": "character_substitution",
            "PUNCTUATION_GLYPH": "punctuation",
            "OTHER_VISUALLY_CLEAR": "no_clear_error",
        }[self.reason_code]


class OCRCorrectionBatch(BaseModel):
    """Batch of OCR correction proposals."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    proposals: list[OCRCorrectionProposal]

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_proposal_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and any(
            isinstance(item, dict) and "visible_error_type" in item
            for item in data.get("proposals", [])
        ):
            raise ValueError("legacy OCR response fields are not accepted")
        return data


class OCRSensitiveConfirmation(BaseModel):
    """
    Independent second-pass confirmation for sensitive OCR proposals (Appendix K11).
    """

    model_config = ConfigDict(extra="forbid")

    confirm: bool
    exact_visible_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str | None = Field(default=None, max_length=200)


class OCRIndependentRead(BaseModel):
    """
    Independent visible transcription for OCR confirmation (Appendix K11, M9 hardening).
    The model transcribes the crop independently without being shown the proposed text.
    """

    model_config = ConfigDict(extra="forbid")

    block_id: str
    segment_id: str
    observed_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    clear_enough: bool


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
    confirmation_observed_text: str | None = None
    visible_error_type: str
    content_role: Literal[
        "prose",
        "caption",
        "footnote",
        "code_body",
        "preformatted_body",
        "math",
        "table",
        "unknown",
    ] = "prose"
    mode: Literal["safe", "all"]
    status: Literal[
        "applied",
        "rejected",
        "suggested_below_threshold",
        "budget_exceeded",
        "mapping_ambiguous",
    ]
    rejection_reasons: list[str] = Field(default_factory=list)


class OCRCorrectionAuditFile(BaseModel):
    """
    Authoritative container and contract for semantic/ocr-corrections.json
    (Appendix K15, M12/Appendix N5).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["off", "safe", "all"]
    eligible_segment_count: int = 0
    candidate_count: int = 0
    applied_count: int = 0
    rejected_count: int = 0
    budget_exceeded: bool = False
    total_codepoints: int = 0
    changed_codepoints: int = 0
    audits: list[OCRAuditRecord] = Field(default_factory=list)
