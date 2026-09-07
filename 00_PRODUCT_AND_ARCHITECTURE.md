# 00 - Product and Architecture Contract

## 1. Product goal

Book2Epub transforms a sequence of already-cleaned book page images into a normal, reflowable EPUB 3.3 suitable for technical books such as programming, mathematics, networking, security, and scientific texts.

The source images are assumed to have already undergone book-photo correction such as dewarping, perspective correction, shadow cleanup, cropping, and page separation in a tool such as vFlat.

The product is not a scanner. Its responsibility starts at clean page images.

## 2. What "faithful to the original" means

Faithfulness is semantic and relational, not pixel-coordinate reproduction.

Book2Epub MUST preserve, when MinerU provides enough information:

- prose text and reading order;
- chapter/section/subsection hierarchy;
- inline and display mathematics;
- code blocks and algorithm blocks;
- figure images, charts, captions, and figure footnotes;
- table structure, captions, footnotes, rowspan/colspan, and embedded table images when present;
- lists and reference-style lists;
- page side notes and page footnotes when they contain meaningful content;
- source-page boundaries and recognized printed page labels;
- approximate relative figure/table width and alignment intent;
- source location/provenance for QA.

Book2Epub MUST NOT preserve print layout by absolute positioning. Multi-column source pages become a single logical reading flow. Text wrapping is controlled by the EPUB reader. Source pagination is represented with EPUB pagebreak anchors/page-list, not by forcing page-sized screens.

## 3. Non-goals

- Perfect recreation of print typography.
- Font-family identification from scanned pixels.
- Reconstructing arbitrary decorative backgrounds.
- Preserving exact line wrapping from print.
- Preserving multi-column display on narrow EPUB readers.
- Semantic correction by an LLM.
- Copyediting OCR errors beyond deterministic whitespace/hyphen normalization.
- DRM.
- Cloud processing.

## 4. Architecture

```text
[Input directory]
  jpg/png/tiff/webp page images
        |
        v
[Ingest]
  validate -> natural-sort -> hash manifest
        |
        v
[Source PDF]
  img2pdf 0.6.3; lossless container wherever supported
        |
        v
[MinerU]
  3.4.5
  backend=hybrid-engine
  effort=high
  method=ocr
  formula=true
  table=true
  image-analysis=true
  local models
        |
        v
[*_middle.json + MinerU image assets]
        |
        v
[MiddleJsonAdapter]
  strict version/backend validation
  no content-list dependency
        |
        v
[BookIR]
  semantic nodes + full provenance + layout hints
        |
        v
[Normalizer]
  deterministic cross-page joining, page labels,
  heading tree, asset linking, sanitization
        |
        v
[ReflowRenderer]
  XHTML 5 + MathML + CSS + semantic EPUB markup
        |
        v
[EpubWriter]
  OCF ZIP + package.opf + nav.xhtml + spine/manifest
        |
        v
[EPUBCheck 5.3.0]
        |
        v
[book.epub + JSON/HTML QA report]
```

## 5. Frozen versions

The initial supported production stack is deliberately narrow:

| Component | Version/contract |
|---|---|
| Python | 3.12.x |
| MinerU | exactly 3.4.5 stable |
| MinerU backend | hybrid-engine |
| MinerU effort | high |
| img2pdf | 0.6.3 |
| latex2mathml | 3.81.0 |
| EPUB | 3.3 |
| EPUBCheck | 5.3.0 |
| OS | Windows 11 x64 |

MinerU 4.0 alpha is explicitly unsupported.

## 6. Why `middle.json` is the only MinerU source of truth

MinerU documents `content_list.json` as a simplified representation that flattens readable blocks and removes complex layout information. `middle.json` retains per-page structure such as `preproc_blocks`, `page_idx`, `page_size`, `images`, `tables`, `interline_equations`, `discarded_blocks`, and `para_blocks`, with block -> line -> span hierarchy and bbox information.

For hybrid output, current MinerU source also records `_backend: "hybrid"`, `_effort`, `_ocr_enable`, `_version_name`, performs title-level normalization, code/algorithm block construction, and cross-page table processing before final output.

Book2Epub therefore reads `middle.json` directly and treats all derived MinerU Markdown/content-list outputs as debug-only artifacts.

## 7. Source-page images in the final EPUB

A whole source page image MUST NOT be included as a content page or background.

Permitted images in the EPUB are only content resources, including:

- MinerU-extracted figure images;
- charts;
- photographs;
- table images only when structured HTML is unavailable or invalid;
- equation image only as an explicit conversion fallback;
- an explicitly supplied cover image.

The original full-page images remain outside the EPUB in the job workspace for QA.

## 8. Layout-intent reconstruction

bbox is used only for deterministic hints:

- block order validation;
- source page boundary;
- relative width ratio;
- centered/left/right alignment class;
- identifying visual blocks near captions/notes;
- detecting probable sidebar placement;
- QA links back to source coordinates.

Never generate CSS `position:absolute`, fixed viewport dimensions, source-page-height containers, or print-column CSS from bbox.

### Figure width classes

For a visual block bbox `[x0,y0,x1,y1]` on source `page_size=[W,H]`, compute `r=(x1-x0)/W`.

- `r <= 0.36`: `size-small`
- `0.36 < r <= 0.72`: `size-medium`
- `r > 0.72`: `size-large`

CSS remains responsive: all images have `max-width:100%; height:auto`.

### Alignment class

Let block center be `cx=(x0+x1)/2` and normalized center delta `d=(cx-W/2)/W`.

- `abs(d) <= 0.07`: center
- `d < -0.07`: left
- `d > 0.07`: right

Alignment is implemented only by block margins/text-align; never by floating text around the visual.

## 9. Error philosophy

Quality is preferred over silent completion.

Fatal errors include:

- unsupported MinerU version/backend;
- malformed `middle.json` root/page structure;
- missing referenced MinerU content image when no semantic substitute exists;
- duplicate EPUB resource paths;
- invalid XML/XHTML generated by Book2Epub;
- EPUBCheck error;
- no meaningful content parsed from a non-empty book.

Recoverable conditions create warnings and deterministic fallback where explicitly defined:

- formula MathML conversion failure -> equation image if available, otherwise escaped LaTeX text with a visible warning marker in QA report;
- missing figure caption -> image remains with empty-alt unless descriptive content exists;
- table HTML unavailable -> use MinerU table image;
- unknown source page label -> generate `scan-N` label for page-list;
- unknown title level -> preserve heading as level 2 and issue warning unless normalizer can deterministically derive a numbered hierarchy.

## 10. Job workspace contract

Each conversion gets a stable job directory:

```text
.work/jobs/<job-id>/
  input/
    manifest.json
    source.pdf
  mineru/
    raw/                 # unmodified MinerU output tree
    canonical/
      book_middle.json
      images/
  ir/
    bookir.raw.json
    bookir.normalized.json
  render/
    OEBPS/...            # unpacked EPUB payload before zipping
  validation/
    epubcheck.json
    epubcheck.txt
    structural-report.json
  qa/
    report.html
    report.json
  logs/
    book2epub.log
```

Original user image files are never modified.

## 11. Cache identity

The MinerU stage cache key is SHA-256 over:

- ordered input-file SHA-256 values;
- ordered relative input names;
- MinerU version;
- backend;
- effort;
- OCR/formula/table/image-analysis settings;
- Book2Epub ingest schema version.

If this key matches a completed MinerU stage, MinerU must not be rerun unless `--force-mineru` is passed.

Renderer changes do not invalidate MinerU cache.

## 12. Public CLI surface

Required commands:

```text
book2epub convert INPUT_DIR -o OUTPUT.epub
book2epub from-middle MIDDLE_JSON -o OUTPUT.epub
book2epub doctor
book2epub inspect-middle MIDDLE_JSON
book2epub validate EPUB_FILE
```

Required common options:

```text
--title TEXT
--author TEXT                 repeatable
--language TEXT               BCP 47; default auto
--identifier TEXT             default urn:uuid:<generated>
--publisher TEXT
--cover-image PATH
--work-dir PATH               default .work
--keep-work / --no-keep-work  default keep
--force-mineru
--strict / --no-strict        default strict
-v / --verbose
```

`convert` also supports `--mineru-model-source {local,huggingface,modelscope}` but the default normal-conversion value MUST be `local`. Remote sources are permitted only for explicit setup/bootstrap behavior, not silently.

## 13. Final outputs

A successful conversion produces:

- requested `.epub`;
- retained job workspace;
- QA report path printed to console;
- summary with block counts and warnings;
- EPUBCheck result.

Exit code is non-zero on fatal error or EPUBCheck validation failure.
