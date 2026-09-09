# M9 — Multimodal Visual Arbitration and Optional OCR Correction

## Objective

Use source-page visual evidence only where it adds value:

1. resolve semantic conflicts/low-confidence/high-impact reclassifications from M8;
2. optionally propose tightly-scoped OCR text corrections when the user explicitly enables them.

The default remains:

```text
ocr_correction.mode = off
```

M9 never changes math source.

## 1. Required modules

```text
src/book2epub/visual/
  __init__.py
  source.py
  raster.py
  crop.py
  models.py
  arbitration.py
  ocr_candidates.py
  ocr_schema.py
  ocr_apply.py
  validation.py
src/book2epub/providers/
  base.py              # vision request support finalized
  openai.py
  google.py
  ollama.py
  anthropic.py
```


## 1.1 Feature independence

M9 OCR correction is independent of M8 semantic reconstruction. If `cfg.semantic.enabled=false` but `ocr_correction.mode` is `safe` or `all`, M8 is a no-op and M9 operates on the M6 evidence plus the unchanged Raw BookIR. It writes `bookir.corrected.json`, which then proceeds to deterministic normalization.

Likewise, M9 semantic visual arbitration runs only for M8 structural decisions; OCR correction may still run when there were no M8 decisions. Provider creation follows Appendix G's `provider_required` rule.

Tests:

```text
tests/unit/visual/test_crop.py
tests/unit/visual/test_arbitration.py
tests/unit/visual/test_ocr_candidates.py
tests/unit/visual/test_ocr_apply.py
tests/integration/test_visual_mock_pipeline.py
```

## 2. Visual source priority

### Normal `convert`

Always prefer the existing M1 `input/source.pdf`. Its page coordinate system is the same document MinerU parsed, avoiding EXIF/rotation ambiguity with original image files.

Use `pypdfium2`, which the current codebase already imports for source-PDF page-count validation, to rasterize only requested pages.

### `from-middle`

Add options:

```text
--source-pdf PATH
--source-images-dir PATH
```

Priority:

1. explicit `--source-pdf`;
2. auto-discovered `input/source.pdf` in a recognized Book2Epub job workspace ancestor;
3. explicit `--source-images-dir` with page natural-order mapping;
4. otherwise no visual evidence.

If `--semantic-vision on` and no source visual evidence exists -> ConfigurationError.

If `--semantic-vision auto` and none exists -> continue text semantic mode, record `VISUAL_SOURCE_UNAVAILABLE`.

OCR correction safe/all requires visual evidence and therefore fails configuration if unavailable.

## 3. Page rasterization

Implement an LRU/local disk raster cache under:

```text
semantic/visual/pages/
```

Raster current page so longest edge <= 1800 px for full-page review.

For previous/next context pages use longest edge <= 1200 px.

Render RGB. Store full-page review as JPEG quality 90 unless line/text fidelity in tests shows PNG is required; target block crops are always PNG.

Cache key includes source PDF SHA-256, page index and raster scale.

Do not rasterize the whole book eagerly.

## 4. bbox crop mapping

MinerU middle bbox is expressed relative to `page_size=[W,H]`.

Given rendered page pixel size `(Rw,Rh)`:

```text
sx = Rw / W
sy = Rh / H
crop = [x0*sx, y0*sy, x1*sx, y1*sy]
```

Add padding:

```text
pad_x = max(12 px, 0.04 * crop_width)
pad_y = max(12 px, 0.04 * crop_height)
```

Clamp to page bounds.

Save:

```text
semantic/visual/crops/<block-id>.png
```

For line/span OCR correction, crop the segment/line bbox with 8% padding so neighboring glyph context remains visible.

## 5. Vision-capable provider input

Every visual adjudication request receives, in order:

1. target crop;
2. current full page;
3. previous page only when cross-page/hierarchy context is relevant;
4. next page only when relevant;
5. text prompt containing current SemanticDraft, BookOutline excerpt and BookState subset.

Maximum images per semantic arbitration request: 4.

Do not upload the entire book/PDF to a frontier provider in M9.

## 6. Provider image encoding

### OpenAI

Use Responses API with user content parts:

```python
input=[{
  "role": "user",
  "content": [
    {"type": "input_image", "image_url": "data:image/png;base64,..."},
    {"type": "input_text", "text": request.user_text},
  ],
}]
```

Keep `text.format` JSON Schema `strict=true`, `store=False`, no tools.

