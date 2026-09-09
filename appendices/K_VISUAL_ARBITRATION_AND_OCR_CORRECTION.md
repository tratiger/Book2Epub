# Appendix K — Visual Arbitration and Optional OCR Correction Contract

This appendix is normative for M9. Visual review resolves semantic uncertainty. OCR correction is a distinct, explicit feature and is **OFF by default**.

## K1. Visual evidence source

For normal `convert`, use the M1 multi-page `input/source.pdf` as visual authority because MinerU parsed that same page sequence.

For `from-middle`, priority:

1. explicit `--source-pdf`;
2. recognized Book2Epub job ancestor `input/source.pdf`;
3. explicit `--source-images-dir` natural-sorted mapping;
4. none.

`semantic-vision=on` with no visual source -> ConfigurationError.

`semantic-vision=auto` with no visual source -> continue text-only semantic mode and record warning.

OCR correction `safe` or `all` without visual source -> ConfigurationError before any mutation.

## K2. Raster/crop contract

Use existing `pypdfium2` dependency.

Full current page:

```text
longest edge <= 1800 px
RGB
JPEG quality 90 for cache
```

Neighbor context page:

```text
longest edge <= 1200 px
```

Target block/segment crop:

```text
PNG
bbox mapped from middle page_size to rendered pixels
block padding = max(12px, 4% width/height)
segment/line padding = 8%
```

Mapping:

```text
sx = rendered_width / source_page_width
sy = rendered_height / source_page_height
left   = x0 * sx
upper  = y0 * sy
right  = x1 * sx
lower  = y1 * sy
```

Clamp all coordinates.

## K3. Visual arbitration response schema

```python
class VisualSemanticDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str
    target: SemanticTarget
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(ge=0, le=1)
    visual_evidence_codes: list[VisualEvidenceCode]
    confirms_text_decision: bool
    rationale: str = Field(max_length=240)

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
```

Still no replacement text.

## K4. Visual semantic review triggers

### vision=off

No vision calls.

### vision=auto

Review:

- overlap conflicts;
- M8 confidence `review_floor <= c < auto_apply_threshold`;
- all accepted `table <-> source_code/preformatted/terminal` retypes;
- paragraph/heading retype below 0.90;
- callout/sidebar classification dependent on layout;
- uncertain caption/footnote association;
- decisions carrying AMBIGUOUS;
- any M8 validator-specific high-impact flag.

### vision=on

Review all changed semantic blocks plus all auto triggers. Do not review untouched ordinary paragraphs solely to spend tokens.

## K5. Visual application policy

- visual decision must choose from existing allowed_targets;
- content hash must still match;
- visual confidence >=0.80 required for a change;
- if text decision and visual decision conflict and neither is >=0.90, preserve original;
- if visual decision >=0.90 with clear evidence code and source validator passes, it may override an M8 text decision;
- every override records both decisions;
- visual model confidence does not override hard data-loss validator failures.

## K6. OCR modes

```text
off
safe
all
```

### off

No candidate generation, no correction calls, no text mutation.

### safe

Candidates limited to prose-like Text segments in:

```text
Paragraph
Heading
Caption
Footnote
Callout prose
List prose
```

Exclude:

```text
CodeBlock / PreformattedBlock
Table HTML/cells
InlineMath / DisplayMath / LaTeX
URLs and hrefs
file paths when detected
all-numeric identifiers
```

### all

Additionally allow Text segments in:

```text
source code/preformatted textual body
terminal/log/config textual body
```

but math remains excluded and sensitive verification rules apply.

## K7. OCR candidate generation

Do not send every segment.

Candidate signals are deterministic and conservative. A segment becomes a candidate only if at least one:

- OCR contains Unicode replacement/control anomaly;
- suspicious mixed alphanumeric token (`retum`, `0O`, `l1`) flagged by a narrow heuristic;
- semantic reviewer explicitly flags visually suspicious OCR without proposing replacement;
- duplicate nearby source evidence strongly differs in one/few glyphs;
- code/preformatted parser evidence suggests a glyph-level anomaly in `all` mode;
- user later supplies an explicit candidate list (future extension; not required in v1).

Do not use a dictionary spellchecker to rewrite all uncommon technical terms.

Cap automatic candidates:

```text
max 3 candidates per source page
max 0.5% of source text segments per book in safe mode before user override
```

This is an overcorrection defense, not an accuracy target.

## K8. OCR proposal schema

OCR correction is the only model output schema that may contain replacement text.

