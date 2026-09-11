# Appendix H — Semantic Evidence, Draft, Block Decision, Relation, Materialization, and Audit Schemas


## H0. Authority and non-negotiable invariants

This appendix defines the exact information boundary between source evidence, model-facing draft data, provider output, deterministic reconciliation, deterministic materialization, and audit artifacts.

The following rules are absolute:

1. **Provider output does not contain replacement book content.** No semantic provider response may contain arbitrary replacement prose, code, table HTML, LaTeX, captions, footnotes, CSS, XHTML, or equivalent content payloads.
2. **The LLM classifies structure; Python materializes it.** Every applied semantic change must be constructible from already-authoritative source evidence held by Book2Epub.
3. **`allowed_targets` is a capability declaration, not a suggestion list.** A target may be advertised only when a deterministic materializer exists for the specific source block/evidence combination.
4. **Silent no-op is forbidden.** If a model requests a target that cannot be materialized, the decision must be explicitly rejected and audited. The implementation must never silently append the unchanged source block while reporting success.
5. **Relations are first-class.** Caption attachment, footnote attachment, paragraph continuation, callout membership, and example membership are represented by `SemanticRelationDecision`, reconciled independently, validated independently, applied deterministically, cached, and audited.
6. **Source-visible content is immutable in M8.** Structural changes may move or regroup exact source-derived content but may not rewrite it. Optional OCR correction belongs to M9 and is governed by Appendix K.
7. **All block IDs remain globally unique recursively.** New semantic wrappers receive new deterministic IDs. A wrapper and its child must never share the same ID.
8. **Overlap conflicts never auto-win by confidence alone.** Conflicts are preserved as unresolved and may be escalated to M9 visual arbitration.
9. **Cache identity includes schema meaning.** Any breaking schema or prompt-contract change invalidates affected semantic caches.
10. **The cache-hit path and live-provider path must produce equivalent semantic application.** Relations, BookState, audit records, and materialization rules must not differ between the two paths.

If another document conflicts with this revised Appendix H on the schema or semantics defined here, this appendix takes precedence until that document is updated to exact parity.

---

## H1. Version constants

Use the following versions for the corrected contract:

```python
SEMANTIC_EVIDENCE_SCHEMA_VERSION = "1.2"
SEMANTIC_DRAFT_SCHEMA_VERSION = "1.0"
STRUCTURE_DECISION_SCHEMA_VERSION = "1.0"
SEMANTIC_DECISION_SCHEMA_VERSION = "1.1"
SEMANTIC_RELATION_SCHEMA_VERSION = "1.0"
SEMANTIC_PATCH_SCHEMA_VERSION = "1.1"
BOOK_STATE_OBSERVATION_SCHEMA_VERSION = "1.0"
PROMPT_CONTRACT_VERSION = "1.1"
```

Rationale:

- Evidence is already implemented as `1.2` at the reviewed baseline.
- Pass A does not require a breaking shape change.
- Pass B **does** require a breaking change from the stale `SemanticDecision` schema to `SemanticBlockDecision + SemanticRelationDecision + observations`, so its version becomes `1.1`.
- The prompt contract changes because Pass B now explicitly asks for relations and the final M8 evidence-code vocabulary.
- Patch semantics change because relation operations become first-class.

Any change to field meaning, operation semantics, relation semantics, or materialization behavior that makes an old cached provider response unsafe to replay requires a version bump and cache invalidation.

Old Pass-B JSON with `schema_version="1.0"` must not be loaded as if it were `1.1`.

---

## H2. Authoritative source text segment

Source-derived prose/caption/footnote text is represented using exact source segments so later semantic, OCR, typography, and QA stages do not need to reverse-engineer already-joined text.

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
        "start",
        "same_line",
        "new_line",
        "page_continuation",
        "unknown",
    ] = "unknown"
    source_span_type: str | None = None
    text_sha256: str
```

`text_sha256` is:

```text
sha256(UTF-8 exact segment text)
```

A structural semantic operation never invents or edits `SourceTextSegment.text`.

`PageBoundary` and other synthetic structural markers are not source text and therefore do not participate in source-text immutability hashes.

---

## H3. Semantic target vocabulary

`SemanticTarget` describes the desired semantic interpretation. It is intentionally richer than raw BookIR `kind` because several targets map to one BookIR class with different subtypes.

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
```

### H3.1 Canonical target-to-BookIR mapping

The following mapping is normative:

