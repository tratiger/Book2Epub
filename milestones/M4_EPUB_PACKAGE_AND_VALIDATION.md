# M4 - Native EPUB 3.3 Packaging and EPUBCheck Validation

## Objective

Package the M3 render tree into a standards-conformant reflowable EPUB 3.3 without Pandoc and validate it with EPUBCheck 5.3.0.

## EPUB tree

Build a staging directory:

```text
render/epub-root/
  mimetype
  META-INF/
    container.xml
  OEBPS/
    package.opf
    nav.xhtml
    text/
      part-0001.xhtml
      ...
    styles/
      book.css
    images/
      ...
```

All paths inside the EPUB use `/`, never Windows backslashes.

## `mimetype`

Root `mimetype` contents are exactly:

```text
application/epub+zip
```

ASCII, no BOM, no newline, no leading/trailing whitespace.

When zipping, this entry MUST be first and MUST use ZIP_STORED (uncompressed). No extra field is intentionally added.

All other files use Deflate unless there is a reason to leave an already-compressed binary stored; either is permitted by EPUB 3.3, but implement one deterministic policy.

## `META-INF/container.xml`

Point to exactly one package document:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
```

## `package.opf`

Use package version `3.0` as required for EPUB 3.x package documents while conforming to EPUB 3.3 requirements.

Required metadata:

- `dc:identifier` with stable id referenced by `unique-identifier`;
- `dc:title`;
- `dc:language`;
- one `dc:creator` per author when supplied;
- optional `dc:publisher`;
- `meta property="dcterms:modified"` in UTC `YYYY-MM-DDTHH:MM:SSZ`.

Do not guess author/publisher from OCR unless a later explicit requirement adds deterministic front-matter extraction.

### Manifest

Include every XHTML, stylesheet, and image exactly once.

Required media types include:

- XHTML: `application/xhtml+xml`
- CSS: `text/css`
- JPEG: `image/jpeg`
- PNG: `image/png`
- GIF if ever copied: `image/gif`
- SVG if ever produced: `image/svg+xml`
- WebP: `image/webp` (EPUB 3.3 lists WebP as an image core media type). Preserve valid MinerU WebP content assets without conversion unless a later reader-compatibility test explicitly justifies a content-asset conversion. Do not make whole-page images.

Exactly one nav item must have `properties="nav"`.

Any XHTML item containing MathML MUST include `mathml` in its manifest `properties`. If it also has another property, emit a whitespace-separated list.

If a cover image is explicitly supplied, set manifest property `cover-image` on that image and create a semantic cover XHTML if needed for spine/landmarks. No implicit full first-page cover in v1.

### Spine

Spine order equals renderer content-document order.

The default publication is reflowable; do not set `rendition:layout` to `pre-paginated`.

Do not add spread metadata.

## `nav.xhtml`

Navigation document is mandatory and must contain exactly one `nav epub:type="toc"`.

Create:

1. TOC nav (required)
2. page-list nav (Book2Epub default, required by product even though optional in EPUB spec)
3. landmarks nav when targets exist

### TOC

Use renderer heading tree and links to top-level content document or fragment.

Nested `<ol>` structure must follow EPUB nav restrictions: each li begins with exactly one `a` or `span`, then optional nested ol.

### page-list

One flat ordered list. Each item links to PageMap target.

Example:

```xml
<nav epub:type="page-list" aria-label="Pages">
  <ol>
    <li><a href="text/part-0003.xhtml#page-137">137</a></li>
  </ol>
</nav>
```

For unknown printed labels use `scan-137` display label. Page-list target may be a block-boundary or inline pagebreak span.

### landmarks

Include at minimum bodymatter when known. Include toc landmark only if a visible TOC document is in spine; the machine nav document itself need not be exposed as reading content.

## Content-document semantics

Generated pagebreak spans use:

```xml
<span epub:type="pagebreak" role="doc-pagebreak" aria-label="..." id="..."/>
```

Ids must be XML/HTML-safe and unique publication-wide at least within target document; generated href map must be tested for exact resolution.

## ZIP implementation

Use Python standard library `zipfile`.

Algorithm:

1. create new archive with `allowZip64=True`;
2. write `mimetype` first with `ZIP_STORED`;
3. write remaining files in deterministic lexical path order with `ZIP_DEFLATED`;
4. use UTF-8 names;
5. do not encrypt;
6. close archive;
7. reopen and assert first `namelist()[0] == "mimetype"` and its compression is `ZIP_STORED`;
8. write to temporary output then atomically replace requested output path on success.

Never leave a partial requested `.epub` after a failed validation. Keep failed candidate in job validation/debug area.

## EPUBCheck integration

Use `.tools/epubcheck-5.3.0/epubcheck.jar`.

Run:

```powershell
java -jar <epubcheck.jar> <candidate.epub> --json <report.json>
```

Also save text stdout/stderr.

Treat nonzero exit or any ERROR/FATAL as failure.

Warnings:

- store all warnings;
- if warning is clearly caused by generated Book2Epub markup/resources, fail strict mode;
- known informational/usage notices may be allowed only through an explicit code allowlist with a test and comment explaining why.

Do not parse only human text if JSON report is available.

## Internal validation before EPUBCheck

Before external checker:

- every manifest href exists;
- every spine idref exists in manifest;
- exactly one nav property;
- no duplicate IDs per XHTML;
- every internal href/src resolves;
- no path escapes `OEBPS` using `..`;
- no external `http:`/`https:` resource src/href except ordinary hyperlink anchors in prose; publication resources must be local;
- no JavaScript;
- no absolute-position source layout CSS;
- every math-containing XHTML manifest item is marked mathml;
- every copied resource media type matches extension/signature where feasible.

## `validate` command

Implement:

```powershell
uv run book2epub validate book.epub
```

It runs internal ZIP/manifest/link checks plus EPUBCheck and prints summary.

## Successful `convert`

At end of M4 the normal command is fully functional:

```powershell
uv run book2epub convert pages -o book.epub
```

On success print:

- output path;
- EPUB file size;
- source page count;
- XHTML part count;
- figure/chart/table/code/math counts;
- fallback counts;
- warnings count;
- EPUBCheck PASS;
- QA report path (M5 may enrich the report).

## Tests

Required:

- package metadata XML parses;
- nav conforms to expected nesting shape;
- all TOC links resolve;
- all page-list links resolve;
- MathML property present only/at least where required;
- mimetype is first/uncompressed/exact content;
- no Windows `\\` paths inside ZIP;
- EPUBCheck integration fixture passes;
- deliberately broken href is caught internally;
- deliberately malformed package fails EPUBCheck test when tool is available;
- candidate output is not promoted to requested path on validation failure.

Mark external EPUBCheck tests with a marker, but the M4 acceptance command on the target machine MUST run them.

## Acceptance criteria

A comprehensive synthetic technical-book fixture must produce an EPUB that:

- passes EPUBCheck 5.3.0 with no generated errors;
- is reflowable;
- contains semantic XHTML text/code/table/math;
- has valid TOC and source-page navigation;
- contains no whole source-page images;
- contains no script or absolute-position source recreation.
