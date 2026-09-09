# Appendix H — Semantic Evidence, Draft, Decision, and Patch Schemas

This appendix is normative for M6-M8. It defines the exact information boundary between MinerU/BookIR and the LLM. Semantic output never contains arbitrary replacement book text.

## H1. Version constants

```text
SEMANTIC_EVIDENCE_SCHEMA_VERSION = "1.0"
SEMANTIC_DRAFT_SCHEMA_VERSION = "1.0"
STRUCTURE_DECISION_SCHEMA_VERSION = "1.0"
SEMANTIC_DECISION_SCHEMA_VERSION = "1.0"
SEMANTIC_PATCH_SCHEMA_VERSION = "1.0"
PROMPT_CONTRACT_VERSION = "1.0"
```

Changing any schema meaning requires a version bump and cache invalidation.

## H2. Source text segment

Add source-segment metadata to text-derived IR so M9/M11 can operate without reverse-engineering joined prose.

```python
class SourceTextSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    page_idx: int
    block_id: str
    line_index: int | None = None
    span_index: int | None = None
    text: str
    bbox: BBox | None = None
    boundary_before: Literal[
        "start", "same_line", "new_line", "page_continuation", "unknown"
    ] = "unknown"
    source_span_type: str | None = None
    text_sha256: str
```

`text_sha256 = sha256(UTF-8 exact segment text)`.

## H3. Semantic evidence block

```python
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
    "definition_list",
    "callout_note",
    "callout_tip",
    "callout_warning",
    "callout_caution",
    "callout_important",
    "sidebar",
    "quote",
    "example",
    "exercise",
    "figure",
    "chart",
    "display_math",
    "footnote",
    "index",
    "keep_original",
]

class SemanticEvidenceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    order_index: int
    page_indices: list[int]
    source_bboxes: list[BBox]
    mineru_source_types: list[str]
    raw_bookir_kind: str
    raw_bookir_subtype: str | None = None

    exact_plain_text_sha256: str
    exact_plain_text: str | None
    preformatted_text: str | None
    source_segments: list[SourceTextSegment]

    table_html_available: bool = False
    table_html_sha256: str | None = None
    table_plain_preview: str | None = None

    asset_ids: list[str] = []
    caption_plain_text: str | None = None
    footnote_plain_text: str | None = None

    allowed_targets: list[SemanticTarget]
    preview_truncated: bool = False
    source_extensions_summary: dict[str, str | int | float | bool | None] = {}
```

In actual code, use `Field(default_factory=...)` for mutable fields.

### H3.1 Exact/plain representation rules

`exact_plain_text` is a deterministic extraction from the Raw BookIR/source spans. It is not an LLM rewrite.

`preformatted_text` reconstructs original source lines/spans preserving line breaks and intra-line spacing as far as `middle.json` exposes it. It is mandatory for blocks whose allowed targets include preformatted/code/terminal/log/config.

For a real MinerU table, both `table_html_available=true` and a `preformatted_text` candidate may exist. This is intentional: the semantic model can decide the table classification was wrong without asking the LLM to regenerate the text.

## H4. Semantic draft block

The LLM receives a compact derivative, not the full raw evidence.

```python
class SemanticDraftBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    order_index: int
    pages: list[int]
    mineru_type: str
    current_kind: str
    current_subtype: str | None
    text_preview: str | None
    preformatted_preview: str | None
    table_summary: str | None
    caption_preview: str | None
    allowed_targets: list[SemanticTarget]
    geometry: DraftGeometry
    content_sha256: str
    preview_truncated: bool
```

`DraftGeometry` may expose only normalized/readable values:

```text
bbox_width_ratio
bbox_height_ratio
alignment_hint
is_full_width
line_count
span_count
```

Do not send arbitrary raw MinerU internals if not needed.

## H5. Compact chunk input

```python
class SemanticChunkInput(BaseModel):
    schema_version: Literal["1.0"]
    chunk_id: str
    block_ids: list[str]
    blocks: list[SemanticDraftBlock]
    preceding_outline: list[OutlineContextItem]
    book_state: BookStatePromptView
    overlap_block_ids: list[str]
```

The chunk JSON is persisted exactly before sending, so model behavior can be reproduced later.

## H6. Pass A: structure decisions

