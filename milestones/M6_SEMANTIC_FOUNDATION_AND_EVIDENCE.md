# M6 — Semantic Foundation, Evidence Preservation, and Compatibility

## Objective

Create the data structures required for semantic adjudication **without calling any LLM yet**. Preserve enough information from `middle.json` to safely reinterpret a block later. Extend BookIR/component vocabulary. Add configuration/path skeletons while proving that default legacy conversion remains unchanged.

## Why M6 exists

The current adapter collapses a MinerU `table` into sanitized table HTML. If a later reviewer determines that it is actually terminal output, Book2Epub needs the original line/span text to reconstruct `<pre>` exactly. Therefore semantic review cannot operate only on the already-reduced typed BookIR object.

M6 introduces:

```text
middle.json + Raw BookIR
        -> SemanticEvidence
        -> SemanticDraft
```

No model call occurs in M6.

## 1. Required new modules

```text
src/book2epub/semantic/
  __init__.py
  models.py
  evidence.py
  draft.py
  hashing.py
  apply.py             # skeleton utilities only; no provider decisions yet
src/book2epub/ir/
  models.py            # extend existing models
src/book2epub/config.py
src/book2epub/paths.py
src/book2epub/errors.py
```

Tests:

```text
tests/unit/test_semantic_models.py
tests/unit/test_semantic_evidence.py
tests/unit/test_semantic_compatibility.py
```

## 2. BookIR extensions

Keep existing classes and serialized compatibility. Add the following discriminated block types.

### 2.1 `PreformattedBlock`

```python
class PreformattedBlock(BlockBase):
    kind: Literal["preformatted"] = "preformatted"
    text: str
    subtype: Literal[
        "source_code",
        "shell_command",
        "terminal_output",
        "terminal_session",
        "repl_session",
        "log_output",
        "config_file",
        "generic_preformatted",
    ]
    language: str | None = None
    caption: list[Inline] = Field(default_factory=list)
    footnotes: list[Inline] = Field(default_factory=list)
```

The `text` field must originate from source evidence, not an LLM.

### 2.2 `Callout`

```python
class Callout(BlockBase):
    kind: Literal["callout"] = "callout"
    subtype: Literal["note", "tip", "warning", "caution", "important", "sidebar"]
    title: list[Inline] = Field(default_factory=list)
    blocks: list["Block"] = Field(default_factory=list)
```

### 2.3 `BlockQuote`

```python
class BlockQuote(BlockBase):
    kind: Literal["block_quote"] = "block_quote"
    blocks: list["Block"] = Field(default_factory=list)
    attribution: list[Inline] = Field(default_factory=list)
```

### 2.4 `DefinitionList`

```python
class DefinitionItem(BaseModel):
    term: list[Inline]
    definitions: list[list[Inline]]

class DefinitionList(BlockBase):
    kind: Literal["definition_list"] = "definition_list"
    items: list[DefinitionItem]
```

### 2.5 `ExampleBlock` / `ExerciseBlock`

These are grouping/semantic blocks, not free-form generated content.

```python
class ExampleBlock(BlockBase):
    kind: Literal["example"] = "example"
    label: list[Inline] = Field(default_factory=list)
    blocks: list["Block"] = Field(default_factory=list)

class ExerciseBlock(BlockBase):
    kind: Literal["exercise"] = "exercise"
    label: list[Inline] = Field(default_factory=list)
    blocks: list["Block"] = Field(default_factory=list)
```

Do not create these from MinerU in M6; they are targets available to later semantic application when source blocks can be grouped losslessly.

### 2.6 List metadata

Extend existing `ListBlock` in a backward-compatible way:

```python
marker_style: Literal[
    "auto", "disc", "circle", "square", "decimal", "alpha", "roman", "dash", "none"
] = "auto"
source_markers: list[str | None] = Field(default_factory=list)
```

Do not strip markers yet in legacy path.

### 2.7 Source text segments (backward-compatible)

Extend `Text` with optional source-segment metadata while retaining the existing joined `text` field:

```python
class SourceTextSegment(BaseModel):
    text: str
    source: SourceRef
    line_index: int | None = None
    span_index: int | None = None
    boundary_before: Literal["start", "same_line", "new_line", "unknown"] = "unknown"
    text_sha256: str

class Text(InlineBase):
    kind: Literal["text"] = "text"
    text: str
    source_segments: list[SourceTextSegment] = Field(default_factory=list)
```

Modify `MiddleJsonAdapter.extract_inlines()` so it populates `source_segments` from the exact source spans that contributed to each joined Text. **Do not change the existing `Text.text` joining algorithm in legacy mode.** This metadata is required by M9 OCR correction and M11 enhanced spacing reconstruction.

Old serialized Text nodes without `source_segments` continue to load with an empty list.

### 2.8 Parallel outline/state fields

Add optional/default-empty root fields to `BookIR`:

```python
outline: BookOutline | None = None
book_state: BookState | None = None
semantic_metadata: SemanticMetadata | None = None
presentation_profile: BookStyleProfileRef | None = None
```

To avoid import cycles, `BookOutline`, `BookState` and metadata models may live under `semantic.models` and use forward imports, or lightweight IR-side equivalents. Choose a clean typed arrangement but preserve serialized JSON.

Set new BookIR default schema version to `1.1`, while loader accepts existing `1.0` JSON.

## 3. SemanticEvidence schema

Create exact Pydantic models.

```text
SemanticEvidenceBook
  schema_version = "1.0"
  source_middle_sha256
  raw_bookir_sha256
  blocks: list[SemanticEvidenceBlock]
```

### `SemanticEvidenceBlock`

Required fields:

```text
block_id: str
page_idx: int
source_index: int | null
source_type: str
current_kind: str
bbox: [x0,y0,x1,y1] | null
page_size: [w,h]
plain_text: str
preformatted_text: str | null
table_html: str | null
asset_ids: list[str]
caption_text: str | null
footnote_text: str | null
line_segments: list[EvidenceLine]
content_sha256: str
allowed_targets: list[SemanticTarget]
flags: list[EvidenceFlag]
```

### `EvidenceLine`

```text
line_index
bbox
segments: list[EvidenceSegment]
```

### `EvidenceSegment`

```text
segment_index
span_type
text: str | null
image_path: str | null
bbox
text_sha256: str | null
```

The evidence representation may contain source text because it is internal input to the model, but model **output schemas may not return arbitrary replacements** until the separate M9 OCR proposal schema.

## 4. Exact evidence extraction rules

Evidence is built by correlating:

- `middle.json` `pdf_info[page].para_blocks[source_index]`;
- Raw BookIR `block.sources[0].source_index` and `page_idx`.

Use stable block id from Raw BookIR. Never match by text alone when source index exists.

### 4.1 `plain_text`

A best-effort visible-text flattening for model context. It is not authoritative for reconstruction.

- concatenate source line/span textual `content` in reading order;
- use single `\n` between source lines;
- retain inline equation source as a sentinel such as `<MATH:...>` only in evidence context; do not rewrite BookIR from this flattened string.

### 4.2 `preformatted_text`

Construct from **source lines**, not from table cell HTML.

For each source line:

```text
line_text = concatenation of textual span content in span order
```

Join lines with `\n`. Preserve characters/spaces supplied inside spans. Do not run `join_prose_texts()`.

For nested table/image/code blocks, recursively collect lines from body subblocks in source order.

This field is the materialization source for later table->preformatted reclassification.

### 4.3 `table_html`

If current Raw BookIR is a `Table`, copy its sanitized HTML. Also retain a boolean/flag when raw middle table HTML existed but sanitizer removed it.

Do not regenerate table HTML from text.

### 4.4 assets

List already-registered asset ids that are semantically tied to the block. Do not register full page images as content assets.

### 4.5 content hash

`content_sha256` is computed from a canonical JSON object containing all user-visible source representations relevant to the block:

```json
{
  "plain_text": "...",
  "preformatted_text": "...",
  "table_html_text_content": "...",
  "caption_text": "...",
  "footnote_text": "..."
}
```

Use UTF-8 JSON with sorted keys and `ensure_ascii=False`.

## 5. `allowed_targets`

The provider never gets unrestricted target freedom. Python computes allowed targets from available evidence.

Target enum:

```text
paragraph
heading
source_code
shell_command
terminal_output
terminal_session
repl_session
log_output
config_file
generic_preformatted
table
list
callout_note
callout_tip
callout_warning
callout_caution
callout_important
sidebar
block_quote
figure
chart
display_math
keep
```

Rules:

- heading/text source may target paragraph/heading/list/callout/quote/preformatted when preformatted text exists.
- table may target table OR preformatted subtypes if `preformatted_text` is nonempty.
- text may target table **only if valid sanitized `table_html` evidence exists**. Never ask model to invent rows/cells.
- code may target source_code/preformatted variants/paragraph only if exact source characters can be retained.
- image/chart may remain image/chart; visual relation changes are M8/M9. Do not convert visual content into prose.
- math can only `keep` in M6-M12 semantic type adjudication; no semantic reclassification that loses math.
- `keep` is always allowed.

## 6. Evidence flags

Compute deterministic flags used later to prioritize review. At minimum:

```text
TABLE_WITHOUT_CLEAR_HEADER
TABLE_CONTAINS_SHELL_PROMPT
TABLE_CONTAINS_CODE_TOKENS
TABLE_LOW_CELL_DENSITY
TEXT_LOOKS_PREFORMATTED
HEADING_LEVEL_UNKNOWN
HEADING_TOO_LONG
HEADING_ENDS_SENTENCE
LIST_MARKER_IN_TEXT
CALLOUT_LIKE_GEOMETRY
CROSS_PAGE_BOUNDARY_NEAR_BLOCK
HAS_VISUAL_ASSET
HAS_STRUCTURED_TABLE
```

