# Book2Epub M6-M12 Specification Consistency Audit

Audit date: **2026-09-09 (Asia/Tokyo)**  
Specification baseline repository: `tratiger/Book2Epub`  
Verified current `master` head: **`1fe4d3aef6e6508e663ee250025cb0b0664da96a`**  
Baseline commit message: `E2E: Add test-img e2e test, CUDA_PATH auto-provisioning, and images subfolder resolution`

## 1. Audit result

**PASS — no unresolved normative contradiction found.**

Automated cross-document checks:

```text
checks: 108
passed: 108
failed: 0
```

The audit covers defaults, feature independence, semantic/visual/OCR schemas, thresholds, provider contracts, runtime ordering, cache invalidation, internal references, Markdown integrity, and stale-contract detection.

This result means the specification files are internally consistent at the freeze point. It does **not** promise that an upstream API will never change after the freeze; `AGENTS.md` defines how implementation must record a genuine upstream mismatch without redesigning silently.

## 2. Baseline code assumptions rechecked

The repository head is still the commit used for the code audit, so the following M0-M5 implementation facts remain the correct starting point:

- MinerU `middle.json` is converted by `MiddleJsonAdapter` into BookIR before deterministic normalization/rendering.
- default `JobConfig` has no semantic/provider/presentation-AI layer yet.
- `join_prose_texts()` has coarse CJK/non-CJK joining rules that can introduce unnatural Japanese/Latin spaces.
- the current EPUB stylesheet is a deliberately small generic stylesheet rather than a rich book-component design system.
- current QA assumes source/final type-count reconciliation in places where M8 retyping will make source-type identity invalid.
- the existing E2E path is a mandatory legacy-regression target and must not acquire an LLM/API dependency under default config.

See `BASELINE_CODE_AUDIT.md` for file-level details.

## 3. Contradictions found and resolved in the final audit

### A. Runtime order of presentation and typography

Earlier wording could be read as:

```text
normalize -> M10 presentation -> M11 typography -> renderer
```

but M11 may consume paragraph-indent intent from the selected `BookStyleProfile`. The final normative runtime order is now:

```text
Semantic BookIR
 -> deterministic normalize
 -> M10a resolve/select BookStyleProfile
 -> M11 typography / whitespace / list normalization
 -> M10b component renderer + deterministic CSS
 -> EPUB packaging
```

Milestone implementation order remains M10 then M11; M10 is intentionally split into a profile-resolution subphase and a later renderer subphase at runtime.

### B. Presentation cache/stage invalidation

The previous stage list placed typography before presentation-profile resolution and did not invalidate typography when the profile changed. Final M12 order/invalidation is:

```text
... -> ir_normalize -> presentation_profile -> typography -> render -> ...
```

A presentation profile/mode/style-inference change invalidates profile, typography, and render onward. `--force-presentation` reruns profile, typography, render/package/validation/QA.

### C. `SourceTextSegment` schema mismatch

M6 and Appendix H formerly described different segment fields. They now share one canonical schema with:

```text
segment_id
page_idx
block_id
line_index
span_index
text
bbox
boundary_before including page_continuation
source_span_type
text_sha256
```

This is the authoritative locator/evidence unit for M9 OCR correction and M11 spacing reconstruction.

### D. Evidence serialization condition

Evidence is not tied only to semantic reconstruction. It is generated when any evidence-dependent feature needs it:

```text
semantic.enabled
OR ocr_correction.mode != off
OR presentation.mode == infer
```

This preserves feature independence such as OCR-only and style-inference-only runs.

### E. Semantic Decision schema mismatch

Appendix H formerly had a simplified one-list decision schema while M8 had block operations plus relations. Appendix H is now canonicalized to M8:

```text
SemanticDecisionBatch
  decisions: SemanticBlockDecision[]
  relations: SemanticRelationDecision[]
```