```python
StructureEvidenceCode = Literal[
    "NUMBERING_PATTERN",
    "MINERU_TITLE_SIGNAL",
    "PRECEDING_SECTION_CONTEXT",
    "FOLLOWING_SECTION_CONTEXT",
    "CROSS_PAGE_SENTENCE_CONTINUITY",
    "TYPOGRAPHIC_GEOMETRY_SIGNAL",
    "BOOK_HIERARCHY_CONSISTENCY",
    "AMBIGUOUS",
]

class StructureDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    is_heading: bool | None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    paragraph_continuation_of: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[StructureEvidenceCode]
    rationale: str = Field(max_length=240)

class StructureDecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    chunk_id: str
    decisions: list[StructureDecision]
```

Invariant: `heading_level` cannot be non-null when `is_heading is False`.

## H7. Pass B: semantic decisions

```python
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
    model_config = ConfigDict(extra="forbid")

    block_id: str
    target: SemanticTarget
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[SemanticEvidenceCode]
    related_block_ids: list[str] = []
    rationale: str = Field(max_length=240)

class SemanticDecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    chunk_id: str
    decisions: list[SemanticDecision]
```

No `text`, `replacement_text`, `html`, `css`, `latex`, `code`, or arbitrary payload field exists.

## H8. Decision validation before application

Python validates every SemanticDecision:

1. block id exists;
2. target is contained in the M6 `allowed_targets` for that block;
3. content hash for the evidence block still matches;
4. heading level is only used for heading target/current Heading;
5. target conversion can be built using existing evidence;
6. no source asset/text would be silently lost;
7. related block ids exist and relation type is allowed;
8. confidence meets the milestone threshold/reconciliation requirement;
9. math blocks cannot change to arbitrary prose/code/table;
10. figure/chart asset identity is preserved.

A provider confidence score is only one signal. It does not override structural validators.

## H9. Patch operations

Apply validated decisions through an explicit operation list. Do not mutate BookIR ad hoc inside provider code.

```python
PatchOpKind = Literal[
    "retype_block",
    "set_heading_level",
    "merge_cross_page_paragraphs",
    "set_preformatted_subtype",
    "set_list_kind",
    "set_callout_subtype",
    "attach_caption",
    "attach_footnote",
    "set_outline_parent",
]

class SemanticPatchOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str
    kind: PatchOpKind
    block_ids: list[str]
    target: str | None
    confidence: float
    source_decision_request_ids: list[str]
    evidence_codes: list[str]
```

The patch contains no freeform replacement text.

## H10. Preformatted block model

Extend BookIR with a semantic preformatted component:

```python
PreformattedSubtype = Literal[
    "source_code",
    "shell_command",
    "terminal_output",
    "terminal_session",
    "repl_session",
    "log_output",
    "config_file",
    "generic_preformatted",
]

class PreformattedBlock(BlockBase):
    kind: Literal["preformatted"] = "preformatted"
    subtype: PreformattedSubtype
    text: str
    language: str | None = None
    caption: list[Inline] = []
    footnotes: list[Inline] = []
```

`text` MUST be constructed by Book2Epub from `SemanticEvidenceBlock.preformatted_text` or existing CodeBlock text. The LLM does not provide it.

## H11. Container semantic components

Add only components required by M8/M10:

```text
CalloutBlock subtype: note|tip|warning|caution|important|sidebar
QuoteBlock
ExampleBlock
ExerciseBlock
DefinitionListBlock
```

For v1, these may contain a list of existing child block IDs or inlines while preserving source order. Do not introduce arbitrary recursive trees that break current rendering/splitting. Outline remains parallel.

## H12. Decision audit record

For every decision, accepted or rejected:

```json
{
  "decision_id": "...",
  "block_id": "blk-00185",
  "source_kind": "table",
  "proposed_target": "terminal_output",
  "final_target": "terminal_output",
  "confidence": 0.96,
  "evidence_codes": ["PRECEDING_TEXT_REFERENCE", "SHELL_PROMPT_PATTERN"],
  "provider": "openai",
  "model": "gpt-5.6-sol",
  "request_ids": ["sem-0004"],
  "status": "applied",
  "rejection_reason": null,
  "source_content_sha256": "..."
}
```

Statuses:

```text
applied
preserved_original_low_confidence
preserved_original_conflict
rejected_invalid_target
rejected_hash_mismatch
queued_visual_review
visual_override_applied
```

## H13. Cache identity

Semantic cache key includes:

```text
raw BookIR SHA-256
SemanticEvidence schema version
SemanticDraft schema version
prompt contract version
provider
model
reasoning effort
chunking settings
auto-apply/review thresholds
BookState schema version
```

OCR correction and presentation have separate cache keys.