These are review cues, not final classifications.

### Shell prompt cue

Detect conservative line-start patterns:

```regex
^\s*[$#>]\s+\S
^\s*[A-Za-z]:\\[^>]*>\s*\S
^\s*PS\s+[^>]*>\s*\S
```

### Code-token cue

Only a weak flag. Examples include multiple occurrences of `{}`, `()`, `;`, `=>`, `==`, common language keywords. Never retype solely from this flag.

## 7. SemanticDraft schema

`SemanticDraft` is the compact model input representation.

Do not dump raw middle JSON into prompts.

```text
SemanticDraftBook
  schema_version
  book_id
  blocks: list[DraftBlock]
```

Each DraftBlock includes:

```text
block_id
page_idx
source_type
current_kind
plain_text
preformatted_preview
has_table_html
bbox_normalized
caption_text
footnote_text
allowed_targets
flags
content_sha256
```

Limit previews deterministically:

- plain text max 4,000 Unicode codepoints per block;
- preformatted preview max 4,000;
- preserve first 2,000 + last 2,000 if truncating and set `preview_truncated=true`.

The full evidence remains on disk for application.

## 8. Config skeleton

Extend `config.py` with models, defaults only; provider use is M7.

```python
class SemanticConfig(BaseModel):
    enabled: bool = False
    provider: Literal["ollama", "openai", "google", "anthropic"] = "ollama"
    model: str | None = None
    allow_cloud: bool = False
    vision: Literal["off", "auto", "on"] = "auto"
    auto_apply_threshold: float = 0.80
    review_floor: float = 0.45
    max_chunk_chars: int = 24_000
    max_chunk_blocks: int = 60
    overlap_blocks: int = 8

class OCRCorrectionConfig(BaseModel):
    mode: Literal["off", "safe", "all"] = "off"

class PresentationConfig(BaseModel):
    mode: Literal["legacy", "enhanced", "infer"] = "legacy"
```

Add them to `JobConfig` with default factories.

No new option changes default conversion behavior.

## 9. Paths

Extend `JobPaths`:

```text
semantic/
  evidence.json
  draft.json
  stage.json
  chunks/
  decisions/
  book_state.json
  outline.json
  applied.json
  provider-usage.json
  visual/
  ocr-corrections.json
presentation/
  book-style-profile.json
  normalization-report.json
```

`ensure_directories()` creates them.

## 10. Errors

Add typed exceptions:

```text
SemanticError(stage="semantic")
ProviderError(stage="provider")
VisualReviewError(stage="visual")
OCRCorrectionError(stage="ocr_correction")
PresentationError(stage="presentation")
```

No secret/provider response body containing full source data should be embedded automatically into exception `details`.

## 11. Legacy compatibility

`run_conversion_m2()` in M6 builds/persists semantic evidence whenever any evidence-dependent feature is requested:

```text
cfg.semantic.enabled == true
OR cfg.ocr_correction.mode != "off"
OR cfg.presentation.mode == "infer"
```

`presentation=enhanced` alone does not require the evidence JSON file, although `Text.source_segments` are still populated in BookIR for M11. When semantic is disabled, OCR correction is off, and presentation is legacy/enhanced without inference, do not instantiate any provider. When everything is legacy/off, keep the current raw->normalize behavior.

M6 must not change current output CSS/XHTML.

Existing test `tests/integration/test_test_img_e2e.py` must not require any new provider dependency.

## 12. Serialization

Write when semantic enabled:

```text
semantic/evidence.json
semantic/draft.json
```

Do not put absolute API keys or image bytes inside these files.

Pydantic round-trip equality is required.

## 13. Tests

Add synthetic evidence fixture with:

- ordinary paragraph;
- real table with header;
- MinerU-table-looking shell output;
- code block;
- heading unknown level;
- unordered list containing `-` marker;
- aside-like block;
- figure/caption;
- math.

Assertions:

1. table shell block has both `table_html` (if source provides) and exact `preformatted_text`;
2. `allowed_targets` permits terminal output for ambiguous table;
3. ordinary table cannot be converted to a fabricated target requiring unavailable data;
4. code whitespace in `preformatted_text` is exact;
5. evidence hash is deterministic;
6. draft truncation is deterministic;
7. old BookIR 1.0 fixture loads;
8. new BookIR 1.1 round-trips;
9. default CLI/config creates no semantic provider call;
10. existing renderer tests remain unchanged/pass.

## 14. Acceptance gate

M6 is complete when:

```powershell
uv run ruff check .
uv run mypy src/book2epub
uv run pytest -q
```

pass, and a new test proves:

```text
legacy config -> existing pipeline path, zero provider imports/calls
semantic config -> evidence/draft files produced before any model is available
```
