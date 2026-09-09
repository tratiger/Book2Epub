# M8 — Document-Level Structure, Book State, and Semantic Adjudication

## Objective

Use the M7 structured-provider layer to perform **document-level semantic reconstruction** over M6 SemanticDraft/Evidence while keeping source text immutable. Adopt the useful MinerU-Popo concepts — dynamic chunks, overlap, document-level hierarchy, synchronization — without importing MinerU-Popo.

M8 operates when `cfg.semantic.enabled=True`. When false, it is a zero-op and the existing M2 normalize path remains authoritative.

## 1. Required modules

```text
src/book2epub/semantic/
  chunking.py
  structure.py
  book_state.py
  decisions.py
  reconcile.py
  apply.py
  relations.py
  prompts.py
  stage.py
```

Tests:

```text
tests/unit/semantic/test_chunking.py
tests/unit/semantic/test_structure_schema.py
tests/unit/semantic/test_reconcile.py
tests/unit/semantic/test_apply.py
tests/unit/semantic/test_book_state.py
tests/integration/test_semantic_mock_pipeline.py
```

## 2. M8 pipeline insertion

Refactor the M2 portion into explicit substeps:

```python
raw_ir = adapter.convert_middle_json(data)
save(raw_ir)

if cfg.semantic.enabled:
    evidence = build_semantic_evidence(data, raw_ir)
    draft = build_semantic_draft(evidence)
    semantic_result = run_semantic_reconstruction(raw_ir, evidence, draft, cfg, paths)
    semantic_ir = semantic_result.bookir
else:
    semantic_ir = raw_ir

normalized_ir = normalize_bookir(semantic_ir, ...)
```

Write semantic-stage output before deterministic normalization:

```text
ir/bookir.semantic.json
```

When semantic is disabled, this file may be omitted; `bookir.normalized.json` remains as today.

## 3. Two-pass document reasoning

Do not ask one prompt to decide every property at once.

### Pass A — structure/hierarchy

Purpose:

- identify which candidate blocks are headings;
- determine heading levels 1..6;
- detect paragraph continuations across page boundaries;
- detect obvious section-boundary anomalies;
- produce a stable outline skeleton.

### Pass B — semantic block adjudication

Using the provisional outline + BookState:

- `table` vs true table vs preformatted terminal/log/config/code;
- paragraph/list/callout/quote classification;
- source code vs shell command vs terminal output/session vs REPL/log/config;
- limited relationships: caption/footnote/callout/example membership when source evidence supports them.

Visual evidence is not sent in M8. Ambiguous/conflicting decisions are queued for M9 if vision is available.

## 4. Dynamic chunking

Input is the compact SemanticDraft, not middle.json and not page images.

Defaults from SemanticConfig:

```text
max_chunk_chars = 24,000
max_chunk_blocks = 60
overlap_blocks = 8
```

### Chunk algorithm

Walk blocks in source order.

A chunk ends before adding the next block if either:

- total preview characters would exceed max_chunk_chars;
- block count would exceed max_chunk_blocks.

Then start next chunk with the final `overlap_blocks` blocks of the prior chunk, unless that would cause no forward progress.

Prefer a nearby heading boundary within the last 8 non-overlap blocks when it keeps chunk size >= 50% of target. Do not split an M6 container/group structure internally.

Chunk ID:

```text
sem-0001-<sha256 first 12>
```

Hash includes ordered block ids, their content hashes, prompt contract version, provider and model.

Write each compact input to:

```text
semantic/chunks/<chunk-id>.input.json
```

## 5. Pass A response schema

Create `StructureDecisionBatch`, with no replacement text fields.

```text
schema_version: "1.0"
chunk_id: str
decisions: list[StructureDecision]
```

`StructureDecision`:

```text
block_id: str
is_heading: bool | null
heading_level: 1..6 | null
paragraph_continuation_of: str | null
confidence: 0..1
evidence_codes: list[StructureEvidenceCode]
rationale: str  # max_length 240, audit only, never applied as book content
```

Evidence codes enum:

```text
NUMBERING_PATTERN
MINERU_TITLE_SIGNAL
PRECEDING_SECTION_CONTEXT
FOLLOWING_SECTION_CONTEXT
CROSS_PAGE_SENTENCE_CONTINUITY
TYPOGRAPHIC_GEOMETRY_SIGNAL
BOOK_HIERARCHY_CONSISTENCY
AMBIGUOUS
```

The prompt explicitly says:

- return exactly one decision only for blocks requiring confirmation/change;
- do not copy/rewrite paragraphs;
- use only block IDs and supplied evidence;
- if uncertain, lower confidence rather than guessing.

