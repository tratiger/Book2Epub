# Appendix L — Presentation Profile, Components, and Deterministic CSS Catalog

This appendix is normative for M10. The purpose is to obtain high visual expressiveness without letting an LLM write CSS/XHTML.

## L1. Presentation modes

```text
legacy
  -> current M0-M5 CSS/render behavior as closely as possible

enhanced
  -> fixed high-quality Book2Epub profile; no model required

infer
  -> VLM selects finite BookStyleProfile from representative source pages;
     Python validates it and renders deterministic CSS;
     inference failure falls back to enhanced
```

`presentation=infer` requires semantic evidence/source visual access and a vision-capable configured provider. It does **not** require `semantic.enabled=true`; style inference is an independent feature. The provider/model settings are shared through `SemanticConfig` for CLI/config compatibility. Cloud gating remains required.

## L2. BookStyleProfile

Use exactly the schema/token families in M10. No arbitrary CSS values, free colors, font family names, or pixel coordinates.

```text
body
headings h1..h4 + minor h5/h6
inline_code
source_code
terminal
log
config
callout by subtype
table
figure
list
quote
```

Profile metadata may include:

```text
schema_version
mode_source: enhanced_default | inferred
provider/model/request_id | null
confidence: 0..1
representative_page_indices
```

## L3. Color policy

EPUB readers frequently override colors/dark mode. Use a minimal semantic palette based on CSS named/hex values controlled by Book2Epub, never arbitrary VLM colors.

Frozen palette tokens:

```text
text             = currentColor
subtle_bg        = #f5f5f5
subtle_border    = #d6d6d6
neutral_accent   = #6b7280
blue_accent      = #2563eb
teal_accent      = #0f766e
amber_accent     = #b45309
red_accent       = #b91c1c
```

Do not make text readable only because of color. Borders/labels/semantic elements must convey type.

Avoid forcing white/black body backgrounds.

## L4. Body token map

```text
page_margin:
  compact   -> body margin-inline: 3%
  standard  -> 5%
  generous  -> 8%

line_height:
  compact   -> 1.40
  normal    -> 1.55
  relaxed   -> 1.70

paragraph_gap:
  none      -> margin-block: 0
  tight     -> .35em
  normal    -> .65em
  open      -> 1em

first_line_indent:
  none      -> 0
  small     -> 1em
  medium    -> 2em
```

For `text_align=justify`, emit `text-align: justify; text-justify: inter-character;` only if the EPUB/XHTML validator tests accept it; otherwise use `text-align:justify` without relying on `text-justify`. `start` is the enhanced Japanese default.

## L5. Heading component mapping

Semantic:

```text
Heading(level=1..6)
```

XHTML:

```html
<h1 class="heading heading-1 ...">...</h1>
```

No inline style.

Scale map:

```text
s   1.05em
m   1.20em
l   1.40em
xl  1.70em
xxl 2.00em
```

Weight:

```text
semibold 600
bold     700
```

Rules:

```text
none:
  no border

bottom_thin:
  border-bottom: .06em solid currentColor
  padding-bottom: .22em

bottom_medium:
  border-bottom: .10em solid currentColor
  padding-bottom: .25em

accent_left:
  border-left: .20em solid currentColor
  padding-left: .45em
```

Spacing:

```text
before m=.9em l=1.3em xl=1.8em xxl=2.4em
after  s=.35em m=.65em l=.95em xl=1.3em
```

`chapter_break_before=true` -> `break-before: page` as progressive enhancement. Reading systems may ignore it; content remains valid.

Enhanced defaults are exactly those in M10.

## L6. Preformatted component catalog

Semantic subtype -> class:

```text
source_code          -> source-code
shell_command        -> shell-command
terminal_output      -> terminal-output
terminal_session     -> terminal-session
repl_session         -> repl-session
log_output           -> log-output
config_file          -> config-file
generic_preformatted -> generic-preformatted
```

XHTML baseline:

```html
<pre class="preformatted terminal-output"><code>...</code></pre>
```

Use `<code>` for source_code/shell/config where appropriate; terminal/log may still use `<code>` for monospace semantics. Never turn preformatted text into a table to obtain columns.

Token map:

```text
theme plain:
  background transparent

theme subtle:
  background #f5f5f5

theme outline:
  background transparent
  border-color #d6d6d6

theme dark:
  background #202124
  color #f2f2f2
  (allowed but never enhanced default; reader overrides may reduce reliability)

border thin:
  1px solid #d6d6d6

border accent_left:
  border-left .22em solid currentColor

padding s=.55em m=.85em l=1.10em
radius small=4px
font_scale small=.88em normal=.95em
line_height compact=1.30 normal=1.45
```

Wrap:

```text
soft     -> white-space:pre-wrap; overflow-wrap:break-word;
preserve -> white-space:pre; overflow-x:auto;
```

Enhanced defaults:

