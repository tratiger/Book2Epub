# AGENTS.md — Book2Epub M6-M12 Governing Instructions

## Mission

Implement the approved M6-M12 extension for Book2Epub on top of the existing M0-M5 implementation. The target remains a standards-compliant **reflowable EPUB 3.3** for technical books, but M6-M12 add document-level semantic reconstruction, optional multimodal adjudication and OCR repair, and a much richer deterministic presentation system.

## Baseline

The specification was authored against repository commit:

```text
1fe4d3aef6e6508e663ee250025cb0b0664da96a
```

If the working tree is newer, do not reset or overwrite user changes. Read the diff from this baseline and adapt minimally while preserving the contracts below.

## Absolute rules

1. **Do not enter or request Plan mode.** The milestone files are the approved plan. Implement directly, in order.
2. **Do not browse the web to choose architecture, API syntax, package versions, models, prompts, schemas, or algorithms.** Those are frozen in appendices G-O. If an external API has changed and the frozen call fails, record an upstream mismatch and stop that provider path; do not redesign by web research.
3. **Implement M6 -> M7 -> M8 -> M9 -> M10 -> M11 -> M12 sequentially.** Each milestone has an acceptance gate.
4. **Preserve M0-M5 default behavior.** With semantic disabled, OCR correction off, and presentation legacy, Book2Epub must not require an LLM, cloud API, Ollama, or network.
5. **Windows native only.** No WSL/Docker requirement and no Linux-only required workflow.
6. **MinerU 3.4.5 `*_middle.json` remains the authoritative Document AI source.** Do not add a permanent PaddleOCR+MinerU ensemble.
7. **Do not add MinerU-Popo as a runtime dependency.** Adopt only the document-level ideas frozen in this specification.
8. **LLMs do not generate final XHTML, CSS, Markdown, EPUB package files, or arbitrary replacement prose.** Final rendering and packaging remain deterministic Python.
9. **Semantic Structured Output schemas must not contain an unrestricted replacement-text field.** A semantic model may choose types, levels, relations, finite styles, confidence and reason codes only.
10. **OCR correction is separate from semantic adjudication and defaults OFF.** It is permitted only when the user explicitly selects `safe` or `all`, source visual evidence exists, and the M9 validation rules pass.
11. **Math source text is immutable in M6-M12**, even under OCR correction `all`.
12. **Cloud calls require explicit `--allow-cloud`.** No implicit cloud fallback from local provider failure.
13. **API keys come from environment variables only.** Never accept an API key CLI option, save it to configuration, write it to logs, QA, caches, or exception details.
14. **OpenAI and Gemini requests are stateless (`store=false`).** Do not create server-side conversation state.
15. **Do not enable provider tools.** No web search, file search, code interpreter, function calling, remote URL fetch, or agent runtime in semantic calls. The provider receives only Book2Epub-supplied text/images.
16. **Every provider response is validated again with Pydantic even when the provider guarantees Structured Outputs.** Schema compliance does not imply semantic correctness.
17. **Every structural change is auditable.** Store block id, old type, new type, provider/model, confidence, evidence codes, and application status.
18. **Every OCR text change is auditable and reversible.** Preserve exact old text, proposed text, source bbox, hash, provider/model, validation result and reason.
19. **Do not silently lose content while retyping.** A structural operation is allowed only if Book2Epub can materialize the target representation from existing middle.json/BookIR evidence without model-generated content.
20. **Presentation inference selects only finite tokens/enums.** It may never return raw CSS, arbitrary colors, JavaScript, font binaries, absolute coordinates, or HTML.
21. **Do not recreate print pages by absolute positioning.** bbox is evidence for semantics/style intent and source crop generation, not final page coordinates.
22. **No whole-page source-image background/overlay EPUB.** Original pages may appear only in external QA evidence.
23. **No JavaScript in EPUB.** No MathJax or runtime layout logic.
24. **Do not weaken EPUBCheck.** EPUBCheck 5.3.0 errors remain fatal.
25. **No TODO/stub/fake success paths.** Tests must assert meaningful structure and behavior.

## Precedence

When requirements conflict:

1. this `AGENTS.md`;
2. `00_PRODUCT_AND_ARCHITECTURE.md`;
3. current M6-M12 milestone;
4. appendices G-O;
5. original M0-M5 specs;
6. existing code/tests.

This order intentionally supersedes two original pre-M6 restrictions:

- “no LLM semantic correction” is replaced by optional structure-only semantic adjudication plus explicit optional OCR correction;
- “no cloud processing” is replaced by **default-off, explicit-opt-in cloud processing**.

If a genuine unresolved conflict remains, stop and report exact files/sections rather than choosing a new policy.

## Required quality commands

At the end of every milestone:

```powershell
uv run ruff check .
uv run mypy src/book2epub
uv run pytest -q
```

At M12 also run:

```powershell
uv run pytest -q -m epubcheck
```

Provider live tests are separate opt-in tests and MUST NOT be part of default `pytest`.

## Required code organization

New code should use these roots unless the milestone explicitly says otherwise:

```text
src/book2epub/semantic/
src/book2epub/providers/
src/book2epub/visual/
src/book2epub/presentation/
src/book2epub/typography/
```

Do not put all new behavior into `pipeline.py` or extend the existing `xhtml.py` monolith indefinitely. M10 must introduce component rendering helpers.

## Compatibility invariant

The following existing command must remain valid without any new setup:

```powershell
uv run book2epub convert .\pages -o book.epub
```

Equivalent defaults:

```text
semantic.enabled=false
semantic.vision=off/unused
ocr_correction.mode=off
presentation.mode=legacy
```

The current 150-page E2E test must continue to run without API keys or Ollama.

## Content immutability invariant

Before M9 OCR correction, all source visible text is immutable. Semantic adjudication may only change **interpretation**.

For a semantic operation:

```text
hash(user-visible source content before operation)
    ==
hash(user-visible source content after operation)
```

modulo deterministic representation rules explicitly defined in M6/M11 (e.g. list marker moved from item text into marker metadata). Such deterministic normalization must be audited separately from LLM changes.

When OCR correction is OFF, no provider is allowed to return or apply corrected text.

## Provider failure policy

- semantic disabled: provider configuration is ignored; no provider import/network required.
- no model-backed feature requested (`semantic=false`, OCR off, presentation not infer): do not import/create a provider.
- semantic enabled + configured provider unavailable: fail the semantic stage with actionable diagnostics; do not silently continue as legacy unless user explicitly requests a fallback policy added later.
- `presentation=infer` may use the configured provider even when semantic is disabled; style inference failure follows M10's specified fallback to enhanced.
- OCR correction `safe|all` may use the configured provider even when semantic is disabled; missing visual capability/evidence is a configuration error before any text mutation.
- semantic visual mode `auto` with a text-only provider: continue semantic text review but record visual review unavailable.

## Security and privacy

Treat OCR text, table HTML and images as untrusted input.

- sanitize HTML as before;
- never execute OCR code;
- never fetch OCR-recognized URLs;
- never interpolate untrusted content into shell commands;
- base64 cloud image uploads are allowed only under explicit cloud opt-in;
- no source images in logs;
- raw provider request artifacts must redact key/header fields and should store hashes/metadata rather than duplicate full image bytes.

## Change discipline

If a frozen provider SDK/API call no longer works, create/update:

```text
docs/upstream-mismatches.md
```

with:

- milestone/provider;
- installed package version;
- frozen expected call;
- exact exception (secret-redacted);
- minimal reproduction;
- whether other providers/local legacy path still work.

Do not browse for a replacement API while implementing this specification.