The evidence-code enum and relation types now match M8 exactly. The response still contains no book-text replacement field.

### F. New BookIR class naming mismatch

Older appendix wording used names such as `CalloutBlock`, `QuoteBlock`, and `DefinitionListBlock`. The final names match M6:

```text
Callout
BlockQuote
DefinitionList
ExampleBlock
ExerciseBlock
PreformattedBlock
```

### G. Visual arbitration schema and threshold mismatch

Appendix K previously used a different response shape and a lower application threshold. It now matches M9:

```text
decision = confirm_proposed | reject_keep_original | replace_with_alternate
target_type / subtype / heading_level
confidence
evidence_codes
ocr_review_recommended
```

`replace_with_alternate` requires confidence **>= 0.85** plus validators.

### H. OCR correction schema, thresholds, confirmation, and book budget

The final canonical unit is one `SourceTextSegment`, located by `segment_id` plus provenance/hash validation.

Normal proposal includes:

```text
block_id
segment_id
line_index/span_index
old_text_sha256
proposed_text
confidence
reason_code
visually_verified
```

Normative thresholds:

```text
safe prose:        confidence >= 0.98, <=24 changed codepoints
sensitive digit/operator: confidence >= 0.995 + independent confirmation
all code/preformatted:    confidence >= 0.995, <=12 changed codepoints + confirmation
```

Normative automatic application budgets:

```text
safe: min(500 changed codepoints, 0.5% of eligible source codepoints)
all:  min(1000 changed codepoints, 1.0% of eligible source codepoints)
```

The independent confirmation response includes the proposed candidate itself, so the second request must return **exactly the same string** before a sensitive edit can apply. Math remains immutable.

### I. Vision-capability behavior

The final behavior is explicit:

- semantic `vision=auto` + non-vision provider/model: skip semantic visual arbitration, record `VISUAL_PROVIDER_UNAVAILABLE`, preserve original for unresolved queued/conflicting cases; no model substitution;
- semantic `vision=on`: source visual + vision-capable provider are required;
- OCR `safe|all`: source visual + vision-capable provider are always required independently of semantic vision setting;
- `presentation=infer`: source visual + vision-capable provider are required; missing capability/evidence is an error, not an `enhanced` fallback;
- `STYLE_INFERENCE_FALLBACK` is reserved for a validly attempted inference that fails schema/semantic validation or specified transient retries.

### J. Anthropic Opus 5 response handling

Claude Opus 5 has adaptive thinking on by default, so `response.content[0]` may be a thinking block. The final provider contract:

- sets `output_config.effort`;
- uses `output_config.format` JSON Schema;
- selects content by `block.type == "text"`;
- requires exactly one usable structured-output text block;
- never concatenates thinking/unrelated blocks.

### K. Provider output-token caps

The final frozen examples consistently carry the provider-neutral `max_output_tokens` into:

- OpenAI `max_output_tokens`;
- Google Interactions `generation_config.max_output_tokens` for text and vision;
- Anthropic `max_tokens`.

### L. Earlier resolved contradictions retained

Two contradictions discovered before this final pass remain resolved:

1. provider creation is feature-neutral and occurs when semantic reconstruction **or** style inference **or** OCR correction needs a model;
2. semantic ON + presentation legacy uses a `LegacySemanticBridge` so new semantic components remain renderable without enabling the enhanced visual theme.

## 4. Frozen external facts re-verified on 2026-09-09

The following official/current sources were rechecked while completing this audit:

### OpenAI

- `gpt-5.6-sol` supports image input and Structured Outputs; context 1,050,000, max output 128,000.
- Responses API exposes `store` (default true when omitted) and `max_output_tokens`; Book2Epub sends `store=False`.
- frozen Python SDK: `openai==3.10.0`, released 2026-09-09.

Sources:

- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- https://pypi.org/project/openai/3.10.0/

### Google Gemini

