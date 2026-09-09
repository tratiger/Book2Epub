# M12 — QA, Semantic/Presentation Evaluation, Caching, and Release Gate

## Objective

Replace pre-semantic QA assumptions with quality checks appropriate for M6-M11 and make the extended pipeline production-usable on large books.

The old rule “MinerU says 10 tables, therefore final EPUB should contain 10 tables” is no longer valid. A correct semantic reviewer may intentionally convert some MinerU tables into terminal output.

M12 validates **preservation + justified transformation + EPUB semantics**, not source-type identity.

## 1. Required modules/changes

```text
src/book2epub/qa/checks.py
src/book2epub/qa/models.py
src/book2epub/qa/report.py
src/book2epub/qa/semantic.py
src/book2epub/qa/presentation.py
src/book2epub/qa/ocr.py
src/book2epub/qa/compare.py
src/book2epub/semantic/stage.py
src/book2epub/presentation/stage.py
src/book2epub/pipeline.py
src/book2epub/cli.py
```

Tests:

```text
tests/unit/test_qa_semantic.py
tests/unit/test_qa_presentation.py
tests/unit/test_qa_ocr.py
tests/integration/test_extended_mock_e2e.py
tests/integration/test_test_img_e2e.py      # existing test retained
```

## 2. Source disposition ledger

Create a machine-readable disposition for every meaningful M6 Evidence block:

```text
SourceDisposition
  block_id
  source_type
  source_content_sha256
  final_block_ids
  disposition:
    unchanged
    retyped
    moved_into_container
    attached_as_caption
    attached_as_footnote
    paragraph_merged
    semantically_superseded
    intentionally_suppressed_boilerplate
    unresolved_original_preserved
  semantic_operation_ids
  final_content_hashes
```

Every meaningful source block must have exactly one primary disposition.

Header/footer/page-number suppression remains permitted by existing policy but must be explicit.

## 3. New content-preservation check

PASS only when:

- every meaningful Evidence block has a disposition;
- no structural-only M8/M9 operation reports content-hash violation;
- no source asset disappears without `semantic_superseded` reason (e.g. table image superseded by valid table HTML, math fallback superseded by MathML);
- all retyped blocks have final nodes traceable to their source refs;
- OCR-corrected blocks are traceable through M9 correction audit.

Remove the old 70% approximate meaningful block count as the primary losslessness gate. Keep a coverage metric for display, but strict mode should require 100% disposition accounting of meaningful blocks.

## 4. Semantic transition metrics

Instead of source/final same-type equality, report:

```text
semantic_review_rate
semantic_change_rate
semantic_auto_apply_rate
semantic_visual_review_rate
semantic_conflict_rate
semantic_unresolved_rate
semantic_invalid_decision_rate
```

And a transition matrix, for example:

```text
table -> table              72
table -> terminal_output     6
table -> source_code         1
text  -> heading             4
title -> paragraph           2
```

A transition is not an error merely because types differ.

## 5. Heading/outline QA

Check:

- every BookOutline heading id resolves to an existing Heading;
- each Heading appears at most once in outline;
- parent level < child level;
- no cycles;
- source order of outline nodes is monotonic;
- TOC targets resolve;
- level jumps are warnings unless accepted by semantic hierarchy;
- renderer split boundaries align with outline where configured.

Metrics:

```text
heading_level_known_rate
outline_coverage_rate
heading_level_change_count
outline_conflict_count
```

## 6. Preformatted/code/table QA

### Preformatted

For every PreformattedBlock:

- source evidence preformatted text or CodeBlock text exists;
- final XHTML contains equivalent selectable text;
- subtype-specific component class exists.

### Table

For every final semantic Table:

- valid sanitized table HTML or documented image fallback;
- final XHTML table exists;
- row/col structure parses;
- no model-generated fabricated table is possible because M6 allowed-target validator must have evidence.

Report final table semantic rate relative to **final semantic table count**, not MinerU source table count.

### Code

