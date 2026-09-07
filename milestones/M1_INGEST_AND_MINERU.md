# M1 - Image Ingest, Lossless Source PDF, and MinerU Execution

## Objective

Convert a directory of cleaned page images into one deterministic multi-page source PDF, run MinerU locally on Windows using the frozen high-quality configuration, canonicalize the resulting `middle.json` and asset directory without changing their content, and implement MinerU-stage caching.

## Supported input

Initial supported page formats:

- `.jpg`, `.jpeg`
- `.png`
- `.tif`, `.tiff`
- `.webp`

Input is a single directory. M1 does not recurse into nested folders for page images.

Ignore hidden/system noise files and known non-page files such as `desktop.ini` and `Thumbs.db`.

If no supported images exist, fail.

## Ordering

Use deterministic natural sort by filename, case-insensitive, then case-sensitive original name as tie-breaker.

Example:

```text
page1.jpg
page2.jpg
page02-alt.jpg
page10.jpg
```

Do not sort by file creation time, EXIF capture time, or modification time.

Before conversion, display the first five and last five ordered filenames in verbose mode.

## Input validation

For every page:

- read metadata through Pillow/img2pdf-compatible path without modifying the original file;
- reject zero dimension;
- reject corrupt/undecodable image;
- calculate SHA-256;
- record byte size, width, height, file suffix, and ordered index;
- detect duplicate byte-identical pages by hash and emit WARN, not fatal error;
- detect extreme aspect ratio (<0.35 or >2.0) and WARN;
- never rewrite or rotate the user's source image.

Write `input/manifest.json` with schema version and all page metadata.

## Source PDF

Use `img2pdf==0.6.3` as a Python library, not ImageMagick.

For common JPEG/JPEG2000/non-interlaced non-transparent PNG and supported direct formats, img2pdf embeds image data without lossy re-encoding. The source PDF is only a container to give MinerU one continuous document.

Use the ordered file paths in a single `img2pdf.convert(...)` call and write to:

```text
.work/jobs/<job-id>/input/source.pdf
```

Handle malformed EXIF orientation conservatively using the img2pdf `Rotation.ifvalid` behavior. Do not perform arbitrary raster re-encoding to fix orientation.

The number of PDF pages MUST equal the number of manifest pages. Verify with a local PDF-page-count capability already available through MinerU/PDFium dependency or a lightweight installed parser. Do not add a second heavyweight PDF toolkit solely for this check.

## Why images are bundled into one PDF

MinerU accepts individual images, but a directory of separate image documents does not provide the same whole-book continuity as one multi-page document. Book2Epub therefore always creates one source PDF before MinerU. This also gives stable page indices and lets MinerU's document postprocessing work across page boundaries.

## MinerU execution contract

Run MinerU as a subprocess with environment:

```text
MINERU_MODEL_SOURCE=local
```

Command semantics must be equivalent to:

```powershell
mineru `
  -p <source.pdf> `
  -o <mineru-raw-output-dir> `
  --backend hybrid-engine `
  --effort high `
  --method ocr `
  --formula true `
  --table true `
  --image-analysis true
```

Use argument arrays in code.

Rationale:

- scanned source requires OCR mode;
- `hybrid-engine` is the current MinerU default high-accuracy local engine family;
- `high` is required because quality is prioritized and MinerU documents that medium effort disables image/chart analysis automatically;
- formula/table/image analysis must stay enabled.

Do not use `pipeline` as silent fallback. Do not use `vlm-http-client` or `hybrid-http-client`.

## MinerU output discovery

Do not hard-code MinerU's nested output subdirectory name. After successful exit:

1. recursively search the raw output directory for `*_middle.json`;
2. require exactly one candidate for this one-book job;
3. parse its root;
4. verify `_version_name == "3.4.5"`;
5. verify `_backend == "hybrid"`;
6. verify `_effort == "high"` if the field is present; if absent, WARN and continue only if version/backend match;
7. verify `pdf_info` is a list with the same page count as the source PDF.

Any version/backend mismatch is fatal.

## Canonicalization

Never alter the raw MinerU output tree.

Copy/link the authoritative artifacts to a canonical area:

```text
mineru/canonical/
  book_middle.json
  images/
```

`book_middle.json` is byte-for-byte copied from the discovered MinerU file.

The canonical `images` directory contains the MinerU asset directory referenced by `image_path` fields. Do not rename content image files at M1 because raw paths in middle.json must remain resolvable.

Store a `canonical-map.json` describing raw path -> canonical path.

## Debug artifacts

Preserve when MinerU generates them:

- `*_model.json`
- `*_layout.pdf`
- `*_span.pdf`
- original PDF dump
- generated Markdown/content lists

They are QA/debug only. No later production stage may read Markdown/content-list files.

## Cache

Compute `mineru_cache_key` exactly as specified in the architecture contract.

Write `mineru/stage.json`:

```json
{
  "state": "complete",
  "cache_key": "...",
  "mineru_version": "3.4.5",
  "backend": "hybrid-engine",
  "middle_json_sha256": "...",
  "page_count": 312
}
```

On a later identical run:

- if stage state is complete;
- cache key matches;
- canonical middle JSON exists and hash matches;
- all referenced image assets exist;

then skip MinerU.

`--force-mineru` invalidates only this stage and later stages, not user input.

## Failure behavior

If MinerU exits nonzero:

- mark stage `failed`;
- retain stdout/stderr and partial output;
- do not manufacture a middle JSON;
- print the raw job path;
- exit nonzero.

If CUDA is unavailable, do not silently use CPU for hybrid-engine. Fail with a message directing the user to `book2epub doctor`.

## Commands introduced

`convert` now executes through the end of M1 and then raises `NotImplementedStageError` for M2 until M2 exists.

Add:

```powershell
uv run book2epub inspect-middle path\to\book_middle.json
```

M1 `inspect-middle` prints:

- MinerU version/backend/effort;
- page count;
- page-size distribution;
- `para_blocks` type counts;
- `discarded_blocks` type counts;
- span type counts;
- count of referenced images and missing image paths;
- count of titles with and without `level`.

## Tests

Unit tests:

- image ordering;
- manifest creation;
- duplicate warning;
- cache key stability/change on input hash/config change;
- strict middle root validation;
- canonical output discovery with nested raw directories;
- rejection of two middle JSON candidates;
- rejection of wrong MinerU version/backend;
- referenced-image verification.

Integration test without GPU:

- monkeypatch/substitute MinerU subprocess with fixture output tree;
- run M1 end-to-end;
- verify source PDF page count and canonical files.

Optional GPU smoke test is separate and not part of default pytest.

## Acceptance criteria

Given 10 valid page images and a mocked valid MinerU output:

- `manifest.json` lists exactly 10 in natural order;
- `source.pdf` contains 10 pages;
- canonical `book_middle.json` is created;
- later code never reads content-list or Markdown;
- a second identical run proves the MinerU subprocess was skipped;
- changing one page invalidates the cache.
