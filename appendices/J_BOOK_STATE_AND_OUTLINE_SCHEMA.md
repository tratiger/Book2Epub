# Appendix J — BookState and BookOutline Contract

M8 needs document-level memory without turning the provider into an uncontrolled long-running agent. BookState and BookOutline are explicit, serializable, bounded data structures.

## J1. BookState principles

BookState:

- contains observed recurring conventions, not a prose summary;
- contains no hidden chain-of-thought;
- does not authorize OCR changes;
- is merged deterministically in Python;
- has hard size limits;
- is supplied selectively to chunks;
- is auditable.

## J2. Schema

```python
class HeadingPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern_id: str
    numbering_family: Literal[
        "chapter_japanese", "chapter_english", "decimal", "roman", "unnumbered", "other"
    ]
    example_block_ids: list[str]
    likely_level: int = Field(ge=1, le=6)
    confidence: float = Field(ge=0, le=1)

class PreformattedConvention(BaseModel):
    convention_id: str
    subtype: Literal[
        "source_code", "shell_command", "terminal_output", "terminal_session",
        "repl_session", "log_output", "config_file"
    ]
    language_or_shell: str | None
    example_block_ids: list[str]
    confidence: float

class CalloutConvention(BaseModel):
    convention_id: str
    subtype: Literal["note", "tip", "warning", "caution", "important", "sidebar"]
    textual_cues: list[str]
    example_block_ids: list[str]
    confidence: float

class NumberingConvention(BaseModel):
    kind: Literal["figure", "table", "listing", "example", "exercise"]
    family: Literal["chapter-hyphen", "chapter-dot", "global", "roman", "other"]
    example_labels: list[str]
    confidence: float

class DomainTerm(BaseModel):
    normalized_key: str
    source_forms: list[str]
    example_block_ids: list[str]
    confidence: float

class BookState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    heading_patterns: list[HeadingPattern] = []
    preformatted_conventions: list[PreformattedConvention] = []
    callout_conventions: list[CalloutConvention] = []
    numbering_conventions: list[NumberingConvention] = []
    domain_terms: list[DomainTerm] = []
    confirmed_code_languages: list[str] = []
    revision: int = 0
```

Actual code uses default factories.

## J3. BookState hard limits

To keep prompts bounded:

```text
heading_patterns <= 16
preformatted_conventions <= 20
callout_conventions <= 12
numbering_conventions <= 12
domain_terms <= 80
confirmed_code_languages <= 16
textual_cues per callout <= 8
example block IDs per pattern <= 8
source_forms per domain term <= 8
```

When full, deterministic merge keeps higher-confidence, multiply-corroborated observations and drops the lowest-priority entries. Never let the model decide which previous state is deleted.

## J4. Observation schema

The provider returns observations, not a replacement BookState:

```python
class BookStateObservationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    chunk_id: str
    heading_patterns: list[HeadingPatternObservation]
    preformatted_conventions: list[PreformattedConventionObservation]
    callout_conventions: list[CalloutConventionObservation]
    numbering_conventions: list[NumberingConventionObservation]
    domain_terms: list[DomainTermObservation]
```

Each observation includes evidence block IDs and confidence.

## J5. Deterministic merge rules

### Heading patterns

Merge when same numbering family + same likely level and examples do not contradict.

- confidence = bounded weighted mean by distinct evidence blocks;
- append unique example IDs to cap;
- contradictory level observations remain separate until outline evidence resolves them;
- a single observation cannot overwrite an established >=0.9 pattern supported by >=3 distinct blocks.

### Preformatted conventions

Merge on subtype + normalized language/shell. Do not infer language from file extension alone unless source block explicitly provides it or semantic syntax evidence is strong.

### Callouts

Merge on subtype. Cues are literal short labels/prefixes observed in source (`NOTE`, `注`, `警告`, etc.), never invented explanations.

### Numbering

Merge on kind + family. Store only short label examples, not full captions.

### Domain terms

This is not a glossary generator. Add only exact repeated source spellings useful for consistency (`fork()`, `execve`, `PID`, `Unix`). Do not define terms or correct variants. A term needs >=2 source occurrences unless a heading/caption explicitly establishes it.

## J6. BookOutline schema

Keep BookIR content flat for renderer compatibility. BookOutline is a parallel tree referencing heading/block IDs.

```python
class OutlineNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    heading_block_id: str
    level: int = Field(ge=1, le=6)
    parent_node_id: str | None
    child_node_ids: list[str]
    first_block_id: str
    last_block_id: str | None

class BookOutline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    root_node_ids: list[str]
    nodes: dict[str, OutlineNode]
```

If provider portability makes dict values awkward for Structured Outputs, only Python serialization uses dict; provider output uses arrays.

## J7. Outline construction

After accepted Pass A heading decisions:

1. walk semantic blocks in source order;
2. when Heading(level=L) encountered, pop stack while top.level >= L;
3. parent is nearest remaining shallower heading;
4. create deterministic node id `outline-<sequence>-<heading-block-id>`;
5. first_block_id is heading block itself;
6. last_block_id is set to block immediately before next heading whose level <= current level, or final book block;
7. level jumps are allowed structurally but create QA warnings;
8. never invent a missing heading node solely to fill level gaps.

## J8. Outline prompt view

Do not send the entire tree to every chunk. Provide:

- nearest previous level 1 heading;
- nearest previous levels 2-4 as applicable;
- next known heading within limited window when available;
- up to 12 outline entries total.

Format as compact JSON:

```json
[
  {"block_id":"h-10","level":1,"text_preview":"Chapter 3 ..."},
  {"block_id":"h-15","level":2,"text_preview":"3.2 ..."}
]
```

Heading text previews are source text, capped at 160 codepoints.

## J9. BookState prompt view

Supply only categories relevant to the chunk:

- heading decisions -> heading patterns + numbering;
- code/terminal decisions -> preformatted conventions + code languages;
- callouts -> callout conventions;
- figure/table relation -> numbering conventions;
- always include max 20 relevant domain terms.

This reduces context and prevents stale irrelevant patterns dominating local evidence.

## J10. State persistence

Write:

```text
semantic/book_state.json
semantic/outline.json
semantic/book_state-observations/*.json
```

Every state file includes:

```text
schema version
source semantic evidence SHA-256
prompt contract version
revision
```

## J11. State conflict policy

BookState is evidence, not authority.

When local source evidence strongly contradicts a stored convention:

- do not force the convention;
- lower semantic confidence / queue visual review;
- record `BOOK_STATE_CONFLICT`;
- multiple later contradictory blocks can reduce/remove the convention through deterministic corroboration rules.

## J12. Tests

Must cover:

- heading patterns merge across chunks;
- one contradictory weak observation cannot overwrite established pattern;
- state limits deterministic;
- outline tree exact for h1/h2/h3 transitions and level jumps;
- flat BookIR order unchanged;
- prompt view is bounded and deterministic;
- no state field contains generated definitions or rewritten source prose.