| Semantic target | BookIR materialization |
|---|---|
| `paragraph` | `Paragraph` |
| `heading` | `Heading` |
| `source_code` | `CodeBlock(subtype="code")` or `PreformattedBlock(subtype="source_code")` according to source-compatible registry rule |
| `shell_command` | `PreformattedBlock(subtype="shell_command")` |
| `terminal_output` | `PreformattedBlock(subtype="terminal_output")` |
| `terminal_session` | `PreformattedBlock(subtype="terminal_session")` |
| `repl_session` | `PreformattedBlock(subtype="repl_session")` |
| `log_output` | `PreformattedBlock(subtype="log_output")` |
| `config_file` | `PreformattedBlock(subtype="config_file")` |
| `generic_preformatted` | `PreformattedBlock(subtype="generic_preformatted")` |
| `table` | existing source-derived `Table` only |
| `unordered_list` | `ListBlock(ordered=False)` |
| `ordered_list` | `ListBlock(ordered=True)` |
| `list` | `ListBlock(ordered=None)` only when deterministic list item boundaries exist |
| `definition_list` | `DefinitionList` only when deterministic term/definition boundaries exist |
| `callout_*` | `Callout` with corresponding subtype |
| `sidebar` | `Callout(subtype="sidebar")` |
| `quote` / `block_quote` | `BlockQuote` |
| `example` | `ExampleBlock` |
| `exercise` | `ExerciseBlock` |
| `figure` | existing `Figure` asset identity preserved |
| `chart` | existing `Chart` asset identity preserved |
| `display_math` | existing `DisplayMath` source preserved |
| `footnote` | existing/source-derived `Footnote` only |
| `index` | existing/source-derived `IndexBlock` only |
| `keep` / `keep_original` | unchanged source block |

A target appearing in this vocabulary does **not** imply that it is legal for every block. Legality is determined by the materializer capability registry described in H9.

---

## H4. Semantic evidence block

The evidence layer is the canonical deterministic representation used to decide what transformations Book2Epub can safely perform.

```python
class EvidenceSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_index: int
    span_type: str
    text: str | None = None
    image_path: str | None = None
    bbox: list[float] | None = None
    text_sha256: str | None = None


class EvidenceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_index: int
    bbox: list[float] | None = None
    segments: list[EvidenceSegment] = Field(default_factory=list)


class SemanticEvidenceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    order_index: int

    page_idx: int
    page_indices: list[int] = Field(default_factory=list)
    source_index: int | None = None
    source_type: str = "unknown"
    mineru_source_types: list[str] = Field(default_factory=list)

    current_kind: str
    current_subtype: str | None = None
    raw_bookir_kind: str
    raw_bookir_subtype: str | None = None

    bbox: list[float] | None = None
    source_bboxes: list[BBox] = Field(default_factory=list)
    page_size: list[float] = Field(default_factory=lambda: [0.0, 0.0])

    plain_text: str = ""
    exact_plain_text: str | None = None
    exact_plain_text_sha256: str
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

    content_sha256: str
    allowed_targets: list[SemanticTarget] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    preview_truncated: bool = False
    source_extensions_summary: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict
    )
```

### H4.1 Exact/plain representation rules

`exact_plain_text` is a deterministic extraction from Raw BookIR/source spans. It is not an LLM rewrite.

`preformatted_text` preserves source line breaks and intra-line spacing as far as authoritative source evidence permits. It is required before a target that needs whitespace-sensitive materialization may be advertised.

For a MinerU table, both `table_html` and `preformatted_text` may exist. This is intentional:

- valid semantic table -> retain the original sanitized table HTML;
- misclassified terminal/log/config/code layout -> use exact `preformatted_text`.

Never flatten table HTML and then reconstruct invented columns as a substitute for missing preformatted evidence.

### H4.2 `allowed_targets` rule

`allowed_targets` must be generated from the same deterministic materializer capability layer used during application.

Conceptually:

```python
allowed_targets = [
    target
    for target in ALL_SEMANTIC_TARGETS
    if MATERIALIZER_REGISTRY.supports(
        source_block=raw_block,
        evidence=evidence_block,
        target=target,
    )
]
```

A broad handwritten whitelist in `evidence.py` that is independent of application code is forbidden.

If a future target has no content-preserving materializer, it must not appear in `allowed_targets`.

---

## H5. Semantic draft block

The model receives a compact derivative of evidence. Draft preview text is **model evidence only** and is never copied back into BookIR.

