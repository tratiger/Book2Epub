# Book2Epub Product and Architecture Contract — M6-M12 Revision

## 1. Product goal

Convert cleaned technical-book page images into a readable, structurally faithful, ordinary **reflowable EPUB 3.3**.

“Faithful” has three dimensions:

1. **content fidelity** — text/code/math/table/figure information is not lost or invented;
2. **semantic fidelity** — headings, paragraphs, code, terminal output, tables, callouts, lists, captions and relationships reflect the book’s meaning and context;
3. **presentation fidelity** — the EPUB reproduces the book’s visual grammar (hierarchy, spacing rhythm, heading rules, code/callout/table treatment) without reproducing fixed page coordinates.

## 2. Approved architecture

```text
[clean source pages]
       |
       v
[M0-M1 existing ingest + MinerU]
       |
       v
[authoritative middle.json]
       |
       v
[existing MiddleJsonAdapter]
       |
       v
[Raw BookIR]
       |
       +-------------------------- semantic OFF -------------------------+
       |                                                                   |
       |                                                        existing normalize
       |                                                                   |
       |                                                                   v
       |                                                              legacy render
       |
       +-- semantic ON --------------------------------------------------+
           |
           v
[M6 SemanticEvidence / SemanticDraft]
  multiple source representations preserved
  exact content hashes + bbox + raw source type
           |
           v
[M7 Provider abstraction]
  Ollama | OpenAI | Google Gemini | Anthropic
  strict Structured Outputs
           |
           v
[M8 document-level semantic reconstruction]
  BookState + BookOutline
  dynamic chunks + overlap reconciliation
  retype / heading hierarchy / relations
           |
           v
[M9 optional visual arbitration]
  source-page/crop evidence
  ambiguous semantic decisions
  OPTIONAL OCR correction (default OFF)
           |
           v
[Semantic BookIR + outline/state]
           |
           v
[existing deterministic normalize, amended]
           |
           v
[M10a presentation-profile resolution]
  legacy | enhanced | infer
  resolve BookStyleProfile / finite design tokens
           |
           v
[M11 typography/list normalization]
  Japanese/Latin spacing, punctuation, list markers
  may consume BookStyleProfile paragraph-indent intent
           |
           v
[M10b deterministic component renderer + CSS generator]
  semantic component + BookStyleProfile -> XHTML/CSS
           |
           v
[existing native EPUB packaging + EPUBCheck]
           |
           v
[M12 semantic/presentation QA]
```

## 3. Explicitly rejected architecture

Do not implement:

- permanent MinerU+PaddleOCR ensemble;
- MinerU-Popo as required runtime package/service;
- whole book -> frontier VLM -> regenerated EPUB;
- LLM-written final Markdown/XHTML/CSS;
- fixed-layout primary EPUB;
- scanned-page background + OCR overlay;
- arbitrary absolute positioning;
- mandatory cloud processing;
- WSL/Docker requirement.

## 4. Why MinerU remains the perception layer

MinerU is retained as the page/document perception system because M0-M5 already preserve its detailed `middle.json` provenance and assets. The new system addresses a different failure mode: **local classification is not equal to book-level semantic interpretation**.

Example:

```text
preceding prose: “次のコマンドを実行すると、以下の出力になります。”
MinerU block: table
content: shell-like aligned text
```

M8 may reclassify this to `terminal_output` without changing the characters.

## 5. MinerU-Popo adoption policy

Adopt the following design ideas:

- document-level postprocessing after page perception;
- cross-page semantic reasoning;
- heading hierarchy reconstruction;
- image/text relation reasoning;
- dynamic chunking rather than one uncontrolled whole-book prompt;
- overlap/synchronization across chunks.

Do not import/run MinerU-Popo itself in M6-M12.

## 6. Three IR layers

### 6.1 Raw BookIR

Existing adapter output. It represents MinerU’s best first interpretation.

### 6.2 SemanticEvidence / SemanticDraft

A non-rendering evidence representation that preserves alternative views before a type is final:

```text
block id
page / bbox
MinerU source type
current Raw BookIR kind
plain text
preformatted line text
structured table HTML availability
asset/caption/note evidence
source span/line references
content hashes
allowed semantic targets
context pointers
```

This layer is mandatory when semantic processing is enabled.

### 6.3 Semantic BookIR

Raw BookIR after validated structural decisions. It remains a flat source-order block list for compatibility, with parallel `BookOutline` and `BookState` metadata.

## 7. Semantic authority boundaries

The semantic reviewer may determine:

- block semantic type;
- preformatted subtype;
- heading level;
- list/callout/quote/example interpretation;
- relationships such as caption/note attachment when source evidence supports it;
- uncertainty/confidence.

It may not:

- rewrite arbitrary prose;
- invent table cells;
- invent code or commands;
- generate missing captions;
- rewrite math;
- translate content;
- make final CSS/XHTML.

## 8. OCR correction boundary

OCR correction is a **separate feature**:

```text
off  = immutable source text (default)
safe = visual-evidence-gated prose-like local corrections
all  = additionally permits sensitive non-math textual blocks under stricter double validation
```

Even `all` does not alter LaTeX/math in M6-M12.

No OCR correction can occur from text context alone. The original page/crop must be available to a vision-capable provider.

## 9. BookState

BookState is a compact, auditable document-level memory, not free-form hidden model memory.

It contains observed patterns such as:

- heading numbering/style patterns;
- known section hierarchy;
- code languages observed in source;
- shell/REPL conventions;
- recurring callout visual signatures;
- figure/table/listing numbering patterns;
- observed glossary/domain terms;
- visual component conventions.

It is serialized to JSON and supplied to later chunks as bounded context.

BookState never authorizes text changes.

## 10. BookOutline

Keep `BookIR.blocks` flat. Add a separate logical tree:

```text
BookOutline
  -> chapter nodes
     -> section nodes
        -> subsection nodes
```

Each outline node refers to existing heading/block ids. It does not duplicate book text.

Renderer splitting/TOC should use outline when semantic mode produced a valid outline; legacy mode retains existing heading-driven behavior.

## 11. Presentation architecture

Presentation is not raw CSS inference.

```text
semantic component
      +
source visual evidence
      +
BookStyleProfile
      |
      v
finite presentation tokens
      |
      v
deterministic component renderer / CSS generator
```

Modes:

- `legacy`: use current M3 CSS/render behavior as compatibility path;
- `enhanced`: richer fixed Book2Epub component theme, no model style inference;
- `infer`: vision model examines deterministic representative pages and selects a finite `BookStyleProfile`; on inference failure, fall back to `enhanced`.

The model cannot emit CSS strings.

## 12. Component vocabulary

M6-M10 may add at least:

```text
Paragraph
Heading
PreformattedBlock
  source_code
  shell_command
  terminal_output
  terminal_session
  repl_session
  log_output
  config_file
  generic_preformatted
Callout
  note | tip | warning | caution | important | sidebar
BlockQuote
DefinitionList
ExampleBlock
ExerciseBlock
ListBlock
Table
Figure
Chart
DisplayMath
Footnote
IndexBlock
```

Existing `CodeBlock` remains accepted for backward compatibility; semantic mode may normalize it into richer component semantics where appropriate.

## 13. Japanese typography principle

Do not ask an LLM to “make the Japanese spacing natural.” M11 uses source segment/bbox evidence and deterministic rules.

The enhanced pipeline distinguishes:

- a real source-space observed within a line;
- a space inserted only because two OCR spans/lines were joined;
- a line-wrap boundary;
- Japanese punctuation/bracket boundaries;
- code/preformatted text, which is excluded from prose normalization.

## 14. Provider abstraction

Supported M7 providers:

```text
ollama     local
openai     cloud; explicit allow-cloud
google    cloud via Google Gemini / AI Studio API; explicit allow-cloud
anthropic  cloud; explicit allow-cloud
```

No provider framework such as LangChain/LiteLLM is required. Use thin direct adapters.

Provider models are configurable. Frozen recommended quality defaults are documented in Appendix G, but the user may set another model string.

## 15. Structured Outputs rule

Every provider call that affects structure/style/correction must request schema-constrained JSON using the provider’s native feature and then validate with the same Pydantic model locally.

A provider response that parses as JSON but fails the Pydantic model is a failed call, not “best effort”.

## 16. Cloud privacy

Cloud use is always explicit.

- OpenAI: `store=False`.
- Google Interactions API: `store=False`.
- Anthropic: no Book2Epub server-side conversation/file reuse; send request-scoped base64 images only.
- no uploaded Files API persistence for M6-M12.
- provider usage logs store request hashes and token/usage metadata, not API credentials.

## 17. Caching

Add stage caches independent of MinerU cache:

```text
semantic evidence
semantic outline/state
semantic decisions
visual arbitration
ocr correction
presentation profile
render
```

A change to style profile must not invalidate MinerU or semantic perception. A change to semantic decisions invalidates presentation/render/package/QA.

Cache keys must include provider/model/schema/prompt contract version and relevant source hashes.

## 18. Final quality priorities

1. no invented/lost technical content;
2. correct reading order and semantic classification;
3. correct section hierarchy;
4. code/terminal/table/math fidelity;
5. readable EPUB-reader-compatible presentation;
6. natural Japanese/Latin spacing and list rendering;
7. source visual grammar translated into reflow-safe styles;
8. speed/cost.
