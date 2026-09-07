# M2 - MinerU `middle.json` to BookIR

## Objective

Implement the core semantic normalization layer. M2 converts MinerU 3.4.5 hybrid `middle.json` into a backend-independent BookIR while preserving all meaningful content and source provenance. No EPUB package is created yet.

## Source contract

Input must have:

```json
{
  "_backend": "hybrid",
  "_version_name": "3.4.5",
  "pdf_info": [...]
}
```

Current hybrid MinerU source initializes `_effort` and `_ocr_enable`; retain them as source metadata when present.

Each page is expected to expose at least:

- `page_idx`
- `page_size`
- `preproc_blocks`
- `para_blocks`
- `discarded_blocks`

Hybrid finalization performs paragraph construction, paragraph merges, cross-page table merging, title leveling, and conversion of split document/paragraph title types to common `title` blocks with a default level mapping before output. Do not redo those internal operations blindly.

## Do not derive BookIR from content-list code

It is permitted to read MinerU source/documentation during implementation only insofar as this specification already freezes the expected fields. Production code reads `middle.json` directly.

Do not call MinerU's own Markdown/content-list generator and parse its result.

## BookIR models

Use Pydantic discriminated models. JSON serialization is a first-class debug artifact.

### Root

```text
BookIR
  schema_version: "1.0"
  source: SourceDocument
  metadata: BookMetadata
  blocks: list[Block]
  assets: dict[str, Asset]
  warnings: list[IRWarning]
```

### SourceDocument

```text
mineru_version
mineru_backend
mineru_effort
source_pdf_sha256 | null
page_count
pages: list[SourcePage]
```

### SourcePage

```text
page_idx: int
width: float
height: float
printed_label: str | null
printed_label_confidence: float
```

### Provenance

Every block and meaningful inline node has:

```text
SourceRef
  page_idx
  bbox: [x0,y0,x1,y1] | null
  source_type: str
  source_index: int | null
  line_bboxes: list[bbox]
  span_bboxes: list[bbox]
  raw_extensions: dict
```

Keep raw extensions JSON-serializable. Do not duplicate megabytes of entire source pages into every node.

### Inline nodes

Required:

- `Text(text)`
- `InlineMath(latex, image_path?, mathml?=null)`
- `Hyperlink(url, children)` when an explicit URL survives in source fields
- `LineBreak` only when semantically required; normal print line wraps are not preserved
- `PageBoundary(page_idx,label)` for a source-page transition inside a logically merged paragraph

Do not infer bold/italic from OCR geometry. Preserve style only if MinerU explicitly supplies a stable style field; otherwise plain text.

### Block nodes

Required:

- `Heading(level: int|None, inlines)`
- `Paragraph(inlines)`
- `Figure(asset_id, caption, footnotes, layout_hint, description?)`
- `Chart(asset_id, caption, footnotes, layout_hint, description?)`
- `Table(html, fallback_asset_id?, caption, footnotes, layout_hint)`
- `CodeBlock(text, subtype: code|algorithm, caption, footnotes, language: str|None)`
- `DisplayMath(latex, fallback_asset_id?, mathml?=null)`
- `ListBlock(ordered: bool|None, items: list[list[BlockOrInline]])`
- `Aside(blocks|inlines, subtype)`
- `Footnote(blocks|inlines, scope: page|figure|table|code)`
- `IndexBlock(items)`
- `PageBreak(page_idx,label)`
- `UnknownBlock(source_type, extracted_text?, asset_id?)`

## Block extraction

Iterate `pdf_info` in ascending `page_idx`. For each page, use `para_blocks` as primary content order. Use the block list order/index provided by MinerU; bbox y/x is a validation hint, not an instruction to resort everything geometrically.

### Text / paragraph

For a `text` block:

- flatten lines/spans into inline nodes;
- `text` span -> Text;
- `inline_equation` span -> InlineMath using `content` as LaTeX;
- preserve explicit hyperlink when URL exists;
- ignore print line breaks by default;
- join text spans using deterministic rules below.

### Title

For a `title` block:

