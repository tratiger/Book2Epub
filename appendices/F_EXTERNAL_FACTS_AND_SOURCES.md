# Appendix F - External Facts and Source Index

Specification freeze date: **2026-09-08**.

The implementation agent should not need to browse these sources. They are recorded for auditability and future human updates.

## F1. MinerU stable version

Frozen fact:

- Stable production version selected: `mineru==3.4.5`.
- PyPI release history shows 3.4.5 released 2026-08-14.
- `4.0.0a*` entries are prereleases and are excluded.

Source:
https://pypi.org/project/mineru/

## F2. MinerU Windows/Python/hardware

Frozen facts from current Quick Start:

- Windows is supported.
- Current engine stack supports Python 3.10-3.12 on Windows; v1 selects 3.12.
- Hybrid/VLM local engine path requires GPU; documented minimum VRAM is 8 GB for the engine family.
- Current accuracy table reports the hybrid high-effort configuration as the highest of its hybrid medium/high choices.

Source:
https://opendatalab.github.io/MinerU/quick_start/

## F3. MinerU CLI

Frozen facts:

- backends include `pipeline`, `vlm-engine`, `hybrid-engine`, `vlm-http-client`, `hybrid-http-client`;
- default backend is hybrid-engine;
- effort choices are medium/high;
- medium hybrid effort automatically disables image/chart analysis;
- CLI supports OCR method, formula and table toggles, image-analysis toggle.

Source:
https://opendatalab.github.io/MinerU/usage/cli_tools/

## F4. MinerU model download/local use

Frozen facts:

- model sources include HuggingFace, ModelScope, local;
- model downloader command is `mineru-models-download`;
- noninteractive examples use `-s huggingface -m all` or ModelScope;
- local normal inference is selected with `MINERU_MODEL_SOURCE=local`.

Source:
https://opendatalab.github.io/MinerU/usage/model_source/

## F5. RTX 50xx direct Windows acceleration

Frozen fact:

MinerU FAQ instructs RTX 50xx/Blackwell direct Windows users to install the `lmdeploy 0.11.1 + cu128` Windows wheel and provides the Python-minor-specific URL pattern. It also documents `--no-dependencies` when cu128 torch is already installed.

Source:
https://github.com/opendatalab/MinerU/blob/master/docs/en/faq/index.md

## F6. MinerU structured output

Frozen facts:

- `middle.json` is a structured intermediate output intended for secondary development.
- root includes `pdf_info`, `_backend`, `_version_name`.
- page data includes `preproc_blocks`, `page_idx`, `page_size`, `images`, `tables`, `interline_equations`, `discarded_blocks`, `para_blocks`.
- hierarchy preserves blocks/lines/spans and bboxes.
- `content_list.json` is explicitly described as a simplified/flattened representation that removes complex layout information.

Source:
https://opendatalab.github.io/MinerU/reference/output_files/

Relevant current hybrid source:
https://github.com/opendatalab/MinerU/blob/master/mineru/backend/hybrid/hybrid_model_output_to_middle_json.py

Relevant table/content builder source:
https://github.com/opendatalab/MinerU/blob/master/mineru/backend/pipeline/pipeline_middle_json_mkcontent.py

## F7. img2pdf

Frozen facts for `img2pdf==0.6.3`:

- designed for lossless raster-image-to-PDF conversion;
- JPEG/JPEG2000 and suitable PNG inputs can be embedded directly without re-encoding;
- supports multiple input files in one output PDF;
- Windows is supported;
- malformed EXIF orientation can be handled with `Rotation.ifvalid` / `--rotation=ifvalid`.

Source:
https://github.com/josch/img2pdf/blob/main/README.md

## F8. LaTeX to MathML

Frozen facts:

- `latex2mathml==3.81.0`, released 2026-04-15;
- pure Python;
- supports Python 3.12;
- API `latex2mathml.converter.convert(...)` produces presentation MathML and supports inline/block display mode.

Sources:
https://pypi.org/project/latex2mathml/
https://github.com/roniemartinez/latex2mathml

## F9. EPUB 3.3 reflow model

Frozen facts:

- EPUB content is normally reflowable by default;
- fixed-layout exists but is not used by this product;
- XHTML and SVG are EPUB content document flavors;
- a mandatory EPUB Navigation Document provides TOC/navigation.

Source:
https://www.w3.org/TR/epub-33/

## F10. EPUB OCF ZIP

Frozen requirements used by EpubWriter:

- `.epub` is a ZIP-based OCF container;
- root `mimetype` is first entry;
- exact content is `application/epub+zip` in US-ASCII;
- no BOM/whitespace;
- mimetype is uncompressed and unencrypted;
- only Stored and Deflate are used by Book2Epub;
- UTF-8 filenames;
- `META-INF/container.xml` points to package document.

Source:
https://www.w3.org/TR/epub-33/

## F11. EPUB image core media types

EPUB 3.3 core image media types include:

- `image/gif`
- `image/jpeg`
- `image/png`
- `image/svg+xml`
- `image/webp`

Source:
https://www.w3.org/TR/epub-33/

## F12. EPUB navigation/page-list

Frozen facts:

- exactly one TOC nav is required in the navigation document;
- page-list is optional in the EPUB standard but Book2Epub requires it as a product feature;
- page-list links represent static source page boundaries;
- targets may use `pagebreak` semantic;
- reading systems SHOULD provide a way to navigate page-list entries.

Sources:
https://www.w3.org/TR/epub-33/
https://www.w3.org/TR/epub-rs-33/

## F13. MathML manifest property

An XHTML manifest item containing MathML is declared with the `mathml` property. The EPUB 3.3 specification provides examples combining properties such as `scripted mathml`.

Source:
https://www.w3.org/TR/epub-33/

## F14. EPUBCheck

Frozen facts:

- EPUBCheck is the official/de facto conformance checker maintained by DAISY for W3C;
- version 5.3.0 (2025-09-01) is the latest production-ready release at freeze time;
- 5.3.0 validates EPUB 3 against EPUB 3.3;
- standalone distribution includes `epubcheck.jar` and its libraries.

Sources:
https://www.w3.org/publishing/epubcheck/
https://www.w3.org/publishing/epubcheck/releases/
https://github.com/w3c/epubcheck/releases/tag/v5.3.0

## F15. EPUBCheck Windows bootstrap URL

Frozen download URL:

```text
https://github.com/w3c/epubcheck/releases/download/v5.3.0/epubcheck-5.3.0.zip
```

The implementation downloads the ZIP then expands it with PowerShell. Do not pipe this ZIP into `tar`; an upstream documentation issue records that such a command is incorrect for the ZIP payload.

Issue reference:
https://github.com/w3c/epubcheck/issues/1643