```python
class DraftGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bbox_width_ratio: float = 0.0
    bbox_height_ratio: float = 0.0
    alignment_hint: Literal["left", "center", "right"] = "left"
    is_full_width: bool = False
    line_count: int = 0
    span_count: int = 0


class SemanticDraftBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    order_index: int
    page_idx: int
    pages: list[int]

    source_type: str
    mineru_type: str
    current_kind: str
    current_subtype: str | None

    plain_text: str | None
    text_preview: str | None
    preformatted_preview: str | None
    table_summary: str | None
    has_table_html: bool

    caption_preview: str | None
    footnote_preview: str | None

    allowed_targets: list[SemanticTarget]
    flags: list[str]
    geometry: DraftGeometry
    content_sha256: str
    preview_truncated: bool
```

Preview truncation may reduce model evidence, but the final materialized output always comes from full deterministic evidence.

---

## H6. Compact chunk input

```python
class SemanticChunkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    chunk_id: str
    block_ids: list[str]
    blocks: list[SemanticDraftBlock]
    preceding_outline: list[OutlineContextItem]
    book_state: BookStatePromptView
    overlap_block_ids: list[str]
```

The exact chunk input sent to the provider is persisted before inference:

```text
semantic/chunks/<chunk-id>.input.json
```

A provider may return decisions only for block IDs that are valid targets for that chunk. Context-only blocks may be referenced only where the scope contract explicitly permits it.

---

## H7. Pass A — structure decisions

Pass A owns heading identity/level and cross-page paragraph continuation discovered during structural reasoning.

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
    is_heading: bool | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    paragraph_continuation_of: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[StructureEvidenceCode] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)


class StructureDecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    chunk_id: str
    decisions: list[StructureDecision] = Field(default_factory=list)
```

### H7.1 Pass A invariants

- `heading_level` must be null unless `is_heading is True`.
- Heading promotion/demotion reuses exact existing inlines.
- Paragraph continuation is not a free-form merge request. It must pass the canonical continuation validator in H11.5.
- Provider rationale is audit-only and never becomes book content.
- Confidence does not override type, adjacency, hash, provenance, or page-boundary validators.

### H7.2 Pass A confidence policy

```text
c >= 0.80             overlap-agreed decision may auto-apply
single vote c >= 0.85 single-vote decision may auto-apply
0.45 <= c < threshold preserve original and queue visual/unresolved
c < 0.45              preserve original as low confidence
conflict               preserve original and queue visual/unresolved
```

---

## H8. Pass B — canonical semantic decision schema v1.1

This section replaces the stale single-list `SemanticDecision(target=...)` contract.

### H8.1 Semantic evidence codes

Use the final M8 vocabulary for new provider responses:

```python
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
```

Do not expose both old and new evidence-code enums to providers. If legacy artifacts are intentionally migrated, translate old names only inside a dedicated compatibility loader before normal validation.

### H8.2 Block decision

```python
SemanticOperation = Literal[
    "keep",
    "retype",
    "set_subtype",
    "retype_and_set_subtype",
    "set_list_kind",
]


class SemanticBlockDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    operation: SemanticOperation
    target_type: SemanticTarget | None = None
    subtype: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[SemanticEvidenceCode] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)
```

`related_block_ids` is intentionally **not** part of `SemanticBlockDecision`. Cross-block semantics belong in `SemanticRelationDecision`.

### H8.3 Relation decision

```python
RelationType = Literal[
    "caption_of",
    "footnote_of",
    "paragraph_continuation",
    "member_of_callout",
    "member_of_example",
]


class SemanticRelationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_type: RelationType
    source_block_ids: list[str]
    target_block_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: list[SemanticEvidenceCode] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=240)
```

### H8.4 Incremental BookState observation

The reviewed implementation already supports incremental BookState propagation. Preserve that feature and document it explicitly.

```python
class BookStateObservationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    chunk_id: str
    heading_patterns: list[HeadingPatternObservation] = Field(default_factory=list)
    preformatted_conventions: list[PreformattedConventionObservation] = Field(default_factory=list)
    callout_conventions: list[CalloutConventionObservation] = Field(default_factory=list)
    numbering_conventions: list[NumberingConventionObservation] = Field(default_factory=list)
    domain_terms: list[DomainTermObservation] = Field(default_factory=list)
```

Every observed term must appear verbatim in referenced deterministic evidence. Free-form document summaries are forbidden.

### H8.5 Pass B batch

```python
class SemanticDecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    chunk_id: str
    decisions: list[SemanticBlockDecision] = Field(default_factory=list)
    relations: list[SemanticRelationDecision] = Field(default_factory=list)
    observations: list[BookStateObservationBatch] = Field(default_factory=list)