- use `block["level"]` when integer 1..6;
- if missing, use deterministic numbered-heading fallback:
  - `Chapter <number/roman>` or Japanese `第...章` -> level 1;
  - leading numeric dotted form `N`, `N.N`, ... -> number of numeric components capped at 6;
  - otherwise `level=None` and warning.
- do not infer a semantic title from font size alone.

Renderer later maps `None` to h2 while preserving a warning.

### Code

Hybrid middle output can contain a top-level `code` block with `sub_type` of `code` or `algorithm`, and nested blocks including `code_body`, optional `code_caption`, and possibly `code_footnote`.

- code body text is joined preserving all internal newlines and indentation present in content;
- never run generic paragraph whitespace normalization over code;
- keep line numbers if MinerU recognized them; do not strip them automatically;
- `language` is set only when a direct stable source field exists; otherwise null;
- algorithm is semantically distinct in IR but uses code-preserving text.

### Image / chart

For level-1 visual blocks:

- locate body span `type=image` or `type=chart`;
- read `image_path`;
- register asset without decoding/re-encoding it;
- collect caption/footnote nested blocks through ordinary inline conversion;
- chart `content` may be preserved as `description` raw textual/structured content but must not replace the visual automatically.

### Table

For `table`:

- locate `table_body` -> `table` span;
- take `span["html"]` when present;
- take `span["image_path"]` as fallback asset when present;
- collect table caption/footnotes;
- raw HTML is retained in raw IR, but normalized HTML is produced by the sanitizer described below.

### Display equation

For `interline_equation`:

- locate interline equation span;
- `content` is LaTeX source;
- register `image_path` when present as fallback;
- do not include `$$` delimiter in the IR latex field if MinerU included it; strip only one matching outer delimiter pair, not arbitrary dollar characters.

### List / index

Prefer explicit source list metadata (`attribute`, `sub_type`, list-start flags) when present.

If ordered/unordered is unknown, keep `ordered=None`. Do not strip text prefixes unless they match a deterministic bullet/number token on every item.

Reference-style list (`sub_type=ref_text`) remains a ListBlock with subtype stored in provenance/extensions.

### Discarded blocks

Do not ignore `discarded_blocks` globally.

Process:

- `header`: exclude from reading content; retain statistics/raw provenance only.
- `footer`: exclude from reading content unless it is classified as page footnote; retain statistics.
- `page_number`: use for printed-page label extraction; do not render as prose.
- `aside_text`: include as `Aside` near its page reading position.
- `page_footnote`: include as `Footnote(scope=page)` near the page boundary.
- unknown discarded type: warning + `UnknownBlock` only if it contains nontrivial unique text not duplicated in header/footer repetition.

## Page label algorithm

For each page, gather text from `page_number` discarded blocks in reading order.

Normalize surrounding whitespace but preserve label text.

Accept as high-confidence label when it matches:

- decimal digits, optionally common surrounding punctuation;
- Roman numerals `[ivxlcdmIVXLCDM]+`;
- common prefix/suffix form such as `p. 12` or `12 ページ` after deterministic extraction.

Require monotonically plausible sequence across neighboring recognized pages; one isolated contradictory label is downgraded.

If no trustworthy label exists, use null in SourcePage. Renderer will expose fallback page-list label `scan-<1-based page_idx>`.

## Text join rules

Paragraph text must not retain OCR line wrapping.

For each adjacent text span/line:

1. preserve all characters except normalize CRLF/CR to LF internally;
2. CJK-to-CJK line boundaries concatenate without injected ASCII space unless source text already contains one;
3. Latin-like words normally join with one space;
4. if previous line ends in a hyphen `-` and next starts lowercase Latin letter, remove the hyphen only when both adjacent pieces contain letters and the previous token is not code/math/URL;
5. otherwise preserve the hyphen;
6. collapse runs of ordinary spaces in prose to one, but preserve NBSP as semantic space only when present;
7. never run these rules inside CodeBlock or raw table HTML.

Record when dehyphenation occurred in normalization statistics.

## Cross-page paragraph merge

Default is conservative.