- Interactions API supports `store`, `generation_config.max_output_tokens`, and `thinking_level`.
- `gemini-3.8-flash` is GA, supports Structured Outputs and vision, and accepts low/medium/high thinking levels.
- `gemini-3.1-pro-preview` remains a valid configurable preview quality model.
- frozen Python SDK: `google-genai==2.22.0` (release history: 2026-09-02).

Sources:

- https://ai.google.dev/api/interactions-api-v1
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview
- https://pypi.org/project/google-genai/

### Anthropic

- Structured Outputs use `output_config.format` with `type=json_schema`.
- effort is set through `output_config.effort`.
- Claude Opus 5 adaptive thinking is on by default and may place thinking blocks before text blocks.
- frozen Python SDK: `anthropic==1.4.0`, released 2026-09-04.

Sources:

- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- https://platform.claude.com/docs/en/build-with-claude/effort
- https://platform.claude.com/docs/en/models/opus-5/whats-new-opus-5
- https://pypi.org/project/anthropic/1.4.0/

### Ollama

- JSON Schema can be passed through `format` and locally validated with Pydantic.
- Structured Outputs work with vision-capable models.
- frozen Python SDK: `ollama==0.6.2`, released 2026-04-29.

Sources:

- https://docs.ollama.com/capabilities/structured-outputs
- https://pypi.org/project/ollama/0.6.2/

## 5. Intentional choices that are not contradictions

The following are deliberate product decisions:

- **No permanent PaddleOCR + MinerU ensemble.** MinerU remains the sole perception backend for this extension.
- **No MinerU-Popo runtime dependency.** Its document-level ideas are reimplemented natively.
- **OCR correction is implemented but default OFF.** This is intentionally different from semantic structure repair.
- **Semantic reconstruction, style inference, and OCR correction are independently selectable.** They share provider settings but not enable flags.
- **Milestone order is M10 before M11, while runtime order is M10a -> M11 -> M10b.** This is intentional and explicitly documented.
- **Provider model strings are configurable.** Frozen defaults are not automatically replaced just because a newer model exists.
- **`presentation=legacy` is the default compatibility mode.** Enhanced typography/presentation stays opt-in until M12 release gates pass.

## 6. Automated checks performed

The 108 checks include:

- all three feature defaults;
- cloud opt-in;
- no ensemble/Popo runtime dependency;
- source-text immutability boundaries;
- exact SourceTextSegment fields;
- evidence-required condition;
- semantic evidence-code parity between M8/H;
- semantic relation parity;
- component class naming;
- visual-decision schema parity and threshold;
- OCR proposal/confirmation schema parity;
- OCR per-segment thresholds and book budgets;
- stale OCR schema/taxonomy absence;
- provider `max_output_tokens` propagation;
- Anthropic thinking-block-safe extraction;
- `store=False` for OpenAI/Google;
- M10a -> M11 -> M10b runtime order across Architecture, README, M11, and implementation prompt;
- presentation profile -> typography cache dependency;
- style inference visual-source requirements;
- internal milestone/appendix reference existence;
- balanced Markdown code fences;
- duplicate H2 detection;
- NUL-byte detection;
- stale superseded-contract phrase detection.

Result: **108/108 PASS**.

## 7. Remaining non-contradiction implementation risks

These are known engineering risks, not unresolved specification conflicts:

- provider SDK/API behavior can change after the 2026-09-09 freeze;
- source page availability can limit visual/style/OCR features in standalone `from-middle` runs;
- real Japanese technical-book layout diversity may reveal a need for additional finite presentation tokens;
- OCR correction `all` intentionally remains conservative and may leave correctable errors untouched;
- strict compatibility across EPUB readers still needs the M12 manual reader matrix in addition to EPUBCheck.

If implementation encounters a frozen-upstream mismatch, follow `AGENTS.md`: record `docs/upstream-mismatches.md`, keep unaffected paths operational, and do not silently redesign.
