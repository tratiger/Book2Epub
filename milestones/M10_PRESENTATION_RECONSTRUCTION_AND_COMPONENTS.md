# M10 — Presentation Reconstruction, BookStyleProfile, and Component Renderer

## Objective

Solve the current “valid EPUB but visually hard to read” limitation. Translate the source book’s **visual grammar** into reflow-safe deterministic XHTML/CSS without copying fixed page coordinates.

M10 introduces:

- presentation modes `legacy`, `enhanced`, `infer`;
- `BookStyleProfile` made only of finite tokens;
- a richer technical-book component renderer;
- deterministic CSS generation from profile tokens.

An LLM/VLM may select presentation tokens in `infer` mode, but may never return CSS/HTML.

## 1. Required modules

```text
src/book2epub/presentation/
  __init__.py
  models.py
  defaults.py
  infer.py
  representative_pages.py
  css_tokens.py
  css_generator.py
  stage.py
src/book2epub/render/components/
  __init__.py
  base.py
  headings.py
  prose.py
  preformatted.py
  callouts.py
  lists.py
  tables.py
  figures.py
  quotes.py
  containers.py
  renderer.py
```

Preserve existing `src/book2epub/render/xhtml.py` as the legacy path until M12 confirms compatibility. Do not rewrite it in place and risk default behavior.

## 2. Presentation modes

### `legacy`

- use current `DocumentRenderer` and current `BOOK_CSS_CONTENT` for pre-M6 block types;
- no style inference;
- no presentation provider call;
- compatibility target for pre-M6 behavior.

When semantic reconstruction is enabled, M8 may legitimately create new semantic component types that the pre-M6 `DocumentRenderer` does not understand. Legacy presentation therefore requires a **minimal semantic compatibility bridge**, but it must not activate the enhanced theme.

Required legacy mappings:

```text
PreformattedBlock -> selectable <pre>/<code> using existing generic pre styling
Callout           -> existing conservative <aside class="aside ..."> styling
BlockQuote        -> semantic <blockquote> with no new theme dependency
DefinitionList    -> <dl>/<dt>/<dd> with reader/default conservative styling
ExampleBlock      -> normal-flow <section class="example">; recursively render children
ExerciseBlock     -> normal-flow <section class="exercise">; recursively render children
```

Implement this either as `LegacySemanticBridge` before `DocumentRenderer` or as narrowly scoped new branches in the legacy renderer. **Do not** coerce terminal/config/log text back into a Table, Paragraph, or invented CodeBlock text. The user-visible characters must remain the exact materialized semantic content.

Regression requirement: when `semantic=false`, `ocr=off`, `presentation=legacy`, these branches are never exercised and existing M0-M5 output behavior remains the compatibility target.

### `enhanced`

- use new component renderer;
- use fixed `DEFAULT_ENHANCED_PROFILE`;
- no style model call;
- suitable for users wanting a consistently readable book without cloud/local VLM presentation inference.

### `infer`

- require source visual evidence + vision-capable configured provider;
- does **not** require semantic reconstruction to be enabled; `--presentation infer --no-semantic` is valid;
- infer finite BookStyleProfile from representative source pages;
- validate it;
- render using the same component renderer/CSS generator as enhanced;
- if style inference fails semantically/schema-wise after provider retry, fall back to `enhanced` and issue high-visibility QA warning `STYLE_INFERENCE_FALLBACK` rather than failing the entire conversion.

Cloud gating from M7 still applies.

## 3. BookStyleProfile schema

No arbitrary strings except profile metadata/provider identifiers. All visual choices are enums.

```text
BookStyleProfile
  schema_version = "1.0"
  body: BodyStyle
  headings: HeadingStyles
  inline_code: InlineCodeStyle
  source_code: PreStyle
  terminal: PreStyle
  log: PreStyle
  config: PreStyle
  callout: CalloutStyles
  table: TableStyle
  figure: FigureStyle
  list: ListStyle
  quote: QuoteStyle
```

### 3.1 BodyStyle

```text
page_margin: compact | standard | generous
line_height: compact | normal | relaxed
paragraph_gap: none | tight | normal | open
first_line_indent: none | small | medium
text_align: start | justify
```

Token mapping:

```text
page_margin:
  compact   -> 3%
  standard  -> 5%
  generous  -> 8%

line_height:
  compact   -> 1.40
  normal    -> 1.55
  relaxed   -> 1.70

paragraph_gap (margin-block):
  none      -> 0
  tight     -> 0.35em
  normal    -> 0.65em
  open      -> 1.0em

first_line_indent:
  none      -> 0
  small     -> 1em
  medium    -> 2em
```

Default enhanced body:

```text
standard / normal / normal / none / start
```

For Japanese books, `start` is safer than forced justification across readers; `infer` may choose justify only when source strongly uses book-style justification.

### 3.2 HeadingStyle

For levels 1-4 individually, levels 5-6 share minor style.

```text
scale: s | m | l | xl | xxl
weight: semibold | bold
alignment: start | center
rule: none | bottom_thin | bottom_medium | accent_left
space_before: m | l | xl | xxl
space_after: s | m | l | xl
chapter_break_before: bool   # effective only for h1
```

