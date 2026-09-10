"""Pass B semantic decision schemas, conflict representation,
and audit records (Appendix H7 & H12)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from book2epub.semantic.book_state import BookStateObservationBatch
from book2epub.semantic.models import SemanticTarget

SemanticEvidenceCode = Literal[
    "PRECEDING_TEXT_REFERENCE",
    "FOLLOWING_TEXT_REFERENCE",
    "SECTION_TOPIC_CONTEXT",
    "BOOK_PATTERN_CONTEXT",
    "SHELL_PROMPT_PATTERN",
    "PROGRAMMING_SYNTAX_PATTERN",
    "LOG_LINE_PATTERN",
    "CONFIG_SYNTAX_PATTERN",
    "TABULAR_HEADER_PATTERN",
    "TABULAR_ROW_COLUMN_SEMANTICS",
    "LIST_MARKER_PATTERN",
    "CALLOUT_LANGUAGE_PATTERN",
    "CAPTION_REFERENCE_PATTERN",
    "TYPOGRAPHIC_GEOMETRY_SIGNAL",
    "MINERU_SIGNAL",
    "AMBIGUOUS",
]


class SemanticDecision(BaseModel):
    """Pass B semantic block adjudication decision."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    target: SemanticTarget
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[SemanticEvidenceCode] = Field(default_factory=list)
    related_block_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)


class SemanticDecisionBatch(BaseModel):
    """Batch of Pass B semantic decisions returned by provider."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    chunk_id: str
    decisions: list[SemanticDecision] = Field(default_factory=list)
    # Optional inline BookState observations from Pass B (Appendix J4).
    # Provider returns these alongside decisions so state propagates chunk-to-chunk.
    observations: list[BookStateObservationBatch] = Field(
        default_factory=list,
        description=(
            "Optional BookStateObservationBatch from this chunk. "
            "Validated and merged into running BookState before the next chunk."
        ),
    )


class SemanticConflict(BaseModel):
    """Representation of conflicting overlapping decisions queued for M9 / audit."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    conflicting_targets: list[str]
    conflicting_levels: list[int | None]
    confidences: list[float]
    chunk_ids: list[str]


class SemanticAuditRecord(BaseModel):
    """Audit record saved to semantic/applied.json or decision logs (Appendix H12)."""

    decision_id: str
    block_id: str
    source_kind: str
    proposed_target: str
    final_target: str
    confidence: float
    evidence_codes: list[str] = Field(default_factory=list)
    provider: str
    model: str
    request_ids: list[str] = Field(default_factory=list)
    status: Literal[
        "applied",
        "preserved_original_low_confidence",
        "preserved_original_conflict",
        "rejected_invalid_target",
        "rejected_hash_mismatch",
        "queued_visual_review",
        "visual_override_applied",
    ]
    rejection_reason: str | None = None
    source_content_sha256: str = ""
