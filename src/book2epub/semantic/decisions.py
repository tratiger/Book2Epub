"""Canonical Pass B semantic schemas and audit records (M8/Appendix H8)."""

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from book2epub.semantic.book_state import BookStateObservationBatch
from book2epub.semantic.models import SemanticTarget

SemanticEvidenceCode = Literal[
    "PRECEDING_PROSE_INTRODUCES_CODE",
    "PRECEDING_PROSE_INTRODUCES_COMMAND",
    "PRECEDING_PROSE_INTRODUCES_OUTPUT",
    "FOLLOWING_PROSE_REFERS_TO_OUTPUT",
    "SHELL_PROMPT_PATTERN",
    "CODE_SYNTAX_PATTERN",
    "MONOSPACED_OR_PREFORMATTED_LAYOUT",
    "TABLE_HAS_REAL_ROW_COLUMN_SEMANTICS",
    "TABLE_LACKS_SEMANTIC_COLUMNS",
    "LOG_PATTERN",
    "CONFIG_PATTERN",
    "REPL_PATTERN",
    "LIST_PATTERN",
    "CALLOUT_CONTEXT",
    "QUOTE_CONTEXT",
    "CAPTION_CONTEXT",
    "BOOK_STATE_PATTERN",
    "OUTLINE_CONTEXT",
    "MINERU_CLASSIFICATION_SUPPORTED",
    "MINERU_CLASSIFICATION_CONTRADICTED",
    "AMBIGUOUS",
]

SemanticOperation = Literal[
    "keep",
    "retype",
    "set_subtype",
    "retype_and_set_subtype",
    "set_list_kind",
]

RelationType = Literal[
    "caption_of",
    "footnote_of",
    "paragraph_continuation",
    "member_of_callout",
    "member_of_example",
]


_LEGACY_EVIDENCE_CODE_MAP: dict[str, str] = {
    "PRECEDING_TEXT_REFERENCE": "PRECEDING_PROSE_INTRODUCES_OUTPUT",
    "FOLLOWING_TEXT_REFERENCE": "FOLLOWING_PROSE_REFERS_TO_OUTPUT",
    "SECTION_TOPIC_CONTEXT": "OUTLINE_CONTEXT",
    "BOOK_PATTERN_CONTEXT": "BOOK_STATE_PATTERN",
    "PROGRAMMING_SYNTAX_PATTERN": "CODE_SYNTAX_PATTERN",
    "LOG_LINE_PATTERN": "LOG_PATTERN",
    "CONFIG_SYNTAX_PATTERN": "CONFIG_PATTERN",
    "TABULAR_HEADER_PATTERN": "TABLE_HAS_REAL_ROW_COLUMN_SEMANTICS",
    "TABULAR_ROW_COLUMN_SEMANTICS": "TABLE_HAS_REAL_ROW_COLUMN_SEMANTICS",
    "LIST_MARKER_PATTERN": "LIST_PATTERN",
    "CALLOUT_LANGUAGE_PATTERN": "CALLOUT_CONTEXT",
    "CAPTION_REFERENCE_PATTERN": "CAPTION_CONTEXT",
    "TYPOGRAPHIC_GEOMETRY_SIGNAL": "MONOSPACED_OR_PREFORMATTED_LAYOUT",
    "MINERU_SIGNAL": "MINERU_CLASSIFICATION_SUPPORTED",
}


def _migrate_legacy_evidence_codes(codes: list[str]) -> list[SemanticEvidenceCode]:
    """Translate only in-memory legacy test/cache objects before canonical validation."""
    return [cast(SemanticEvidenceCode, _LEGACY_EVIDENCE_CODE_MAP.get(code, code)) for code in codes]


class SemanticBlockDecision(BaseModel):
    """Canonical Pass B block decision; no content-generation fields are allowed."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    operation: SemanticOperation
    target_type: SemanticTarget | None = None
    subtype: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[SemanticEvidenceCode] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)
    _legacy_related_block_ids: list[str] = PrivateAttr(default_factory=list)
    _legacy_evidence_codes: list[str] = PrivateAttr(default_factory=list)

    @property
    def target(self) -> SemanticTarget:
        """Compatibility view for the existing deterministic application path."""
        return self.target_type or "keep_original"

    @property
    def related_block_ids(self) -> list[str]:
        """Legacy compatibility view; relations are canonical batch members."""
        return list(self._legacy_related_block_ids)


class SemanticDecision(BaseModel):
    """Legacy in-memory input accepted only for existing non-provider callers."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    target: SemanticTarget
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[str] = Field(default_factory=list)
    related_block_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)


class SemanticRelationDecision(BaseModel):
    """Canonical relation response; application is intentionally a later step."""

    model_config = ConfigDict(extra="forbid")

    relation_type: RelationType
    source_block_ids: list[str]
    target_block_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[SemanticEvidenceCode] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)


class SemanticDecisionBatch(BaseModel):
    """Canonical Pass B batch: decisions, relations, and observations."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    chunk_id: str
    decisions: list[SemanticBlockDecision] = Field(default_factory=list)
    relations: list[SemanticRelationDecision] = Field(default_factory=list)
    observations: list[BookStateObservationBatch] = Field(
        default_factory=list,
        description=(
            "Optional BookStateObservationBatch from this chunk. "
            "Validated and merged into running BookState before the next chunk."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_in_memory_decisions(cls, value: Any) -> Any:
        """Migrate old model instances without widening the provider JSON schema.

        Legacy dict responses are deliberately not migrated: provider responses and
        cache artifacts must validate the canonical 1.1 contract.
        """
        if not isinstance(value, dict):
            return value
        decisions = value.get("decisions")
        if not isinstance(decisions, list) or not any(
            isinstance(item, SemanticDecision) for item in decisions
        ):
            return value

        migrated: list[SemanticBlockDecision] = []
        for item in decisions:
            if isinstance(item, SemanticDecision):
                target = None if item.target in {"keep", "keep_original"} else item.target
                operation: SemanticOperation = "keep" if target is None else "retype"
                migrated_decision = SemanticBlockDecision(
                    block_id=item.block_id,
                    operation=operation,
                    target_type=target,
                    heading_level=item.heading_level,
                    confidence=item.confidence,
                    evidence_codes=_migrate_legacy_evidence_codes(item.evidence_codes),
                    rationale=item.rationale,
                )
                migrated_decision._legacy_related_block_ids = list(item.related_block_ids)
                migrated_decision._legacy_evidence_codes = list(item.evidence_codes)
                migrated.append(migrated_decision)
            else:
                # Do not make old dictionaries provider-compatible.
                migrated.append(item)
        result = dict(value)
        result["schema_version"] = "1.1"
        result["decisions"] = migrated
        return result


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


class SemanticRelationAuditRecord(BaseModel):
    """Audit record for every proposed Pass B relation."""

    model_config = ConfigDict(extra="forbid")

    relation_id: str
    relation_type: RelationType
    source_block_ids: list[str]
    target_block_id: str | None = None
    confidence: float
    evidence_codes: list[str] = Field(default_factory=list)
    provider: str
    model: str
    request_ids: list[str] = Field(default_factory=list)
    status: Literal["proposed", "applied", "rejected", "conflict", "queued_visual"]
    rejection_reason: str | None = None