```

### H8.6 Forbidden provider-output fields

The Pass-B output schema must contain no arbitrary content-bearing field, including:

```text
text
replacement_text
replacement
content
html
xhtml
css
latex
code
caption
footnote
list_items
summary
rewritten_text
corrected_text
```

`rationale` is bounded audit metadata. It is never a source of publication content.

### H8.7 Block decision invariants

Validate after provider schema validation and again before materialization:

- `operation="keep"` -> `target_type`, `subtype`, and `heading_level` must not request a structural mutation.
- `operation="retype"` -> `target_type` is required and must be present in the block’s computed `allowed_targets`.
- `operation="set_subtype"` -> source block must already support a subtype and requested subtype must be valid for its class.
- `operation="retype_and_set_subtype"` -> both transition and subtype must be supported by the same deterministic materializer.
- `operation="set_list_kind"` -> source/target must have deterministic item boundaries; no model-generated list text is allowed.
- `heading_level` is normally null in Pass B. Heading identity and level belong to Pass A. If implementation intentionally allows a Pass-B heading-level correction, it must reuse Pass-A validators and exact inlines.
- `confidence` is necessary but never sufficient for application.

---

## H9. Scope validation and overlap reconciliation

Provider schema validity does not imply document-scope validity.

### H9.1 Block decision scope

For each block decision:

- `block_id` must be a decision-eligible target in the current chunk;
- duplicate decisions for the same target within one batch are invalid;
- `target_type` must be allowed for the current block/evidence;
- the provider may not create, delete, reorder, or rename arbitrary blocks through a block decision;
- no provider-generated source hash is trusted; Python compares against the current evidence object.

### H9.2 Relation scope

For each relation:

- all referenced block IDs must exist;
- IDs outside the chunk are allowed only if they were explicitly supplied as valid relation context;
- source IDs must not contain duplicates;
- source ordering is the authoritative book order, not lexical block-ID order;
- relation-specific scope rules in H11 apply before reconciliation/application.

### H9.3 Block overlap reconciliation

For the same block across overlapping chunks:

1. identical semantic result -> merge; confidence = arithmetic mean; union evidence/request IDs;
2. only one chunk votes -> mark `single_vote=true`; require `confidence >= 0.85` for automatic application;
3. conflicting operation/target/subtype/level -> preserve original and emit conflict; do not choose the numerically highest confidence;
4. all raw decisions remain auditable.

### H9.4 Relation overlap reconciliation

Canonical relation identity:

```python
RelationKey = tuple[
    relation_type,
    tuple(source_block_ids),
    target_block_id,
]
```

Rules:

- identical relation repeated in overlap -> merge, mean confidence, union evidence/request IDs;
- one vote only -> `single_vote=true`, automatic application threshold at least `0.85`;
- incompatible relations over the same logical source group -> unresolved conflict;
- conflicting caption/footnote ownership must never be resolved by highest confidence alone;
- all rejected/conflicting relation outcomes are audited.

### H9.5 BookState observations

An observation is accepted only when its evidence references are in scope and every claimed term/convention can be verified against deterministic evidence.

Invalid observations are dropped and audited; they do not fail otherwise-valid block/relation decisions unless the provider batch itself cannot be safely interpreted.

---

## H10. Deterministic materializer capability registry

The old design allowed `evidence.py` and `apply.py` to drift apart. This revision requires one source of truth.

Conceptual API:

```python
@dataclass(frozen=True)
class SemanticMaterializer:
    target: SemanticTarget
    supports: Callable[[Block, SemanticEvidenceBlock], bool]
    apply: Callable[
        [Block, SemanticEvidenceBlock, SemanticBlockDecision],
        Block | list[Block],
    ]


class MaterializerRegistry:
    def supported_targets(
        self,
        source_block: Block,
        evidence: SemanticEvidenceBlock,
    ) -> list[SemanticTarget]: ...

    def materialize(
        self,
        source_block: Block,
        evidence: SemanticEvidenceBlock,
        decision: SemanticBlockDecision,
    ) -> Block | list[Block]: ...
