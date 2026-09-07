# M3 - Semantic Reflow XHTML/MathML Renderer

## Objective

Render normalized BookIR into standards-oriented, ordinary reflowable XHTML content documents and CSS. This milestone creates an unpacked publication tree, not the `.epub` ZIP yet.

## Primary rendering rule

The renderer follows normal document flow. It MUST NOT recreate print coordinates.

Forbidden CSS/features:

- `position:absolute` for source layout;
- fixed source-page width/height;
- page background images;
- transparent OCR layers;
- CSS multi-column recreation of printed columns;
- JavaScript;
- remote fonts/styles/scripts/images;
- MathJax or any script-based math rendering.

## XHTML namespace contract

Every content document is XML-serializable XHTML with:

```xml
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="..."
      lang="...">
```

Use XML serialization, UTF-8, and escape text/attribute content. Do not generate HTML by concatenating unescaped OCR strings.

## Semantic mapping

### Heading

- level 1..6 -> `h1`..`h6`.
- missing level -> `h2` plus QA warning class/record; do not show a visible warning in user text.
- every heading gets stable id `h-<global-sequence>-<slug-fragment>`.
- TOC source uses these heading nodes.

### Paragraph

`<p>` with inline children.

A PageBoundary inside a paragraph becomes an empty semantic pagebreak span placed exactly at that inline position:

```xml
<span id="page-137" epub:type="pagebreak" role="doc-pagebreak" aria-label="137"/>
```

If multiple source pages have no printed label, use unique ids `scan-page-000137` and label `scan-137`.

### InlineMath / DisplayMath

Preferred path is MathML.

Use `latex2mathml==3.81.0`:

```python
latex2mathml.converter.convert(latex, display="inline")
latex2mathml.converter.convert(latex, display="block")
```

Parse the result as XML before inserting it. It must use MathML namespace `http://www.w3.org/1998/Math/MathML`.

For display math, wrap in `<div class="math display">`; inline math stays inline.

Do not emit TeX dollar delimiters around successful MathML.

Fallback order on conversion failure:

1. MinerU equation fallback image if available -> `<img class="math-fallback" ...>` with alt set to normalized LaTeX;
2. if no image, render escaped LaTeX in `<code class="math-unconverted">` and add a high-severity QA warning.

Never call a network math service.

Every XHTML manifest item containing MathML must later be marked with package manifest property `mathml`.

### CodeBlock

Use:

```xml
<figure class="code-listing">   <!-- only when caption/footnote exists -->
  <figcaption>...</figcaption>
  <pre><code>...</code></pre>
  ...footnote...
</figure>
```

Without caption/footnote, `pre/code` is sufficient.

Do not syntax-highlight with generated spans in v1. Do not infer language unless IR provides it. If language exists, class may be `language-python` etc after sanitizing to `[a-z0-9_+-]+`.

Code text must preserve newlines and indentation.

### Figure / Chart

Use `<figure>` + `<img>` + `<figcaption>`.

- image src points to an internal EPUB asset path;
- `alt` is caption plain text if caption is genuinely descriptive;
- if no caption/description, use `alt=""` and record accessibility warning rather than inventing alt text;
- footnotes follow figcaption in a small semantic `<div class="figure-note">`.

Apply size and alignment classes only:

```text
figure size-small align-left
figure size-medium align-center
figure size-large align-right
```

No float. Text never wraps around figure in v1.

### Table

Structured table is preferred whenever normalized HTML exists.

Renderer creates:

```xml
<figure class="table-figure ...">
  <figcaption>...</figcaption>
  <div class="table-wrap">
    <table>...</table>
  </div>
  <div class="table-note">...</div>
</figure>
```

Do not include `<html><body>` wrappers from MinerU.

If no valid structured table and fallback image exists, render a figure containing the table image and caption/notes.

Do not rasterize a valid table just because it is wide.

### List

- ordered true -> `<ol>`;
- ordered false -> `<ul>`;
- unknown -> `<ul class="list-marker-preserved">`, preserving original item prefix text.

Nested lists are rendered only when IR explicitly contains nesting; do not infer nesting from horizontal bbox offset in v1.

### Aside

Use `<aside>` in normal flow. Do not position beside the paragraph. Use subtype classes.

### Page footnote

If a reliable in-text reference target is unavailable, preserve page footnote content near the page boundary as:

```xml
<aside epub:type="footnote" class="page-footnote">...</aside>
```

Do not invent backlink/reference IDs.

### Index

Render with `epub:type="index"` when structurally appropriate and preserve entries. Cross-reference links are emitted only when explicit anchors/targets exist.

### UnknownBlock

Strict rendering policy:

