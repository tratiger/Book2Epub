"""Data models for semantic evidence, draft representation, and document state."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from book2epub.ir.models import BBox, SourceTextSegment

# Version constants (Appendix H1)
SEMANTIC_EVIDENCE_SCHEMA_VERSION = "1.1"
SEMANTIC_DRAFT_SCHEMA_VERSION = "1.0"
STRUCTURE_DECISION_SCHEMA_VERSION = "1.0"
SEMANTIC_DECISION_SCHEMA_VERSION = "1.0"
SEMANTIC_PATCH_SCHEMA_VERSION = "1.0"
PROMPT_CONTRACT_VERSION = "1.0"

SemanticTarget = Literal[
    "paragraph",
    "heading",
    "source_code",
    "shell_command",
    "terminal_output",
    "terminal_session",
    "repl_session",
    "log_output",
    "config_file",
    "generic_preformatted",
    "table",
    "unordered_list",
    "ordered_list",
    "list",
    "definition_list",
    "callout_note",
    "callout_tip",
    "callout_warning",
    "callout_caution",
    "callout_important",
    "sidebar",
    "quote",
    "block_quote",
    "example",
    "exercise",
    "figure",
    "chart",
    "display_math",
    "footnote",
    "index",
    "keep",
    "keep_original",
]

EvidenceFlag = Literal[
    "TABLE_WITHOUT_CLEAR_HEADER",
    "TABLE_CONTAINS_SHELL_PROMPT",
    "TABLE_CONTAINS_CODE_TOKENS",
    "TABLE_LOW_CELL_DENSITY",
    "TEXT_LOOKS_PREFORMATTED",
    "HEADING_LEVEL_UNKNOWN",
    "HEADING_TOO_LONG",
    "HEADING_ENDS_SENTENCE",
    "LIST_MARKER_IN_TEXT",
    "CALLOUT_LIKE_GEOMETRY",
    "CROSS_PAGE_BOUNDARY_NEAR_BLOCK",
    "HAS_VISUAL_ASSET",
    "HAS_STRUCTURED_TABLE",
]


class EvidenceSegment(BaseModel):
    """Detailed evidence unit for an individual source span."""

    segment_index: int
    span_type: str
    text: str | None = None
    image_path: str | None = None
    bbox: list[float] | None = None
    text_sha256: str | None = None


class EvidenceLine(BaseModel):
    """Evidence for a single source line composed of spans."""

    line_index: int
    bbox: list[float] | None = None
    segments: list[EvidenceSegment] = Field(default_factory=list)


class SemanticEvidenceBlock(BaseModel):
    """
    Rich evidence representation preserving alternative views of a block before
    semantic decisions are made (M6 spec Section 3, Appendix H3).
    """

    block_id: str
    order_index: int = 0
    page_idx: int = 0
    page_indices: list[int] = Field(default_factory=list)
    source_index: int | None = None
    source_type: str = "unknown"
    mineru_source_types: list[str] = Field(default_factory=list)
    current_kind: str = "unknown"
    current_subtype: str | None = None
    raw_bookir_kind: str = ""
    raw_bookir_subtype: str | None = None

    bbox: list[float] | None = None
    source_bboxes: list[BBox] = Field(default_factory=list)
    page_size: list[float] = Field(default_factory=lambda: [0.0, 0.0])

    plain_text: str = ""
    exact_plain_text: str | None = None
    exact_plain_text_sha256: str = ""
    preformatted_text: str | None = None

    table_html: str | None = None
    table_html_available: bool = False
    table_html_sha256: str | None = None
    table_plain_preview: str | None = None

    asset_ids: list[str] = Field(default_factory=list)
    caption_text: str | None = None
    caption_plain_text: str | None = None
    footnote_text: str | None = None
    footnote_plain_text: str | None = None

    line_segments: list[EvidenceLine] = Field(default_factory=list)
    source_segments: list[SourceTextSegment] = Field(default_factory=list)
    caption_source_segments: list[SourceTextSegment] = Field(default_factory=list)
    footnote_source_segments: list[SourceTextSegment] = Field(default_factory=list)

    content_sha256: str = ""
    allowed_targets: list[SemanticTarget] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    preview_truncated: bool = False
    source_extensions_summary: dict[str, Any] = Field(default_factory=dict)


class SemanticEvidenceBook(BaseModel):
    """Top-level container for all semantic evidence across a publication."""

    schema_version: str = SEMANTIC_EVIDENCE_SCHEMA_VERSION
    source_middle_sha256: str
    raw_bookir_sha256: str
    blocks: list[SemanticEvidenceBlock] = Field(default_factory=list)


class DraftGeometry(BaseModel):
    """Normalized, human-readable geometry summary for LLM context."""

    bbox_width_ratio: float = 0.0
    bbox_height_ratio: float = 0.0
    alignment_hint: Literal["left", "center", "right"] = "left"
    is_full_width: bool = False
    line_count: int = 0
    span_count: int = 0


class DraftBlock(BaseModel):
    """Compact model-facing draft block (M6 spec Section 7, Appendix H4)."""

    block_id: str
    order_index: int = 0
    page_idx: int = 0
    pages: list[int] = Field(default_factory=list)
    source_type: str = "unknown"
    mineru_type: str = ""
    current_kind: str = "unknown"
    current_subtype: str | None = None

    plain_text: str | None = None
    text_preview: str | None = None
    preformatted_preview: str | None = None
    table_summary: str | None = None
    has_table_html: bool = False

    bbox_normalized: list[float] | None = None
    caption_text: str | None = None
    caption_preview: str | None = None
    footnote_text: str | None = None

    allowed_targets: list[SemanticTarget] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    geometry: DraftGeometry = Field(default_factory=DraftGeometry)
    content_sha256: str = ""
    preview_truncated: bool = False


class SemanticDraftBook(BaseModel):
    """Compact model-facing representation of the entire book or chunk."""

    schema_version: str = SEMANTIC_DRAFT_SCHEMA_VERSION
    book_id: str
    blocks: list[DraftBlock] = Field(default_factory=list)


# Forward-compatible document-level models (M8, M10)
class OutlineNode(BaseModel):
    """Logical document hierarchy node referring to heading block IDs."""

    node_id: str
    heading_block_id: str
    title: str
    level: int
    children: list["OutlineNode"] = Field(default_factory=list)


class BookOutline(BaseModel):
    """Parallel document outline tree."""

    nodes: list[OutlineNode] = Field(default_factory=list)


class BookState(BaseModel):
    """Document-level observed patterns and recurring conventions."""

    heading_patterns: list[str] = Field(default_factory=list)
    code_languages: list[str] = Field(default_factory=list)
    observed_terms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticMetadata(BaseModel):
    """Audit summary of semantic passes performed on BookIR."""

    provider: str | None = None
    model: str | None = None
    decisions_applied_count: int = 0
    ocr_corrections_applied_count: int = 0


class BookStyleProfileRef(BaseModel):
    """Reference to resolved presentation style profile."""

    profile_name: str = "enhanced"
    mode: str = "enhanced"