```

`SemanticEvidenceBlock.allowed_targets` is derived from `supported_targets()`.

### H10.1 Required transition semantics

#### Table -> preformatted subtype

Allowed only when `evidence.preformatted_text` is non-empty.

```python
PreformattedBlock(
    id=source.id,
    sources=source.sources,
    text=evidence.preformatted_text,
    subtype=<validated subtype>,
    caption=source.caption,
    footnotes=source.footnotes,
)
```

Do not reconstruct text from table HTML.

#### CodeBlock -> preformatted subtype

Use `CodeBlock.text` exactly. Preserve caption, footnotes, sources, and language when compatible.

#### PreformattedBlock -> subtype change

Reuse exact `text`, caption, footnotes, sources, and language. Only subtype changes.

#### Paragraph/Heading -> preformatted subtype

Allowed only when exact deterministic `preformatted_text` exists and source-content preservation can be proven. The model preview is never used as body text.

#### Paragraph -> Callout

Single-block conversion may create a new `Callout` wrapper containing the original paragraph child. The wrapper gets a new deterministic unique ID; the child keeps its original ID.

#### Paragraph -> BlockQuote

Same wrapper rule as Callout.

#### Paragraph/List source -> ListBlock

Allowed only when deterministic source-derived item boundaries exist. The provider may choose semantics, not generate item text.

#### Text -> Table

Allowed only when valid existing `table_html` evidence exists. The model cannot invent rows/cells/HTML.

#### Aside -> Callout / Paragraph

Allowed only if exact existing inlines are preserved.

#### DefinitionList

Advertise only if deterministic term/definition boundaries are available. If they are not implemented, remove `definition_list` from that block’s `allowed_targets`.

#### Figure / Chart / DisplayMath / Footnote / Index

Do not advertise arbitrary retyping unless a dedicated deterministic materializer proves asset/math/content preservation. Conservative `keep` is preferred.

### H10.2 No silent fallback

If a decision reaches materialization but no registry entry supports it:

```text
status = rejected_unimplemented_target
```

If the existing audit enum is not extended, use:

```text
status = rejected_invalid_target
reason = "No deterministic materializer supports <source> -> <target> for current evidence"
```

The original block is preserved, but the rejection is explicit.

---

## H11. Relation validation and application

Relations are applied **after** Pass-B block materialization and before final recursive unique-ID validation.

Recommended order:

```text
Pass A structure application
-> Pass B block materialization
-> relation application
-> outline refresh if grouping/continuation changes structure
-> recursive unique-ID validation
-> semantic BookIR serialization
```

### H11.1 `caption_of`

Validation:

- source block(s) exist;
- exactly one target exists;
- target is `Figure | Chart | Table | CodeBlock | PreformattedBlock`;
- source-to-target page distance is `<= 1` in v1;
- source content is caption-compatible prose/inlines;
- target caption is empty, or already contains exactly the same provenance/content;
- a caption source cannot belong to multiple targets;
- source attachment must preserve exact source-derived content/provenance.

Application:

1. derive exact source inlines from existing BookIR/evidence;
2. attach them to `target.caption`;
3. verify preservation fingerprint;
4. only after successful attachment remove the standalone source block from the top-level sequence;
5. write relation audit + preservation ledger entry.

Never use model rationale as caption text.

### H11.2 `footnote_of`

Same pattern as caption attachment, using `target.footnotes`.

Allowed targets are `Figure | Chart | Table | CodeBlock | PreformattedBlock` where the BookIR model supports footnotes.

A standalone source block is removed only after exact transfer succeeds.

### H11.3 `member_of_callout`

Validation:

- member IDs are source-ordered and contiguous;
- grouping does not cross a `Heading` boundary;
- members are not already consumed by another incompatible container relation;
- subtype is determined by an associated validated semantic block decision or an existing target Callout;
- all child content/provenance remains exact.

Application:

- children retain original IDs;
- wrapper receives a new deterministic unique ID;
- source order is preserved;
- no child is duplicated both top-level and inside the wrapper after successful application.

Example deterministic wrapper ID:

```text
<first-id>--<last-id>--callout
```

or a stable hash derived from ordered child IDs + relation type.

### H11.4 `member_of_example`

Same contiguity/order/ownership rules as callout grouping.

Create an `ExampleBlock` wrapper with a new deterministic ID. Children retain original IDs.

### H11.5 `paragraph_continuation`

There must be exactly one canonical continuation validator shared by Pass A and relation application.

Required conditions:

- source and target are Paragraph-compatible;
- source-order adjacency is proven from the authoritative block sequence;
- continuation crosses a real source page boundary;
- no intervening meaningful block exists;
- heading/table/figure/code/container boundary does not interrupt the sentence flow;
- concatenation preserves all source segments and sources;
- a synthetic `PageBoundary` may be inserted for provenance but does not alter user-visible source text.

Application must not implement a second weaker merge algorithm in `relations.py`.

### H11.6 Relation conflict behavior

If a relation is ambiguous, conflicts with another relation, or fails a hard validator:

- preserve the source structure;
- record the outcome;
- optionally queue for M9 visual review when visual evidence can resolve it;
- never partially consume/remove source blocks.

---

## H12. Recursive BookIR ID uniqueness

`BlockBase.id` is publication-unique recursively, not merely unique among top-level blocks.

Forbidden pattern:

```python
Callout(
    id=blk.id,
    blocks=[blk],  # child has same id -> invalid
)
```

Required pattern:

```text
child id:   blk-00123
wrapper id: blk-00123--callout
```

After block materialization and relation application, run a recursive uniqueness assertion across:

- top-level `BookIR.blocks`;
- `Callout.blocks`;
- `BlockQuote.blocks`;
- `ExampleBlock.blocks`;
- `ExerciseBlock.blocks`;
- any future nested structural container.

Duplicate IDs are a semantic-stage error, not a warning.

---

## H13. Content preservation fingerprint

A simple top-level visible-string hash is insufficient when content is moved into captions, footnotes, callouts, examples, or paragraph continuations.

M8 must validate structural preservation using deterministic leaf-level provenance.

A preservation fingerprint should include, as applicable:

```text
ordered SourceTextSegment IDs + text_sha256 values
CodeBlock / PreformattedBlock exact body SHA-256
Table original HTML SHA-256 when table remains table
DisplayMath exact LaTeX/source hash
asset IDs for Figure/Chart/fallback assets
caption/footnote source-segment hashes
```

Synthetic structural markers such as `PageBoundary` are excluded from source-content equality.

For a pure structural operation:

```text
multiset/ordered-ledger of authoritative source leaves before
==
multiset/ordered-ledger of authoritative source leaves after
```

Location in the tree may change; source-derived content may not disappear, duplicate, or mutate.

Any unapproved preservation mismatch is fatal for M8.

---

## H14. Deterministic patch operations

Provider responses are not applied directly. After validation and reconciliation, Book2Epub derives explicit internal patch operations.

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
    "group_callout_members",
    "group_example_members",
    "set_outline_parent",
]


class SemanticPatchOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str
    kind: PatchOpKind
    block_ids: list[str]
    target: str | None = None
    confidence: float
    source_decision_request_ids: list[str] = Field(default_factory=list)
    evidence_codes: list[str] = Field(default_factory=list)
```