## 6. Pass A validation/application

For each decision:

- block id must exist in current chunk;
- `heading_level` allowed only when target block can be represented as Heading without changing text;
- paragraph continuation requires both ids be Paragraph-compatible, adjacent across source page boundary, and no intervening meaningful block;
- decision content hash does not change.

Confidence:

```text
>= 0.80  eligible for automatic application when overlap agrees
0.45 <= c < 0.80 queue for visual review/unresolved
< 0.45   preserve original; record low-confidence rejection
```

Do not apply a low-confidence change merely because a model returned it.

## 7. Overlap reconciliation

The same block can appear in multiple chunks.

Rules:

1. all overlapping decisions agree on semantic result -> merge; confidence = arithmetic mean;
2. one chunk has decision and another omits it -> keep the decision, but mark `single_vote=true` and require >=0.85 for automatic application;
3. conflicting targets/levels -> **do not choose a winner numerically**; create `SemanticConflict` and queue to M9;
4. if M9 visual review unavailable/off, preserve the original structure for conflicts;
5. all raw decisions remain in audit files.

This is deliberately more conservative than “take highest confidence”.

## 8. Provisional BookOutline

After Pass A, build a deterministic outline from accepted headings.

Model:

```text
BookOutline
  schema_version
  roots: list[OutlineNode]

OutlineNode
  node_id
  heading_block_id
  level
  parent_node_id | null
  child_node_ids
  first_block_id
  last_block_id | null
```

Do not duplicate title text in the authoritative outline. UI/debug utilities can derive it from the referenced heading block.

Tree rules:

- heading level N attaches to nearest preceding heading with level < N;
- level jump attaches to nearest shallower heading and records a hierarchy warning;
- level 1 has no parent;
- no model-generated invisible section nodes in v1.

## 9. Initial BookState

Generate a compact state before Pass B.

### Deterministic state fields

Compute without LLM:

```text
heading_level_counts
heading_numbering_patterns
observed_code_languages
figure_number_labels
 table_number_labels
listing_number_labels
block_type_counts
```

### Model-assisted observed terms/conventions

Optional in semantic mode, returned as `BookStateObservationBatch`:

```text
domain_terms:
  - term: str
    source_block_id: str
semantic_conventions:
  - enum convention + source_block_ids
```

Every returned `term` must appear **verbatim** in the referenced block’s evidence text; otherwise discard and audit as invalid. Do not store a free-form book summary.

Convention enums:

```text
PREDOMINANT_C_SOURCE
PREDOMINANT_PYTHON_SOURCE
PREDOMINANT_SHELL_EXAMPLES
FREQUENT_TERMINAL_TRANSCRIPTS
NUMBERED_CODE_LISTINGS
NUMBERED_FIGURES
NUMBERED_TABLES
RECURRING_NOTES
RECURRING_WARNINGS
```

BookState is serialized:

```text
semantic/book_state.json
```

## 10. Pass B response schema

`SemanticDecisionBatch`:

```text
schema_version
chunk_id
decisions: list[SemanticBlockDecision]
relations: list[SemanticRelationDecision]
```

### `SemanticBlockDecision`

```text
block_id
operation: keep | retype | set_subtype | retype_and_set_subtype | set_list_kind
 target_type: SemanticTarget | null
subtype: str | null
heading_level: int | null  # normally null in Pass B
confidence: float
evidence_codes: list[SemanticEvidenceCode]
rationale: str  # max 240, audit only
```

No `text`, `replacement`, `html`, `code`, `latex`, `content`, `css` or equivalent field is permitted.

Semantic evidence code enum at least:

```text
PRECEDING_PROSE_INTRODUCES_CODE
PRECEDING_PROSE_INTRODUCES_COMMAND
PRECEDING_PROSE_INTRODUCES_OUTPUT
FOLLOWING_PROSE_REFERS_TO_OUTPUT
SHELL_PROMPT_PATTERN
CODE_SYNTAX_PATTERN
MONOSPACED_OR_PREFORMATTED_LAYOUT
TABLE_HAS_REAL_ROW_COLUMN_SEMANTICS
TABLE_LACKS_SEMANTIC_COLUMNS
LOG_PATTERN
CONFIG_PATTERN
REPL_PATTERN
LIST_PATTERN
CALLOUT_CONTEXT
QUOTE_CONTEXT
CAPTION_CONTEXT
BOOK_STATE_PATTERN
OUTLINE_CONTEXT
MINERU_CLASSIFICATION_SUPPORTED
MINERU_CLASSIFICATION_CONTRADICTED
AMBIGUOUS
```