### Google

Interactions input entries:

```python
input=[
  {"type": "image", "data": image_bytes, "mime_type": "image/png"},
  {"type": "text", "text": request.user_text},
]
```

If the installed SDK requires base64/raw-data form as documented by its interaction content type, use the exact `google-genai==2.22.0` supported byte form. Keep `response_format` schema and `store=False`.

### Ollama

User message includes:

```python
{"role":"user", "content": text, "images":[str(path1), ...]}
```

and `format=response_schema`.

Ollama API capability supports vision, but the configured model itself may be text-only. A model vision failure is actionable ProviderError. Never auto-pull/replace the model.

### Anthropic

Use request-scoped base64 image content blocks before the text content block:

```python
{
  "type":"image",
  "source": {
    "type":"base64",
    "media_type":"image/png",
    "data": base64_data
  }
}
```

Use `output_config.format` JSON schema. Do not persist images through Files API.

## 7. Visual semantic review triggers

### `vision=off`

No M9 semantic vision call. M8 automatically accepted high-confidence non-conflicting changes remain; conflicts/queued changes remain original.

### `vision=auto`

Review:

- every M8 overlap conflict;
- every M8 decision with confidence in `[review_floor, auto_apply_threshold)`;
- every high-impact accepted retype involving `table <-> preformatted/code`;
- paragraph <-> heading changes with confidence < 0.90;
- uncertain caption/footnote relation;
- callout/sidebar classification when evidence relied on geometry;
- any decision carrying `AMBIGUOUS`.

### `vision=on`

Review every proposed semantic structural change plus all `auto` triggers. Do not review unchanged ordinary prose simply for costless “confirmation”.

## 8. Visual arbitration schema

`VisualSemanticDecision` contains only structure:

```text
block_id
decision: confirm_proposed | reject_keep_original | replace_with_alternate
target_type | null
subtype | null
heading_level | null
confidence
evidence_codes
rationale max 240
ocr_review_recommended: bool
```

No replacement text field.

Validation uses M6 `allowed_targets` and the same materialization rules as M8.

A visual decision overrides an M8 queued/conflicting decision only if confidence >= 0.85. Otherwise preserve original and record unresolved.

For high-impact table/preformatted changes that were already M8-applied, M9 may reverse them using the original evidence snapshot; no data should have been destroyed.

## 9. OCR correction modes

### `off`

No OCR correction candidate scan, no text-correction model request, no text mutation.

### `safe`

Only source segments belonging to prose-like content are eligible:

- Paragraph text;
- Heading text;
- list item text;
- Callout/Aside/Footnote prose;
- figure/chart/code/table captions and textual notes when represented as inline Text.

Excluded:

- CodeBlock/PreformattedBlock body;
- Table HTML/cells;
- DisplayMath/InlineMath/LaTeX;
- hyperlink URL target;
- generated metadata.

### `all`

Adds:

- CodeBlock body source segments where mapping exists;
- PreformattedBlock source segments.

Still excludes in M6-M12:

- LaTeX/MathML source;
- structured Table HTML cell mutation;
- image pixels;
- hyperlink URL targets.

“All” means broader eligible textual components, not unrestricted rewriting.

## 10. OCR candidate detection

Do not send every sentence to correction by default.

Candidate sources:

1. `ocr_review_recommended=true` from M9 visual semantic review;
2. source span confidence/score field when present and below a configurable threshold, preserved through `raw_extensions`;
3. Unicode replacement character `�`;
4. suspicious isolated alphanumeric confusion inside Japanese sequences;
5. broken token around line join detected by M11-compatible boundary analysis;
6. obvious OCR control/nonprinting character;
7. in `all`, syntax-token anomaly in code/preformatted may mark candidate but never auto-correct without visual double confirmation.

Candidate detector never changes text itself.

## 11. OCR proposal granularity

Correction is at `SourceTextSegment` granularity, not whole paragraphs.

Schema:

```text
OcrCorrectionProposal
  block_id
  line_index
  span_index
  old_text_sha256
  proposed_text
  confidence
  reason_code
  visually_verified: true
```

The provider is given the exact old segment text plus crop, but Python locates target using block/line/span/hash.

Reason code enum:

```text
GLYPH_CONFUSION
MISSING_CHARACTER
EXTRA_CHARACTER
BROKEN_WORD
BROKEN_JAPANESE_TOKEN
CODE_IDENTIFIER_GLYPH
PUNCTUATION_GLYPH
OTHER_VISUALLY_CLEAR
```