Final CodeBlock/Preformatted source-code body must reconcile exact normalized line text unless OCR correction audit explicitly changed a segment.

## 7. OCR QA

Report:

```text
ocr_mode
oeligible_segment_count
ocr_candidate_count
ocr_proposal_count
ocr_applied_count
ocr_rejected_count
ocr_sensitive_confirmation_count
ocr_confirmation_disagreement_count
ocr_changed_codepoints
ocr_changed_fraction
ocr_budget_exceeded
```

Checks:

- OCR mode off -> applied_count must be 0;
- every applied proposal old hash resolves;
- every applied proposal has visual evidence;
- sensitive change has two matching confirmations;
- no math correction;
- no table HTML correction;
- total edits within budget.

Any violation is fatal in strict mode.

## 8. Presentation QA

Record:

```text
presentation_mode
style_profile_hash
style_inference_confidence
style_inference_fallback
component_counts
component_style_coverage
```

Checks enhanced/infer:

- every rendered semantic component has one known component class/style path;
- no raw provider CSS/HTML file exists;
- generated CSS has no `position:absolute`;
- no JavaScript;
- heading levels have deterministic typography rules;
- preformatted subtypes have distinct component classes;
- all images remain responsive;
- body line-height/margins resolve from profile tokens;
- inferred profile contains only schema enum values.

## 9. List duplication QA

Parse generated XHTML.

For semantic lists:

- source marker extracted in M11 must not remain duplicated at start of li text when a renderer marker is present;
- count `list_duplicate_marker_count`;
- strict enhanced/infer release requires zero duplicate-marker findings in test fixtures.

Do not globally reject a literal hyphen that is legitimate item text after the first token.

## 10. Typography QA

Report M11 normalization metrics.

Synthetic strict checks:

- CJK boundary test corpus has expected output;
- code/preformatted content unchanged by typography;
- no newline introduced into ordinary paragraph solely from print line wrap;
- source-segment fallback count visible.

Do not claim a numerical “Japanese readability score” from heuristics.

## 11. QA report HTML

Extend current offline `qa/report.html` sections:

1. Environment / pipeline modes
2. MinerU summary
3. Semantic reconstruction
4. Type transition matrix
5. Book outline tree
6. BookState observations
7. Visual arbitration
8. OCR correction audit summary
9. Presentation profile
10. Typography/list normalization
11. EPUB validation
12. Per-page/block provenance

For changed semantic blocks, show short excerpts capped to 160 chars and old/new **type**, not rewritten content.

For OCR changes, showing exact short old/new segment is allowed because correction audit requires it.

No cloud-hosted resources in QA HTML.

## 12. Cache/stage records

Use existing stage-record patterns.

Required stages:

```text
ingest
mineru
ir_raw
semantic_evidence
semantic_structure
semantic_visual
ocr_correction
ir_normalize
typography
presentation_profile
render
package
validate
qa
```

Not every run writes every optional stage; disabled optional stage gets a completed/skipped record with reason.

### Invalidation graph

```text
input changes -> everything
MinerU config -> MinerU onward
semantic provider/model/prompt/schema/threshold/chunk settings -> semantic_structure onward
vision setting/model -> semantic_visual onward
OCR correction mode/settings -> ocr_correction onward
presentation profile/mode -> presentation_profile/render onward
typography rules/version -> typography/render onward
renderer/CSS generator -> render onward
packager -> package onward
```

A CSS-only change must never rerun MinerU or semantic LLM.

## 13. Force options

Add:

```text
--force-semantic
--force-visual
--force-presentation
```

Rules:

- `--force-semantic` invalidates M8 decisions and M9/M10+ downstream but reuses MinerU/M6 evidence;
- `--force-visual` reruns M9 visual/OCR decision stage only where enabled, then downstream;
- `--force-presentation` reruns style inference/profile/render only;
- existing `--force-mineru` remains strongest upstream invalidation.

## 14. Provider cost/usage reporting

When provider usage fields exist, QA reports:

```text
calls by provider/model/purpose
input/output token counts
cache token counts when provider reports them
latency totals
```

Do not calculate currency cost from hard-coded prices in production; prices change. Token/call usage is stable evidence.

## 15. Evaluation command

Extend existing:

```powershell
uv run book2epub evaluate JOB_DIR
```

with semantic/presentation metrics.

Add optional comparison:

```powershell
uv run book2epub compare JOB_A JOB_B
```

It compares QA JSON only and prints:

- mode/provider/model differences;
- semantic transition counts;
- unresolved/conflict differences;
- OCR edit differences;
- component/style profile differences;
- EPUBCheck differences.

Do not claim one is objectively more readable solely from structural metrics.

## 16. Test fixtures

Create synthetic fixtures specifically covering the user-observed failures:

### Fixture A — command output misread as table

Prose says command/output; MinerU evidence type table; final semantic expected terminal output.

### Fixture B — genuine table

Must remain table.

### Fixture C — heading hierarchy

MinerU levels incomplete/mistyped; M8 mock decisions produce consistent hierarchy.

### Fixture D — Japanese technical prose

Contains:

```text
Linuxカーネル
C言語
UTF-8
日本語（Linux）
```

split over span/line boundaries; expected no artificial spaces.

### Fixture E — list marker duplication

MinerU ListBlock item text begins `-`, `•`, numbered markers; final contains one marker.

### Fixture F — component presentation

Heading under-rule, source code, terminal, config, note, table, figure; enhanced CSS/class assertions.

### Fixture G — OCR correction

Visually mocked proposal path with safe prose and sensitive code, including rejection cases.

## 17. Existing 150-page E2E

Retain `tests/integration/test_test_img_e2e.py` legacy/default behavior.

Add an **optional** high-quality E2E test for the same local `test-img` corpus:

```text
@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.provider_local   # if using Ollama live
```

It must skip if configured local provider/model is unavailable. Cloud API is never required by CI/default tests.

The high-quality local/manual evaluation should inspect at least:

- known command-output-as-table cases;
- headings;
- lists;
- Japanese/Latin spaces;
- code appearance;
- representative table/figure/callout rendering.

## 18. Manual reader checklist

Before v0.2 release:

- open legacy EPUB and high-quality EPUB side by side;
- test desktop EPUB reader and narrow mobile reader;
- resize font significantly;
- verify text reflows;
- inspect chapter/h2/h3 visual hierarchy;
- inspect heading bottom rules where profile selected them;
- copy code/terminal text;
- confirm no `• - item` duplicates;
- confirm common Japanese/Latin phrases do not gain artificial spaces;
- inspect true tables still behave as tables;
- inspect command output no longer looks like a table in known sample;
- EPUBCheck PASS.

## 19. Release commands

Required:

```powershell
uv run ruff check .
uv run mypy src/book2epub
uv run pytest -q
uv run pytest -q -m epubcheck
uv run book2epub doctor
```

Optional/manual:

```powershell
uv run pytest -q -m provider_local
uv run pytest -q -m provider_cloud
```

Never place live cloud tests in default release gate.

## 20. v0.2 Definition of Done

The project is done for this specification when:

1. existing default path works without LLM/network;
2. semantic mode can contextually reclassify structures with schema-constrained provider output;
3. BookState/BookOutline exist and chunk conflicts are conservatively handled;
4. visual mode adjudicates ambiguous/high-impact structure using source crops/pages;
5. OCR correction is OFF by default and safe/all obey strict audit/validation rules;
6. presentation enhanced/infer creates a richer deterministic component system and source-like visual grammar;
7. Japanese boundary spacing/list marker regressions are fixed in enhanced/infer;
8. QA evaluates preservation and justified transitions rather than MinerU type equality;
9. output remains reflowable, selectable and EPUBCheck-valid;
10. no PaddleOCR ensemble, MinerU-Popo runtime, fixed-layout page recreation, or model-written XHTML/CSS has entered the production architecture.