Suggested rem scale map:

```text
s=1.05, m=1.20, l=1.40, xl=1.70, xxl=2.00
```

Rule implementation uses border/padding, not pseudo-element absolute positioning.

Default enhanced:

```text
h1: xxl bold start none xxl xl, chapter break true
h2: xl  bold start bottom_thin xl m
h3: l   bold start none l m
h4: m   semibold start none l s
h5-6: s semibold start none m s
```

This specifically addresses source books where section headings have a horizontal rule.

### 3.3 PreStyle

```text
theme: plain | subtle | dark | outline
border: none | thin | accent_left
padding: s | m | l
radius: none | small
font_scale: small | normal
line_height: compact | normal
wrap: soft | preserve
```

Mapping:

```text
padding s=.55em, m=.85em, l=1.10em
radius small=4px
font_scale small=.88em, normal=.95em
line_height compact=1.30, normal=1.45
```

`soft` -> `white-space: pre-wrap; overflow-wrap: break-word;`  
`preserve` -> `white-space: pre; overflow-x: auto;` only when reader behavior is acceptable; enhanced default uses `soft` for mobile compatibility.

Default enhanced source-code:

```text
subtle / accent_left / m / small / small / compact / soft
```

Default enhanced terminal:

```text
outline / thin / m / small / small / compact / soft
```

Do not force dark terminal theme as default because reader dark-mode/color overrides vary.

### 3.4 InlineCodeStyle

```text
background: none | subtle
border: none | thin
padding: none | xs
font_scale: normal | small
```

### 3.5 Callout style

Per semantic subtype can choose:

```text
variant: plain | accent_left | boxed
accent: neutral | blue | teal | amber | red
spacing: tight | normal | open
show_label: bool
```

Renderer may add localized labels (`Note`, `Warning`, etc.) **only if the source/semantic structure has an explicit callout type and the label is presentation chrome**, not source book text. To avoid altering publication content by default, `show_label=false` in enhanced profile.

### 3.6 TableStyle

```text
rules: full | horizontal | minimal
header_emphasis: none | subtle | strong
cell_padding: compact | normal | generous
font_scale: small | normal
caption_align: start | center
```

Do not use CSS Grid for tables.

### 3.7 FigureStyle

```text
spacing: tight | normal | open
caption_align: start | center
caption_scale: small | normal
caption_position: after | before
```

Respect semantic order/source caption relation. `caption_position` may only affect DOM placement when source relation does not explicitly determine position; default after.

### 3.8 ListStyle

```text
item_spacing: compact | normal | open
indent: compact | normal | generous
unordered_marker: disc | circle | square | dash
ordered_marker: decimal | lower_alpha | lower_roman
```

M11 ensures source marker text is not duplicated.

### 3.9 QuoteStyle

```text
variant: indent | accent_left | boxed
font_style: normal | italic
spacing: normal | open
```

## 4. Style inference input selection

Select representative pages deterministically from current Semantic BookIR + source pages.

Maximum default `max_style_pages=8`.

Priority slots, each page chosen at most once:

1. first page containing level-1 heading;
2. page containing level-2/3 heading;
3. page containing source code;
4. page containing terminal/preformatted content;
5. page containing a table;
6. page containing a figure/chart;
7. page containing list/callout/sidebar;
8. ordinary prose page near middle of book.

If fewer categories exist, fill remaining slots by evenly distributed source pages, excluding cover-only/blank pages when deterministically known.

Use full-page raster longest edge <= 1600 px. No OCR crop is needed for style inference unless provider input-size constraints require it.

Write selection to:

```text
presentation/style-pages.json
```

## 5. Style inference Structured Output

Response is exactly `BookStyleProfile` plus confidence metadata:

```text
StyleInferenceResult
  profile: BookStyleProfile
  confidence: float
  evidence_page_indices: list[int]
  uncertainty_codes: list[StyleUncertaintyCode]
```

No fields:

```text
css
html
color_hex
font_file
font_family_guess
absolute_position
pixel_margin
raw_style
```

System prompt says:

- infer visual grammar, not pixel-perfect layout;
- select only schema enums;
- favor reader-safe styles;
- distinguish heading hierarchy, prose rhythm, preformatted blocks, callouts, tables and captions;
- do not alter semantic structure;
- do not output text from the book.

The local validator verifies all page indices were actually supplied.

## 6. Profile confidence/fallback

- confidence >= 0.70 -> use inferred profile;
- confidence < 0.70 -> use enhanced default and record fallback;
- provider failure after normal M7 retries -> enhanced fallback;
- schema failure -> enhanced fallback.

Do not fail a successfully semantically reconstructed book merely because style inference failed.

## 7. Component renderer

Create `ComponentDocumentRenderer` for enhanced/infer.

Document skeleton/pagebreak/math primitives can reuse existing tested helpers, but block rendering delegates to component functions/classes.

Required mapping:

```text
Heading              -> heading component classes by level/profile
Paragraph            -> body paragraph
CodeBlock             -> source-code component (legacy compatibility semantic)
PreformattedBlock:
  source_code        -> source-code
  shell_command      -> shell-command
  terminal_output    -> terminal-output
  terminal_session   -> terminal-session
  repl_session       -> repl-session
  log_output         -> log-output
  config_file        -> config-file
  generic            -> generic-preformatted
Callout               -> callout subtype component
Aside                  -> sidebar compatibility component
BlockQuote             -> blockquote
DefinitionList         -> dl/dt/dd
ExampleBlock            -> section/div semantic example container
ExerciseBlock           -> section/div exercise container
ListBlock               -> ul/ol
Table                   -> semantic HTML table wrapper
Figure/Chart            -> figure/figcaption/img
Math                    -> current MathML renderer
Footnote                -> current footnote semantics
Index                    -> current index semantics
```

## 8. XHTML semantics

Use semantic HTML/EPUB elements wherever possible:

- headings remain h1-h6;
- source/terminal/log/config remain selectable text in `<pre><code>` or `<pre>`;
- block quote uses `<blockquote>`;
- definition list uses `<dl><dt><dd>`;
- callout uses `<aside>` with classes;
- Example/Exercise use `<section>`/`<div>` in normal flow;
- table stays `<table>`;
- no visual component becomes a screenshot when semantic text exists.

## 9. CSS generation

`generate_book_css(profile)` is pure/deterministic.

Rules:

- no `position:absolute`;
- no fixed source-page dimensions;
- no JS;
- no remote styles/fonts;
- no CSS emitted by provider;
- no inline style attributes; stable classes only;
- images always `max-width:100%; height:auto`;
- use `break-inside: avoid` only as a hint on compact components;
- long code remains usable on narrow screens;
- body left/right margin respects profile;
- explicit paragraph and heading vertical rhythm;
- heading borders/rules use `border-bottom`/`border-left` only.

Generated CSS goes to current:

```text
OEBPS/styles/book.css
```

and profile to:

```text
presentation/book-style-profile.json
```

## 10. Recommended enhanced CSS behavior

At minimum generated enhanced CSS must provide deliberate rules for:

```text
body
p + p
h1..h6
pre/code
.inline-code
.source-code
.shell-command
.terminal-output
.terminal-session
.repl-session
.log-output
.config-file
.callout-* 
blockquote
dl/dt/dd
ul/ol/li
figure/figcaption
table/th/td/caption
footnotes
math
```

This is substantially richer than current single generic `pre` style.

## 11. Existing renderer integration

Amend `ReflowRenderer` constructor to receive `PresentationConfig` and optional `BookStyleProfile`.

Selection:

```python
if presentation.mode == "legacy":
    renderer = existing DocumentRenderer
    css = BOOK_CSS_CONTENT
else:
    renderer = ComponentDocumentRenderer
    css = generate_book_css(profile)
```

Do not change legacy CSS constant while proving compatibility.

RenderResult/manifest additions, backward-compatible defaults:

```text
presentation_mode
style_profile_hash
component_counts: dict[str,int]
```

## 12. Nested components

Component renderer must recursively render `Callout.blocks`, `ExampleBlock.blocks`, `ExerciseBlock.blocks`, but enforce:

- no recursive cycles;
- max nesting depth 8;
- pagebreak inside a container remains semantically reachable;
- heading inside callout/example does not automatically become top-level TOC unless its semantic heading level says it should and policy permits; v1 default excludes container-internal headings from nav unless they existed as normal source headings.

## 13. Accessibility

- do not invent descriptive alt text;
- preserve current empty-alt warning behavior for figures without descriptions;
- callout color is never the sole semantic cue: subtype classes/borders and semantic `<aside>` remain;
- code/preformatted stays selectable;
- contrast for finite palette CSS should remain reasonable in default theme;
- do not hide source text visually to mimic design.

## 14. Tests

Profile tests:

- every enum maps to deterministic CSS;
- invalid provider raw CSS field rejected by schema;
- profile hash deterministic;
- infer confidence low -> enhanced fallback;
- representative page selection deterministic and <=8.

Renderer tests:

- h2 `bottom_thin` emits class/CSS border-bottom;
- paragraph line-height/gap tokens apply;
- code and terminal get different classes/styles;
- terminal remains text, not table/image;
- callout subtype maps to aside class;
- definition list maps dl/dt/dd;
- no inline style;
- no absolute positioning;
- EPUB standalone XHTML passes checker as before;
- legacy renderer output remains on old CSS/component path.

Visual regression-style structural test:

Compare generated XHTML/CSS tokens, not screenshots, to avoid fragile reader-specific pixel tests.

## 15. Acceptance gate

M10 complete when:

- legacy mode passes existing renderer/E2E contracts;
- enhanced mode visibly/structurally has distinct heading rhythm, code/terminal treatments, callouts and lists;
- infer mode uses only finite profile schema and falls back safely;
- no model-generated CSS/HTML is ever executed/emitted;
- ruff/mypy/pytest pass.