```text
source_code: subtle/accent_left/m/small/small/compact/soft
terminal:    outline/thin/m/small/small/compact/soft
log:         plain/thin/s/small/small/compact/soft
config:      subtle/thin/m/small/small/compact/soft
```

Do not create syntax-highlight spans in M10.

## L7. Inline code

```html
<code class="inline-code">...</code>
```

Enhanced:

```text
background subtle
border none
padding xs -> .12em .28em
font_scale small -> .92em
border-radius 3px
```

Do not add inline-code markup unless BookIR has explicit inline-code semantics. M10 does not infer it from punctuation.

## L8. Callouts

Semantic components:

```text
note
tip
warning
caution
important
sidebar
```

XHTML:

```html
<aside class="callout callout-warning">...</aside>
```

Variants:

```text
plain       -> spacing only
accent_left -> left border + padding
boxed       -> full thin border + padding
```

Accent tokens use frozen palette. Warning/caution may default amber/red but color is not sole cue.

`show_label=false` enhanced default. If true in inferred profile, the renderer may add a localized chrome label only because semantic subtype is already explicit. The label is marked as presentation chrome and is not included in extracted source-text fidelity checks.

## L9. Tables

XHTML remains semantic `<table>`. Presentation never rasterizes a valid table.

Rules:

```text
full:
  cell borders all sides
horizontal:
  horizontal row rules, minimal vertical rules
minimal:
  no grid, header/bottom rules only
```

Header emphasis:

```text
none
subtle -> font-weight:600; background:#f5f5f5
strong -> font-weight:700; border-bottom:.12em solid currentColor
```

Cell padding:

```text
compact .20em .30em
normal  .35em .50em
generous .55em .70em
```

All tables remain within `.table-wrap` with horizontal overflow as progressive enhancement.

## L10. Figures/captions

Classes:

```text
figure
figure-image
figure-caption
```

Respect M0-M5 responsive width classes. Presentation style adjusts margins/caption typography only.

Spacing:

```text
tight .8em
normal 1.2em
open 1.8em
```

Caption scale:

```text
small .88em
normal .95em
```

Caption position does not override an explicit source relation.

## L11. Lists

M11 extracts literal OCR marker text. M10 decides presentation marker style.

Indent:

```text
compact 1.2em
normal  1.8em
generous 2.4em
```

Item spacing:

```text
compact .15em
normal  .35em
open    .65em
```

Native list markers preferred for disc/circle/square/decimal/lower-alpha/lower-roman.

For `dash`, use:

```html
<ul class="list list-dash">
  <li><span class="list-marker" aria-hidden="true">–</span><span class="list-content">...</span></li>
</ul>
```

with `list-style:none`; do not combine native marker and explicit dash.

## L12. Quotes

```html
<blockquote class="quote quote-accent-left">...</blockquote>
```

Variants:

```text
indent       margin-inline:1.5em
accent_left  border-left:.18em solid currentColor; padding-left:.8em
boxed        border:1px solid #d6d6d6; padding:.8em
```

Italic is optional token, not automatic for Japanese quotes.

## L13. Examples/exercises

Semantic ExampleBlock/ExerciseBlock rendered as `<section>` or `<div>` with component classes, never as a fake heading unless a real heading exists.

```html
<section class="example">...</section>
<section class="exercise">...</section>
```

No generated “Example”/“Exercise” title unless presentation chrome is explicitly enabled by a future profile field; v1 does not add one.

## L14. Representative-page selection for infer

Maximum 8 pages, deterministic priority:

1. h1 page;
2. h2/h3 page;
3. source code;
4. terminal/preformatted;
5. table;
6. figure/chart;
7. list/callout/sidebar;
8. ordinary prose near median page.

Deduplicate pages. Fill missing slots by evenly distributed ordinary source pages. Exclude blank/cover-only when known.

Full-page raster longest edge <=1600px.

## L15. Inference result schema

```python
class BookStyleProfileDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    profile: BookStyleProfile
    confidence: float = Field(ge=0, le=1)
    evidence_page_indices: list[int]
```

No CSS/HTML/free colors/font names in schema.

Application:

```text
confidence >= .70 -> use inferred profile
confidence < .70 -> enhanced profile
provider failure -> enhanced profile + QA warning
```

Do not fail the whole EPUB solely because style inference failed.

## L16. CSS generation

Generate CSS from token lookup tables only. One deterministic generator function accepts a validated profile and returns UTF-8 CSS.

Requirements:

- stable property ordering;
- no inline styles in XHTML;
- no `position:absolute`;
- no CSS Grid dependency;
- no external fonts;
- no JavaScript;
- all components readable with CSS partially ignored;
- no source page dimensions.

Write profile and generated CSS hash into `presentation/book-style-profile.json` and render manifest QA metadata.

## L17. Legacy separation

`presentation=legacy` MUST continue to use current `BOOK_CSS_CONTENT` and current renderer class structure unless a semantic component requires a minimal backward-compatible rendering rule.

Do not silently make enhanced typography the default during M10.