- if it has extracted text, render `<div class="unknown-block">` with the text and a QA warning;
- if it has an asset, render as generic figure only if semantic loss is otherwise worse;
- if it has neither, omit from user content but retain QA record.

## Document splitting

The output must not be one giant XHTML file.

Deterministic split algorithm:

1. content before first level-1 heading -> `frontmatter.xhtml` if non-empty;
2. every level-1 heading starts a new content document;
3. if a document exceeds either 100,000 rendered text characters OR spans more than 50 source pages, split before the nearest preceding level-2 heading that keeps both sides non-empty;
4. if no suitable level-2 heading exists, split at a block boundary immediately before the threshold would be exceeded;
5. never split inside code, figure, table, math, list item, or paragraph;
6. a PageBoundary inside a paragraph remains inside that paragraph and cannot be chosen as an arbitrary file split point.

Files are named `text/part-0001.xhtml`, etc.

## Source page navigation

Create a renderer-side PageMap with:

```text
page_idx
label
xhtml_path
fragment_id
printed_label_confidence
```

The EPUB writer uses this for nav `page-list`.

Every source page receives a destination, even if printed label is unknown.

At a normal block boundary, insert pagebreak span before the first rendered block sourced from that page. When a cross-page paragraph merge moved the boundary inside a paragraph, use the inline PageBoundary.

## Table of contents

Build a logical heading tree from levels.

Rules:

- include levels 1-3 in navigation by default;
- preserve deeper headings in XHTML but do not crowd nav unless config changes;
- if heading levels jump (h1 -> h3), create nav nesting only under the nearest existing shallower level; do not invent a visible heading;
- if there are no headings at all, create a single TOC entry using book title to the first content document.

## CSS contract

Create one `styles/book.css` with conservative reader-compatible styles.

Required base properties include:

```css
html { line-height: 1.5; }
body { margin: 0 5%; }
img { max-width: 100%; height: auto; }
figure { margin: 1.2em auto; break-inside: avoid; }
figcaption { font-size: 0.9em; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
code { font-family: monospace; }
table { border-collapse: collapse; max-width: 100%; }
th, td { vertical-align: top; padding: 0.25em 0.4em; }
.table-wrap { max-width: 100%; overflow-x: auto; }
.math.display { text-align: center; margin: 1em 0; }
.size-small { width: 36%; max-width: 100%; }
.size-medium { width: 72%; max-width: 100%; }
.size-large { width: 100%; }
.align-left { margin-left: 0; margin-right: auto; }
.align-center { margin-left: auto; margin-right: auto; }
.align-right { margin-left: auto; margin-right: 0; }
```

Add a narrow-screen media query that promotes small/medium figures to `width:100%` below approximately 40em. The exact threshold is fixed in code/config, not reader-specific JS.

Do not embed proprietary fonts in v1.

## Metadata inference needed before packaging

Renderer/normalizer must make final metadata available:

### Title

Priority:

1. explicit CLI title;
2. first level-1 heading text;
3. input directory basename.

### Language

Priority:

1. explicit BCP 47 CLI value;
2. deterministic text heuristic over first 10,000 letters:
   - if Japanese kana is significant or CJK with Japanese kana -> `ja`;
   - predominantly ASCII/Latin -> `en`;
   - otherwise `und`.

Never call language-detection service.

### Identifier

Explicit identifier else generate UUID4 as `urn:uuid:<uuid>` and persist it in job metadata so rerender of same job reuses the identifier.

## Unpacked render tree

M3 writes:

```text
render/OEBPS/
  text/*.xhtml
  styles/book.css
  images/*
  render-manifest.json
```

Do not create package.opf/nav/container/mimetype yet; M4 owns those.

`render-manifest.json` records XHTML properties such as `contains_mathml` and all resource media types.

## Tests

Required rendering fixture assertions:

- heading hierarchy maps correctly;
- special characters `<>&` from OCR are escaped;
- inline/display LaTeX produces parseable MathML for representative fractions, roots, superscripts, matrices, sums, Greek symbols;
- formula failure takes documented fallback;
- code indentation/newlines are preserved;
- table rowspan/colspan survive;
- external table image/script URL is removed/rejected;
- figure uses responsive class, no absolute CSS;
- pagebreak anchors exist for every source page;
- no whole-page source image path appears in XHTML;
- generated XHTML parses as XML.

## Acceptance criteria

M3 complete means a comprehensive BookIR fixture renders to an unpacked XHTML tree where:

- all content is readable in normal document order;
- no `position:absolute`, JavaScript, background page image, or fixed viewport exists;
- formulas are MathML except explicit fallback cases;
- code is selectable text;
- structured tables remain tables;
- source-page destinations and TOC model are complete;
- every XHTML file is well-formed XML.
