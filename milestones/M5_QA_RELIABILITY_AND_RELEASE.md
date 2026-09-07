# M5 - QA, Reliability, Diagnostics, and Release Gate

## Objective

Make the pipeline usable for large real books: rich diagnostics, rerendering without MinerU, semantic-quality checks, deterministic reports, cache/resume behavior, and release-grade tests.

## QA report

Generate `qa/report.json` and `qa/report.html` outside the EPUB.

The report is local/offline and may reference original source page images from the job workspace.

Required sections:

- job/environment summary;
- dependency versions;
- input page manifest summary;
- MinerU version/backend/effort;
- BookIR block counts by type;
- fallback counts;
- title-level distribution;
- page-number recognition table;
- missing caption/alt warnings;
- unknown block/field warnings;
- cross-page paragraph merges performed;
- dehyphenations performed;
- table sanitizer failures/fallbacks;
- math conversion failures/fallbacks;
- EPUB internal validation result;
- EPUBCheck result.

### Page-level QA

For each source page provide a compact entry:

- source page index/printed label;
- thumbnail or link to source image/PDF page where available;
- source block list with bbox/type;
- generated BookIR blocks originating on the page;
- links/IDs of rendered XHTML targets;
- warnings.

This QA page is allowed to show source page imagery because it is not the EPUB content.

Do not implement OCR overlays in the EPUB itself.

## Structural quality checks

Add deterministic validators:

### Content-loss check

For every meaningful source `para_block`:

- it must map to at least one BookIR node or an explicit suppression reason (`header`, `footer`, `page_number`, duplicated boilerplate);
- content-bearing unknown blocks may not disappear silently.

### Asset-loss check

Every referenced MinerU local content asset must be either:

- registered and copied to final EPUB;
- intentionally superseded by semantic content (e.g. valid table HTML, successful MathML) with provenance record;
- explicitly excluded as non-content with reason.

### Math check

Count source inline/display equations and final successful MathML + fallbacks. Counts must reconcile.

### Table check

Count source tables and final semantic table + image-fallback tables. Counts must reconcile.

### Code check

Count source code/algorithm blocks and final `pre/code` blocks. Counts must reconcile.

### Heading check

- no heading level outside 1..6;
- warn on level jumps >1;
- all TOC targets exist;
- all level-1/2/3 headings appear in TOC unless explicitly excluded by config.

## Idempotence/determinism

Given the same:

- input manifest;
- frozen dependencies;
- existing cached middle.json;
- metadata identifier and modified timestamp held fixed for test;

renderer/package output must be structurally deterministic.

ZIP timestamps can otherwise cause byte differences. For reproducibility tests, EpubWriter must support `reproducible=True` and use a fixed valid ZIP timestamp (e.g. 1980-01-01) plus stable file ordering. Production may use current packaging timestamp but metadata modified time remains explicit.

## Rerender command

`from-middle` must be fully supported.

Inputs:

- path to middle JSON;
- optional `--mineru-images-dir`; if omitted, discover sibling/nearby `images` directory;
- metadata options;
- output path.

It runs M2-M5 only and never invokes MinerU.

This command is the standard development/test loop for renderer changes.

## Resume/failure state

Each stage has `stage.json` with `pending|running|complete|failed` plus input hash.

Stages:

1. ingest
2. mineru
3. ir
4. render
5. package
6. validate
7. qa

A complete upstream stage can be reused when its input hash matches. Changing renderer code/config invalidates render and later stages, not MinerU.

For implementation simplicity, code version invalidation can use a manually incremented `STAGE_SCHEMA_VERSION` constant per stage rather than hashing the source tree.

## Large-book behavior

Quality-first defaults:

- process the full source PDF in one MinerU job;
- do not chunk MinerU by default because cross-page semantics may degrade;
- render/package streaming where practical;
- do not hold original raster pages decoded in memory simultaneously;
- copied assets are streamed.

If a full MinerU book fails from resource exhaustion, report it. M5 does not silently introduce chunking because that changes parsing semantics. Future chunking requires its own approved contract.

## User-facing diagnostics

Errors must always include:

- stage;
- concise reason;
- job workspace path;
- next diagnostic command when relevant.

Examples:

```text
MinerU stage failed. Run: uv run book2epub doctor
EPUB validation failed. See: ...\validation\epubcheck.txt
Math conversion fallback used on 4 equations. See QA report: ...\qa\report.html
```

No generic "conversion failed" without stage context.

## Security/privacy

Normal conversion is offline after setup.

- no telemetry implemented by Book2Epub;
- no uploaded book data;
- no HTTP call by Book2Epub conversion code;
- reject external table image resources instead of fetching them;
- never execute OCR-recognized code or HTML scripts;
- sanitize table HTML;
- treat all OCR content as untrusted text;
- XML generation must escape it.

MinerU's own local model libraries may have their own behavior; Book2Epub explicitly sets `MINERU_MODEL_SOURCE=local` during conversion to prevent normal model download behavior.

## Test corpus strategy

Repository test data must be legally redistributable/synthetic.

Create:

1. synthetic middle JSON comprehensive fixture;
2. synthetic source-page images generated during test containing text/layout markers;
3. synthetic table HTML fixture;
4. known LaTeX formula corpus;
5. small generated technical-book BookIR fixture.

Do not commit scanned pages from commercial O'Reilly books.

Real-book evaluation can be run locally by user and results stored outside git.

## Evaluation metrics for real books

Add `book2epub evaluate JOB_DIR` that prints manual/easy-to-review metrics:

- block coverage = mapped meaningful source blocks / meaningful source blocks;
- math semantic rate = MathML equations / total equations;
- table semantic rate = HTML tables / total tables;
- code text rate = code blocks rendered as text / source code blocks;
- caption retention rate;
- heading-level known rate;
- unknown-block count per 100 pages;
- EPUBCheck error/warning counts.

Do not label these as OCR accuracy metrics; they measure pipeline structural preservation.

## Reader compatibility release checklist

Automated mandatory:

- EPUBCheck 5.3.0 pass;
- XML parsing pass;
- all links/resources resolve;
- no scripts;
- no absolute-position source layout;
- no page-image background/overlay;
- formula/table/code reconciliation passes.

Manual recommended before tagging release:

- open representative EPUB in the user's normal Windows reader;
- open on at least one narrow/mobile reader;
- resize font significantly and confirm reflow;
- select/copy prose and code;
- navigate TOC;
- navigate source page list when reader exposes it;
- inspect several formulas, complex tables, figures, and sidebars.

Do not make a particular proprietary reader a hard runtime dependency.

## Release command

Create a script or documented command group equivalent to:

```powershell
uv run ruff check .
uv run mypy src/book2epub
uv run pytest -q
uv run pytest -q -m epubcheck
uv run book2epub doctor
```

All must pass on the target Windows development machine.

## Definition of Done

The project is complete for v1 when a user can:

```powershell
uv run book2epub convert "D:\scan\book" -o "D:\scan\book.epub"
```

and receive a reflowable EPUB 3.3 that:

- passes EPUBCheck 5.3.0;
- contains selectable prose and code;
- contains MathML for supported formulas with explicit fallback only on conversion failure;
- preserves valid tables as semantic HTML tables;
- includes figures/charts and captions;
- has hierarchy-based TOC;
- retains source page navigation;
- does not use full-page scans as content/background;
- does not depend on WSL/Docker/cloud/Pandoc;
- can be rerendered from middle.json without rerunning MinerU;
- emits a QA report sufficient to locate losses and fallbacks.