Patch operations contain no arbitrary replacement publication text.

A patch is produced only after hard validation. Provider code never mutates BookIR directly.

---

## H15. BookIR semantic components

### H15.1 Preformatted block

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
    caption: list[Inline] = Field(default_factory=list)
    footnotes: list[Inline] = Field(default_factory=list)
```

`text` comes only from authoritative deterministic evidence such as:

- existing `CodeBlock.text`, or
- `SemanticEvidenceBlock.preformatted_text`.

The LLM never provides `text`.

### H15.2 Containers

M8/M10 may use:

```text
Callout
BlockQuote
ExampleBlock
ExerciseBlock
DefinitionList
```

New wrapper containers always get new deterministic IDs. Child blocks retain their IDs and provenance.

Do not create arbitrary recursive structures merely because the model requested them. A container is legal only through a registered block materializer or validated relation operation.

---

## H16. Audit schemas

Every proposed semantic outcome must be auditable, including accepted, rejected, low-confidence, conflicting, and unimplemented outcomes.

### H16.1 Block decision audit

```python
BlockDecisionStatus = Literal[
    "applied",
    "preserved_original_low_confidence",
    "preserved_original_conflict",
    "rejected_invalid_target",
    "rejected_unimplemented_target",
    "rejected_hash_mismatch",
    "queued_visual_review",
    "visual_override_applied",
]


class SemanticBlockAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    block_id: str
    source_kind: str
    operation: SemanticOperation
    proposed_target: str | None
    final_target: str
    confidence: float
    evidence_codes: list[str] = Field(default_factory=list)
    provider: str
    model: str
    request_ids: list[str] = Field(default_factory=list)
    status: BlockDecisionStatus
    rejection_reason: str | None = None
    source_content_sha256: str
```

### H16.2 Relation audit

```python
RelationDecisionStatus = Literal[
    "applied",
    "preserved_original_low_confidence",
    "preserved_original_conflict",
    "rejected_invalid_relation",
    "rejected_scope_violation",
    "rejected_preservation_mismatch",
    "queued_visual_review",
]


class SemanticRelationAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_id: str
    relation_type: RelationType
    source_block_ids: list[str]
    target_block_id: str | None
    confidence: float
    evidence_codes: list[str] = Field(default_factory=list)
    provider: str
    model: str
    request_ids: list[str] = Field(default_factory=list)
    status: RelationDecisionStatus
    rejection_reason: str | None = None
    before_fingerprint: str
    after_fingerprint: str | None = None
```

### H16.3 Authoritative applied artifact

Persist a versioned wrapper rather than an untyped mixed list:

```python
class SemanticApplicationAuditFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    block_decisions: list[SemanticBlockAuditRecord] = Field(default_factory=list)
    relations: list[SemanticRelationAuditRecord] = Field(default_factory=list)
