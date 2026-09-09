# Baseline Code Audit — commit `1fe4d3aef6e6508e663ee250025cb0b0664da96a`

This file freezes the implementation facts that motivate M6-M12. The implementation agent should verify file existence locally, but should not redesign the system by web research.

## Pipeline

`src/book2epub/pipeline.py` currently performs:

```text
M1: images -> source PDF -> MinerU -> canonical middle.json
M2: MiddleJsonAdapter -> raw BookIR -> normalize_bookir -> normalized BookIR
M3: ReflowRenderer -> XHTML/MathML/CSS
M4: native EPUB package -> EPUBCheck
M5: QA report
```

The semantic insertion point is specifically between:

```python
raw_ir = adapter.convert_middle_json(data)
```

and:

```python
normalized_ir = normalize_bookir(raw_ir, ...)
```

Both `run_pipeline()` and `run_from_middle()` must use the same optional post-M5 extension path.

## Current adapter limitation

`src/book2epub/ir/adapter.py` converts MinerU guesses into typed BookIR immediately:

- `title` -> `Heading`
- `text` -> `Paragraph`
- `table` -> sanitized `Table` or image fallback
- `code` -> `CodeBlock`
- `image/chart` -> `Figure/Chart`
- equation -> `DisplayMath`
- list -> `ListBlock`

This is insufficient for contextual reclassification. Example: once a MinerU `table` has been reduced to sanitized HTML, a later semantic reviewer may no longer have a faithful preformatted line representation needed for `terminal_output`.

M6 therefore introduces an **Evidence layer built from both middle.json and Raw BookIR**, before semantic decisions are applied.

## Current BookIR limitation

`src/book2epub/ir/models.py` keeps a flat `BookIR.blocks` sequence and lacks technical-book components such as:

- terminal output/session
- shell command
- log output
- config file
- generic preformatted text
- rich callout variants
- block quote
- definition list
- example/exercise grouping

The flat block list should be retained for compatibility. M8 adds a parallel `BookOutline` tree rather than replacing source-order blocks with a nested tree.

## Current normalization limitation

`src/book2epub/ir/normalize.py` handles deterministic concerns only:

- page labels
- regex heading inference
- bbox-based figure/table layout hints
- pagebreaks
- conservative cross-page paragraph merging

It has no document-level context or semantic adjudication.

## Current text-join limitation

`src/book2epub/ir/text_join.py` currently:

- concatenates CJK->CJK boundaries;
- inserts one ASCII space at other boundaries;
- performs simple Latin dehyphenation;
- collapses ordinary spaces.

This can create unnatural Japanese/Latin boundaries such as artificial spaces around technical terms. M11 introduces source-segment/bbox-aware enhanced normalization while leaving legacy behavior available.

## Current renderer/style limitation

`src/book2epub/render/css.py` is intentionally minimal. It defines generic body, figure, pre/code, table, math and aside styles but lacks a complete typography rhythm and component vocabulary.

`src/book2epub/render/xhtml.py` is a large type-dispatch renderer. It does not distinguish source code from terminal/log/config presentation and has only a generic Aside style.

M10 introduces:

- `BookStyleProfile`
- finite presentation tokens
- component-specific deterministic renderers
- richer but reader-safe CSS

No LLM-generated raw CSS is allowed.

## Current list duplication issue

`ListBlock` renders as `<ol>`/`<ul>`, but existing item text may still contain OCR/source marker characters. Therefore an item whose content is `- foo` can render visually like `• - foo`.

M11 separates source markers from list item content and renders one canonical marker system.

## Current QA limitation

`src/book2epub/qa/checks.py` compares MinerU source type counts with final same-type counts. That is wrong once semantic adjudication intentionally changes `table -> terminal_output`, `text -> heading`, etc.

M12 changes QA from **type identity** to:

- provenance/content preservation;
- semantic-decision audit;
- unresolved ambiguity;
- structured asset reconciliation;
- OCR-correction audit;
- presentation/style integrity;
- EPUB validity.

## Current E2E contract

`tests/integration/test_test_img_e2e.py` runs the existing 150-page local input corpus and asserts valid EPUB plus nonzero code/table/figure counts.

Default M6-M12 configuration must not make this test require an LLM, API key, Ollama, or network.