Insert `PageBreak` between page content first. Then merge the final Paragraph before a PageBreak with the first Paragraph after it only when ALL are true:

- neither is title/list/code/aside/footnote;
- previous paragraph does not end in sentence terminal `. ! ? 。！？」』` or colon heading pattern;
- next paragraph begins lowercase Latin or punctuation that normally continues a sentence, OR the previous line ends in a dehyphenatable Latin word;
- left/right bbox edges of the two paragraphs differ by <= 8% of source page width;
- neither boundary has a figure/table/title between them in source order.

When merging, retain an inline `PageBoundary` at the join so EPUB page-list anchors can still point into the paragraph.

If uncertain, do not merge. A visible paragraph break is preferable to accidental sentence corruption.

## LayoutHint

For Figure, Chart, and Table:

```text
width_ratio: float
size_class: small|medium|large
alignment: left|center|right
source_bbox
```

Compute exactly using thresholds in `00_PRODUCT_AND_ARCHITECTURE.md`.

No layout hint may contain CSS position coordinates.

## Asset registry

Asset fields:

```text
asset_id: sha256:<hex>
source_path: Path
media_type
sha256
byte_size
width | null
height | null
role: figure|chart|table-fallback|equation-fallback|cover
```

Deduplicate byte-identical assets by hash.

Do not recompress normal assets in M2.

## Table HTML sanitizer

Use lxml HTML parsing, then construct an XHTML-safe table fragment.

Allowed structural tags:

`table, thead, tbody, tfoot, tr, th, td, caption, colgroup, col, p, span, br, img, sup, sub, em, strong`

Allowed attributes:

- table cells: `rowspan`, `colspan`, `scope`, `headers`
- image: `src`, `alt`
- generic: `class` only from a Book2Epub-generated allowlist

Remove:

- style attributes from MinerU table HTML;
- event handlers;
- scripts;
- external URLs;
- ids that are not regenerated by Book2Epub.

For `<eq>...</eq>` present inside MinerU HTML, convert its inner LaTeX into an inline-math placeholder IR node before final XHTML generation. If direct tree-level preservation is too complex, replace with a unique token and retain a token map; never emit raw `<eq>` in final XHTML.

For table `<img src>` paths, resolve only local MinerU assets. Copy/register them into AssetRegistry and rewrite later to EPUB-relative paths.

If sanitizer cannot produce one valid table root, mark structured table invalid and rely on fallback asset if available; otherwise fatal in strict mode.

## IR serialization

Write:

```text
ir/bookir.raw.json
ir/bookir.normalized.json
```

Raw is the direct adapter result. Normalized has cross-page joins/page labels/layout hints.

Both must round-trip through Pydantic without data loss.

## Unknown data policy

Unknown dictionary keys on known MinerU structures are retained in provenance `raw_extensions` when reasonably sized.

Unknown block type:

- extract text spans if possible;
- produce UnknownBlock;
- warning includes page/type/bbox;
- strict mode does not fail merely because a future optional field exists;
- strict mode DOES fail when an unknown block type contains a referenced local image/table asset that would otherwise be lost.

## Tests

Create synthetic fixture `tests/fixtures/middle/hybrid-3.4.5-comprehensive.json` containing:

- title with level;
- paragraph with inline equation;
- display equation + image fallback;
- code + caption;
- algorithm;
- figure caption/footnote;
- chart;
- simple and rowspan/colspan tables;
- list;
- index;
- header/footer/page number/aside/page footnote;
- two-page paragraph continuation;
- unknown extra field.

Tests must assert exact BookIR node sequence and content, not only counts.

## Acceptance criteria

M2 complete means:

- comprehensive middle fixture converts with no content loss;
- no production import/function reads content-list or MinerU Markdown;
- all nodes retain page+bbox provenance where source supplies it;
- code whitespace is byte-equivalent after newline normalization;
- inline/display math LaTeX is retained;
- table HTML is safely normalized;
- page numbers are excluded from prose and available as page labels;
- round-trip BookIR JSON produces an equal model;
- unknown fields are not silently lost.