```

Path:

```text
semantic/applied.json
```

If compatibility with an older list-only artifact is temporarily required, use an explicit compatibility reader/writer. Do not let the runtime accept ambiguous shapes silently.

---

## H17. Semantic-stage persisted artifacts

The M8 semantic stage persists at least:

```text
semantic/evidence.json
semantic/draft.json
semantic/chunks/<chunk-id>.input.json
semantic/decisions/pass-a/<chunk-id>.json
semantic/decisions/pass-b/<chunk-id>.json
semantic/decisions/reconciled.json
semantic/book_state.json
semantic/outline.json
semantic/applied.json
ir/bookir.semantic.json
```

`reconciled.json` must include reconciled block decisions **and** reconciled relations. A cache hit must be able to re-materialize the same semantic IR without another provider call.

Provider raw response text may be retained only where policy permits and must never be treated as publication content.

---

## H18. Cache identity

The semantic cache key includes at minimum:

```text
raw BookIR stable hash
SemanticEvidence stable hash
SEMANTIC_EVIDENCE_SCHEMA_VERSION
SEMANTIC_DRAFT_SCHEMA_VERSION
STRUCTURE_DECISION_SCHEMA_VERSION
SEMANTIC_DECISION_SCHEMA_VERSION
SEMANTIC_RELATION_SCHEMA_VERSION
SEMANTIC_PATCH_SCHEMA_VERSION
PROMPT_CONTRACT_VERSION
BookState observation schema version
provider
model
reasoning effort / provider inference controls where applicable
chunk settings
review/auto-apply thresholds
provider output JSON Schema hashes
materializer capability/version identity
```

Changing Pass-B from schema `1.0` to `1.1` invalidates M8 semantic cache entries but must not invalidate MinerU or source ingestion caches.

M9 visual/OCR and M10 presentation maintain separate downstream cache identities.

---

## H19. Failure semantics

When semantic mode is explicitly enabled:

- unrecoverable provider/stage failure is fatal unless a separately documented explicit fallback mode was requested;
- individual low-confidence or invalid decisions are not stage failures: preserve original and audit them;
- partial application after an unrecoverable batch/stage failure is forbidden;
- relation application is transactional per relation: do not remove/move source blocks until attachment/group creation and preservation validation succeed;
- an invalid relation must not invalidate unrelated valid decisions unless the invalidity makes the whole batch untrustworthy.

M9 provider transport failure is **not** evidence that the M8 decision was semantically wrong. M9 failure handling is defined in Appendix K and must not silently reinterpret provider failure as a visual rejection.

---

## H20. Required schema and materialization tests

At minimum add or update tests proving:

### H20.1 Schema tests

1. `SemanticDecisionBatch.schema_version == "1.1"`.
2. Batch contains `decisions`, `relations`, and `observations`.
3. Arbitrary replacement text fields are rejected by `extra="forbid"`.
4. Old/stale semantic evidence-code strings are rejected for new provider responses.
5. Old `schema_version="1.0"` Pass-B cache is not accepted as `1.1`.
6. `related_block_ids` is not accepted as a substitute for first-class relations.

### H20.2 Allowed-target/materializer matrix

For every target advertised by `supported_targets()` on synthetic source/evidence fixtures, assert that:

- a deterministic materializer exists;
- materialization returns a valid BookIR node/container; and
- the preservation fingerprint remains valid.

If no deterministic materializer exists, the target must not be advertised.

### H20.3 Block conversion tests

At least:

- real table -> table unchanged;
- table containing shell/output evidence -> terminal preformatted using exact `preformatted_text`;
- code -> shell/log/config subtype with exact body preserved;
- paragraph -> callout with unique wrapper ID;
- paragraph -> block quote with unique wrapper ID;
- list creation uses deterministic item boundaries only;
- unavailable definition-list split is rejected/not advertised;
- unsupported allowed-target request produces explicit rejection audit, never silent no-op.

### H20.4 Relation tests

At least:

- Figure caption attachment;
- Chart caption attachment;
- Table/Code/Preformatted caption attachment where supported;
- caption page distance > 1 rejected;
- same caption source attached to two targets rejected/conflicted;
- footnote attachment preserves source provenance;
- multi-block callout grouping succeeds only for contiguous source blocks;
- grouping across a heading boundary is rejected;
- example grouping preserves child IDs and gives wrapper unique ID;
- paragraph continuation validates adjacency + page boundary;
- overlap relation conflict remains unresolved;
- live-path and cache-hit relation materialization are semantically equivalent.

### H20.5 Global invariants

After M8 application:

- recursive block IDs are unique;
- no source content leaf is lost or duplicated by structural operations;
- no provider rationale appears in publication text;
- no provider output text field is used as body/caption/footnote/table/math/code content;
- every applied/rejected block decision has an audit record;
- every applied/rejected relation has an audit record;
- `ruff`, `mypy`, and `pytest` pass.

---

## H21. Canonical example — table misclassified terminal output

Source evidence:

```text
preceding paragraph: "Run the following command."
current MinerU kind: table
preformatted_text:
$ docker compose up
[+] Running 4/4
redis      Started
postgres   Started
following paragraph: "The output above..."
```

Valid provider response:

```json
{
  "schema_version": "1.1",
  "chunk_id": "sem-0004-abc123def456",
  "decisions": [
    {
      "block_id": "blk-00185",
      "operation": "retype_and_set_subtype",
      "target_type": "terminal_output",
      "subtype": "terminal_output",
      "heading_level": null,
      "confidence": 0.98,
      "evidence_codes": [
        "PRECEDING_PROSE_INTRODUCES_COMMAND",
        "FOLLOWING_PROSE_REFERS_TO_OUTPUT",
        "TABLE_LACKS_SEMANTIC_COLUMNS"
      ],
      "rationale": "Context indicates command output rather than a semantic row-column table."
    }
  ],
  "relations": [],
  "observations": []
}
```

Python materialization:

```python
PreformattedBlock(
    id="blk-00185",
    sources=original_table.sources,
    text=evidence.preformatted_text,
    subtype="terminal_output",
    caption=original_table.caption,
    footnotes=original_table.footnotes,
)
```

The model does **not** return the terminal text.

---

## H22. Canonical example — caption relation

Source order:

```text
blk-00210 Figure
blk-00211 Paragraph: "図 3.2 ..."
blk-00212 Paragraph: normal prose
```

Valid relation:

```json
{
  "relation_type": "caption_of",
  "source_block_ids": ["blk-00211"],
  "target_block_id": "blk-00210",
  "confidence": 0.97,
  "evidence_codes": ["CAPTION_CONTEXT"],
  "rationale": "Caption label and adjacency identify the paragraph as the figure caption."
}
```

Application:

```text
before:
  Figure(id=blk-00210, caption=[])
  Paragraph(id=blk-00211, exact inlines)