```python
class OCRCorrectionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str
    segment_id: str
    old_text_sha256: str
    proposed_text: str | None
    confidence: float = Field(ge=0, le=1)
    visible_error_type: Literal[
        "character_substitution",
        "missing_character",
        "extra_character",
        "spacing_inside_segment",
        "punctuation",
        "case",
        "no_clear_error",
    ]
    rationale: str = Field(max_length=200)

class OCRCorrectionBatch(BaseModel):
    schema_version: Literal["1.0"]
    proposals: list[OCRCorrectionProposal]
```

The schema does NOT permit changing multiple segments with one proposal.

## K9. Base validators for OCR proposal

Before any correction:

1. block/segment exists;
2. old hash matches current exact segment;
3. crop exists and corresponds to segment bbox/line;
4. proposed text not null and differs from old;
5. proposed text length <= max(4 * old length, old length + 16) to prevent paragraph generation;
6. proposal contains no newline unless original segment contains newline;
7. math/source span types prohibited;
8. edit distance bounded.

Default normalized Levenshtein budget:

```text
safe: max(2 characters, ceil(0.12 * old_len))
all:  max(3 characters, ceil(0.15 * old_len))
```

A larger edit is rejected rather than escalated automatically.

## K10. Sensitive-change detection

Sensitive if correction changes any:

- digit `0-9`;
- ASCII operator/punctuation used in code: `+-*/%=<>!&|^~:;.,()[]{}_$#@\\/`;
- case of ASCII identifier character in code/preformatted;
- non-space character in CodeBlock/PreformattedBlock;
- URL/path-looking token;
- hex value;
- IP address;
- version number;
- command option beginning `-` or `--`.

Sensitive proposals are allowed only in `all` and require independent confirmation.

## K11. Independent confirmation

For sensitive proposals:

- issue a second fresh vision request with same target crop;
- do not include the first model rationale/confidence;
- supply old text and proposed candidate;
- response schema:

```python
class OCRSensitiveConfirmation(BaseModel):
    confirm: bool
    exact_visible_match: bool
    confidence: float
```

Apply only when:

```text
confirm == true
exact_visible_match == true
confidence >= 0.95
first proposal confidence >= 0.95
second proposed candidate exactly matches first proposed_text
```

If confirmation schema does not return candidate text, compare confirmation against the candidate supplied in the request; it must state exact match true.

For maximum conservatism, use a new request id. It may use the same configured provider/model; “independent” means fresh context without first rationale.

## K12. Safe-mode thresholds

Safe prose correction applies only if:

```text
proposal confidence >= 0.98
not sensitive
edit budget passes
visual crop exists
segment source type is prose-like
```

If below threshold, retain as suggestion in audit but do not apply.

## K13. Book-level overcorrection budget

Track:

```text
changed_segments / total_text_segments
changed_codepoints / total_source_codepoints
```

Hard automatic stop:

```text
safe: changed_segments > 0.5% OR changed_codepoints > 0.10%
all:  changed_segments > 1.0% OR changed_codepoints > 0.25%
```

After hard stop, no further automatic changes are applied; candidates remain recorded and QA warns `OCR_CORRECTION_BUDGET_EXCEEDED`.

## K14. Applying correction

Correction updates the exact `SourceTextSegment.text`, then recomputes its SHA-256 and reconstructs the affected block text from source segments.

Until M11 enhanced typography exists:

- preserve legacy `join_prose_texts` boundary behavior when rebuilding ordinary prose;
- preserve exact PreformattedBlock/CodeBlock whitespace.

After M11, enhanced/infer mode uses enhanced segment-boundary reconstruction.

Never directly mutate final XHTML text.

## K15. Reversible audit

`semantic/ocr-corrections.json` stores:

```text
block_id
segment_id
page_idx
bbox
old_text
new_text
old_sha256
new_sha256
provider/model/request ids
first confidence
confirmation result if any
mode
status
reason
```

This file contains source snippets intentionally because reversibility requires exact old/new local data. It remains local job output and is never embedded in EPUB.

## K16. OCR correction QA categories

```text
applied_safe
applied_sensitive_confirmed
suggested_below_threshold
rejected_no_visual
rejected_hash_mismatch
rejected_edit_budget
rejected_math
rejected_sensitive_mode
rejected_confirmation
stopped_book_budget
```

## K17. Required tests

- off mode makes zero correction calls;
- safe prose obvious one-glyph crop proposal applies when mocked high confidence;
- same proposal without crop rejected;
- code change in safe rejected;
- code change in all requires second confirmation;
- digit/operator change requires second confirmation;
- math proposal always rejected;
- large rewrite rejected by edit budget;
- old hash mismatch rejected;
- budget halts subsequent changes;
- exact old/new audit allows reversal;
- semantic classification still does not contain replacement text.
