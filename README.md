# Book2Epub Implementation Specification

This directory is the governing implementation specification for **Book2Epub**: a Windows-native pipeline that converts clean, rectified page images of technical books into a standards-compliant, reflowable EPUB 3.3 while preserving as much semantic structure and layout intent as practical.

## Governing architecture

```text
Rectified page images (vFlat, etc.)
  -> deterministic natural ordering
  -> lossless multi-page PDF (img2pdf)
  -> MinerU 3.4.5, local Windows GPU, hybrid-engine, effort=high, OCR mode
  -> MinerU *_middle.json (the only authoritative MinerU structured input)
  -> Book2Epub IR (lossless semantic/provenance normalization)
  -> layout-intent reconstruction (not pixel-position reconstruction)
  -> reflowable XHTML 5 + MathML + CSS
  -> native EPUB 3.3 package writer
  -> EPUBCheck 5.3.0
  -> .epub
```

## Explicitly rejected architectures

The implementation MUST NOT use any of the following as its production path:

- fixed-layout EPUB as the primary output;
- a full scanned page image as the content page;
- a scanned page image as a background with a transparent OCR/text overlay;
- absolute-positioned page reconstruction;
- Pandoc as the production EPUB generator;
- MinerU Markdown, `content_list.json`, or `content_list_v2.json` as the source of truth;
- WSL, Docker, Linux containers, or a remote OCR/LLM service;
- MinerU HTTP client backends.

The target is an ordinary reflowable EPUB that opens and behaves like an electronic book in mainstream EPUB reading systems.

## Target environment

- Windows 11 x64
- CPython 3.12
- `uv` for environment and dependency management
- NVIDIA GPU; primary target is RTX 50-series / Blackwell
- MinerU 3.4.5 stable release
- Local models only during normal conversion
- No WSL and no Docker

## Specification order

Read and implement in this order:

1. `AGENTS.md`
2. `00_PRODUCT_AND_ARCHITECTURE.md`
3. `milestones/M0_FOUNDATION.md`
4. `milestones/M1_INGEST_AND_MINERU.md`
5. `milestones/M2_MIDDLE_JSON_TO_BOOKIR.md`
6. `milestones/M3_REFLOW_RENDERER.md`
7. `milestones/M4_EPUB_PACKAGE_AND_VALIDATION.md`
8. `milestones/M5_QA_RELIABILITY_AND_RELEASE.md`
9. appendices as referenced by each milestone (including `appendices/F_EXTERNAL_FACTS_AND_SOURCES.md`)

A milestone is complete only when every acceptance criterion in that milestone is satisfied.

## Final user experience

The normal command MUST be:

```powershell
uv run book2epub convert "D:\Books\MyBook\pages" -o "D:\Books\MyBook\MyBook.epub"
```

A rendering-only development path MUST also exist:

```powershell
uv run book2epub from-middle ".work\jobs\<job-id>\mineru\book_middle.json" -o out.epub
```

The second command is critical because it allows all EPUB/BookIR development and regression testing without rerunning the expensive MinerU stage.

## Sources frozen for this specification

- MinerU 3.4.5 stable release on PyPI (2026-08-14): https://pypi.org/project/mineru/
- MinerU output-file reference: https://opendatalab.github.io/MinerU/reference/output_files/
- MinerU CLI reference: https://opendatalab.github.io/MinerU/usage/cli_tools/
- MinerU model source reference: https://opendatalab.github.io/MinerU/usage/model_source/
- MinerU Windows CUDA FAQ: https://github.com/opendatalab/MinerU/blob/master/docs/en/faq/index.md
- EPUB 3.3 Recommendation: https://www.w3.org/TR/epub-33/
- EPUB Reading Systems 3.3: https://www.w3.org/TR/epub-rs-33/
- EPUBCheck: https://www.w3.org/publishing/epubcheck/
- EPUBCheck 5.3.0 releases: https://www.w3.org/publishing/epubcheck/releases/
- img2pdf: https://github.com/josch/img2pdf
- latex2mathml 3.81.0: https://pypi.org/project/latex2mathml/
