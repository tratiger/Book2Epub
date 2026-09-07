# Appendix D - BookIR Schema and Render Mapping Reference

This file is a compact implementation reference. M2 is normative for detailed extraction behavior.

## D1. Suggested module layout

```text
src/book2epub/ir/
  models.py
  source.py
  assets.py
  serializer.py
  normalize.py
  page_labels.py
  text_join.py
src/book2epub/mineru/
  runner.py
  discover.py
  validate.py
  middle_adapter.py
  middle_schema.py
src/book2epub/render/
  xhtml.py
  inline.py
  math.py
  tables.py
  css.py
  split.py
  navigation_model.py
```

## D2. Minimal model sketch

Use discriminated unions; exact field names may vary but semantic data must not.

```python
class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

class SourceRef(BaseModel):
    page_idx: int
    bbox: BBox | None
    source_type: str
    source_index: int | None = None
    line_bboxes: list[BBox] = []
    span_bboxes: list[BBox] = []
    raw_extensions: dict[str, Any] = {}

class Text(InlineBase):
    kind: Literal["text"] = "text"
    text: str

class InlineMath(InlineBase):
    kind: Literal["inline_math"] = "inline_math"
    latex: str
    fallback_asset_id: str | None = None

class Paragraph(BlockBase):
    kind: Literal["paragraph"] = "paragraph"
    inlines: list[Inline]

class Heading(BlockBase):
    kind: Literal["heading"] = "heading"
    level: int | None
    inlines: list[Inline]
```

Avoid mutable defaults in actual Pydantic code; use factories.

## D3. Source -> IR -> XHTML

| MinerU middle | BookIR | XHTML |
|---|---|---|
| title | Heading | h1-h6 |
| text | Paragraph | p |
| text span | Text | text node |
| inline_equation span | InlineMath | MathML math |
| interline_equation | DisplayMath | div + MathML |
| image + body/caption | Figure | figure/img/figcaption |
| chart | Chart | figure/img/figcaption |
| table HTML | Table | table inside figure/wrapper |
| code | CodeBlock | pre/code (+ figure if caption) |
| algorithm | CodeBlock subtype | pre/code |
| list | ListBlock | ol/ul |
| index | IndexBlock | section/list |
| aside_text | Aside | aside |
| page_footnote | Footnote | aside epub:type=footnote |
| page_number | SourcePage label | pagebreak/page-list; no prose |
| header/footer | suppressed boilerplate | not rendered |

## D4. Provenance invariant

No BookIR block that came from MinerU may have an empty source reference unless it is a Book2Epub-synthesized structural node such as a generated PageBreak or chapter container.

If a node merges multiple source blocks/pages, it stores `sources: list[SourceRef]` rather than selecting one and losing the others.

## D5. Stable generated IDs

Generated IDs should be deterministic within a fixed IR:

```text
h-000123-<short-slug>
fig-000045
Tbl-000012
page-000137
```

Do not use Python hash() because it is process-randomized. Use sequence numbers and sanitized text, or SHA-256 fragments.

## D6. Plain-text extraction

Implement one utility that extracts user-visible plain text from any Inline/Block for:

- TOC labels;
- captions/alt candidates;
- QA report;
- title inference.

Math plain text should default to original LaTeX, not pretend OCR prose.

## D7. No accidental source-image inclusion

Asset role must be explicit. `source_page` is not an allowed EPUB asset role. The EpubWriter rejects any Asset whose role is `source_page` or whose path belongs to the input page manifest unless it is explicitly configured as `cover`.