## 12. OCR proposal safety validation

Before apply:

1. block/line/span exists;
2. old hash matches exactly;
3. crop exists;
4. provider visual response confidence threshold passes;
5. target type eligible for selected mode;
6. proposal does not add/remove newline in `safe`;
7. source and proposed strings are nonempty unless visual evidence explicitly confirms an extra-character deletion;
8. edit distance budget passes;
9. math/URL/table exclusions enforced;
10. cumulative book edit budget passes.

### Edit budget calculation

Use Python `difflib.SequenceMatcher` opcodes; `changed_codepoints` is total inserted/deleted/replaced codepoints.

Safe prose:

```text
confidence >= 0.98
changed_codepoints <= 24 per segment
```

If correction changes any digit or ASCII operator symbol:

```text
confidence >= 0.995
requires confirmation pass
```

Sensitive `all` code/preformatted:

```text
confidence >= 0.995
changed_codepoints <= 12
requires confirmation pass
```

## 13. Confirmation pass

For digit/operator changes and code/preformatted corrections:

- issue a **fresh independent request** with a different request id;
- no `previous_response_id`, `previous_interaction_id`, or server conversation state;
- same source crop and exact old segment;
- second response must propose exactly the same `proposed_text`;
- second confidence >= required threshold.

If disagreement -> reject and preserve source.

## 14. Book-level overcorrection budget

Defaults:

```text
safe: min(500 codepoints, 0.5% of eligible source codepoints)
all:  min(1000 codepoints, 1.0% of eligible source codepoints)
```

When budget is exceeded, stop auto-application, leave remaining proposals unapplied, record `OCR_EDIT_BUDGET_EXCEEDED`. Do not silently raise the budget.

## 15. Applying a correction

Use `Text.source_segments` populated in M6.

Update the exact segment text, retain old value in correction audit, recompute `text_sha256`.

Then recompute the parent `Text.text`:

- before M11 enhanced typography, use the same legacy `join_prose_texts` semantics so OCR correction does not implicitly alter spacing policy;
- M11 may later recompute enhanced text from source segments.

For CodeBlock/PreformattedBlock in `all`, apply only when a stable segment->text mapping exists. If current evidence cannot locate exact segment offsets without ambiguity, reject rather than using string `.replace()` heuristics.

Never mutate source `middle.json`.

Write corrected semantic IR separately:

```text
ir/bookir.corrected.json
```

Then normalization consumes corrected IR.

## 16. Correction audit

Write:

```text
semantic/ocr-corrections.json
```

Each proposal/application:

```text
block_id/page/bbox/line/span
old_text
proposed_text
old/new hash
provider/model
first confidence
second confidence if applicable
reason code
mode
status: applied|rejected|budget_exceeded|mapping_ambiguous
validation reasons
```

This is the only M6-M12 provider-output path allowed to contain proposed replacement text.

## 17. Tests

Visual crop tests:

- bbox scaling/clamping;
- padding;
- correct page selected;
- current page PDF raster mapping;
- no eager whole-book raster.

Semantic arbitration tests:

- M8 table/terminal conflict + crop -> visual confirms terminal;
- visual rejects wrong proposed retype -> original restored;
- low-confidence visual -> original preserved;
- no visual source + auto -> warning; no crash;
- no visual source + on -> configuration error.

OCR tests:

- default off -> zero candidate/provider correction calls;
- safe prose `l`/`1` visually proposed, high confidence -> exact segment change only;
- safe attempts code change -> rejected;
- all code correction requires two exact matching confirmations;
- confirmation disagreement -> rejected;
- digit change requires confirmation;
- math correction always rejected;
- table HTML correction always rejected;
- wrong old hash -> rejected;
- ambiguous segment mapping -> rejected;
- cumulative edit budget stops overcorrection;
- all applied corrections are present in audit/reversible.

## 18. Acceptance gate

M9 complete when:

- semantic visual arbitration works with mocked vision providers;
- OCR OFF proves byte/content equality with M8 output before deterministic normalization;
- safe/all cannot edit excluded content;
- sensitive corrections require two independent matching visual decisions;
- no correction can be applied without source bbox/crop evidence;
- default existing E2E still requires no provider;
- ruff/mypy/pytest pass.