after:
  Figure(id=blk-00210, caption=<exact blk-00211 inlines>)
```

`blk-00211` is removed from the top-level sequence only after exact transfer and preservation validation succeed. Its source text/provenance remains represented in the figure caption and preservation ledger.

---

## H23. Canonical example — single paragraph callout

Input:

```text
Paragraph id = blk-00301
text = exact source-derived note text
```

Valid semantic decision:

```json
{
  "block_id": "blk-00301",
  "operation": "retype_and_set_subtype",
  "target_type": "callout_note",
  "subtype": "note",
  "heading_level": null,
  "confidence": 0.94,
  "evidence_codes": ["CALLOUT_CONTEXT"],
  "rationale": "Recurring note convention and local language identify a note callout."
}
```

Correct materialization:

```text
Callout id = blk-00301--callout
  child Paragraph id = blk-00301
```

Incorrect materialization:

```text
Callout id = blk-00301
  child Paragraph id = blk-00301
```

The incorrect form violates recursive publication-unique IDs and must fail validation.

---

## H24. Implementation acceptance gate

Appendix H remediation is complete only when all of the following are true:

1. Repository Appendix H, M8, prompts, Pydantic models, generated JSON Schemas, validators, reconciler, materializer, cache loader, and tests use the same Pass-B `1.1` contract.
2. `SemanticDecisionBatch` contains first-class `decisions`, `relations`, and `observations`.
3. The old target-only `SemanticDecision` contract is not used for new provider calls.
4. Relations are used in the production path and in the cache-hit path.
5. Chart is included wherever caption/footnote relation targets support visual assets.
6. Every advertised `allowed_target` has a deterministic materializer for that evidence state.
7. Unsupported materialization is explicitly rejected/audited; silent no-op is impossible.
8. Semantic wrappers never duplicate child IDs.
9. Paragraph continuation uses one hard validator shared by all entry paths.
10. Structural operations preserve the authoritative source-content fingerprint.
11. Old `1.0` Pass-B caches do not replay under `1.1`.
12. No provider response can structurally inject arbitrary publication text.
13. All required schema, materializer-matrix, relation, cache-equivalence, ID-uniqueness, and preservation tests pass.

The governing principle is:

> **A model decision must never be stronger than Book2Epub’s deterministic ability to materialize, validate, audit, cache, and reverse it.**