## 11. Semantic target materialization

Python, not the model, creates target BookIR nodes.

### table -> preformatted

Use `SemanticEvidenceBlock.preformatted_text` exactly.

```text
terminal_output -> PreformattedBlock(text=evidence.preformatted_text, subtype="terminal_output")
```

Never serialize table HTML text back into invented alignment.

If preformatted source evidence is empty, reject the decision even if model requested it.

### code -> richer preformatted

Use the original CodeBlock text exactly. Map subtype based on validated decision.

### paragraph -> heading

Reuse existing `inlines` exactly; only node class/level changes.

### heading -> paragraph

Reuse inlines exactly.

### text -> list

Allowed only when evidence has at least two source lines/items with parsable marker or when Raw BookIR already has list item structure. M11 performs final marker stripping. No model-generated list item text.

### paragraph/aside -> callout

Single-block conversion wraps an exact cloned paragraph inside Callout.blocks.

Multi-block callout grouping is permitted only through a validated relation whose block ids are contiguous, do not cross a heading boundary, and preserve source order.

### block quote

Same content-preservation rule.

### text -> table

Permitted only when existing valid `table_html` evidence is present. Otherwise reject.

## 12. Relation decisions

`SemanticRelationDecision`:

```text
relation_type:
  caption_of
  footnote_of
  paragraph_continuation
  member_of_callout
  member_of_example
source_block_ids: list[str]
target_block_id: str | null
confidence
evidence_codes
rationale
```

Validation:

- all ids exist;
- source-order contiguity required for grouping;
- caption/footnote target must be figure/chart/table/code/preformatted-compatible;
- caption source must not already be attached elsewhere;
- no relation may delete its source text without moving the exact same inline content into the target container;
- page distance <= 1 for caption/footnote in v1;
- paragraph continuation only adjacent across page boundary.

Uncertain relation goes to M9 or remains unapplied.

## 13. Semantic application audit

Write:

```text
semantic/decisions/pass-a/*.json
semantic/decisions/pass-b/*.json
semantic/decisions/reconciled.json
semantic/applied.json
ir/bookir.semantic.json
semantic/outline.json
semantic/book_state.json
```

`applied.json` entry:

```text
operation_id
block_ids
old_kinds
new_kinds
old_content_hashes
new_content_hashes
provider
model
confidence
evidence_codes
status: applied|rejected|queued_visual|conflict|invalid
reason
```

For structural-only operations, old/new user-visible content hashes must match.

## 14. Pipeline behavior

Semantic stage failure is fatal when semantic explicitly enabled. Do not silently fall back to legacy.

However individual low-confidence decisions are not stage failures; preserve original block and continue.

## 15. Cache

Semantic cache key includes:

- evidence file SHA-256;
- provider + model;
- M8 schema/prompt contract version;
- thresholds/chunk settings;
- Book2Epub semantic stage schema version.

Provider/model change invalidates M8 onward but not MinerU/M6 evidence.

## 16. QA metrics introduced now

Record, but full QA rendering is M12:

```text
semantic_reviewed_blocks
semantic_applied_changes
semantic_preserved_originals
semantic_low_confidence_count
semantic_conflict_count
type_transition_matrix
heading_level_changes
relation_changes
content_hash_violation_count
```

Any content-hash violation in structural-only M8 is fatal.

## 17. Tests

Synthetic scenarios must include:

1. preceding paragraph says “以下のコマンドを実行”; MinerU table -> terminal output;
2. real table stays table;
3. `1.2` text block -> h2 without text modification;
4. paragraph mislabeled title -> paragraph;
5. code -> shell command subtype while exact bytes retained;
6. list-like text -> ListBlock from source lines only;
7. note-like paragraph -> Callout;
8. two-page paragraph continuation relation;
9. conflicting overlap decisions -> queued visual, original preserved;
10. hallucinated table target without table evidence -> rejected;
11. provider tries nonexistent block id -> rejected;
12. provider output rationale may differ but never becomes book content;
13. content hash equality before/after every applied structural operation.

Mock-provider integration test must run whole:

```text
middle fixture -> raw IR -> evidence -> M8 semantic -> normalize -> renderer -> EPUB package
```

and prove no API/network.

## 18. Acceptance gate

M8 complete when:

- semantic disabled path still passes existing tests unchanged;
- semantic mock path correctly fixes table->terminal and heading hierarchy;
- no structural application changes user-visible text hash;
- outline and BookState serialize/round-trip;
- overlap conflicts never auto-win by confidence alone;
- ruff/mypy/pytest pass.
