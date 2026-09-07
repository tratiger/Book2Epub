# Appendix A - Frozen MinerU 3.4.5 `middle.json` Contract

This appendix records the specific MinerU facts the implementation may rely on. It exists so the implementation agent does not need to search upstream documentation while coding.

## A1. Stable release and Windows target

The stable version selected for v1 is MinerU **3.4.5**, released 2026-08-14 on PyPI. MinerU 4.0.0a* releases are alpha/pre-release and not supported by this contract.

MinerU current quick-start documentation supports Windows and Python 3.10-3.12 on Windows for the relevant engine stack; v1 fixes Python 3.12.

## A2. CLI

Relevant current CLI options:

```text
mineru -p PATH -o PATH
  -m/--method [auto|txt|ocr]
  -b/--backend [pipeline|vlm-engine|hybrid-engine|vlm-http-client|hybrid-http-client]
  --effort [medium|high]
  -f/--formula BOOLEAN
  -t/--table BOOLEAN
  --image-analysis BOOLEAN
  --client-side-output-generation BOOLEAN
```

Current default backend is `hybrid-engine`; current default effort is `medium`. Book2Epub overrides effort to `high`.

MinerU documentation states that hybrid medium effort automatically disables image/chart analysis; therefore Book2Epub uses high effort.

Source: https://opendatalab.github.io/MinerU/usage/cli_tools/

## A3. Model source

Supported `MINERU_MODEL_SOURCE` values include `huggingface`, `modelscope`, and `local`. For local predownloaded models:

```powershell
$env:MINERU_MODEL_SOURCE = "local"
```

Model download command:

```powershell
mineru-models-download -s huggingface -m all
```

or ModelScope.

MinerU records model paths/config in user `mineru.json`.

Source: https://opendatalab.github.io/MinerU/usage/model_source/

## A4. Windows RTX 50xx acceleration

MinerU FAQ for Blackwell/RTX 50xx documents Windows `lmdeploy 0.11.1 + cu128` wheel, with Python ABI selected by Python minor version. For Python 3.12:

```powershell
$env:LMDEPLOY_VERSION = "0.11.1"
$env:PYTHON_VERSION = "312"
$wheel = "https://github.com/InternLM/lmdeploy/releases/download/v$($env:LMDEPLOY_VERSION)/lmdeploy-$($env:LMDEPLOY_VERSION)+cu128-cp$($env:PYTHON_VERSION)-cp$($env:PYTHON_VERSION)-win_amd64.whl"
pip install $wheel --extra-index-url https://download.pytorch.org/whl/cu128
```

When cu128 torch is already installed, FAQ says use `--no-dependencies` to avoid downloading a lower torch.

Source: https://github.com/opendatalab/MinerU/blob/master/docs/en/faq/index.md

## A5. `middle.json` root

Official output documentation describes:

```text
pdf_info: list[dict]
_backend: string
_version_name: string
```

Current hybrid source initializes:

```json
{
  "pdf_info": [],
  "_backend": "hybrid",
  "_effort": "high|medium",
  "_ocr_enable": true|false,
  "_version_name": "<MinerU version>"
}
```

Book2Epub requires `_backend == "hybrid"` and `_version_name == "3.4.5"`.

Hybrid source reference:
https://github.com/opendatalab/MinerU/blob/master/mineru/backend/hybrid/hybrid_model_output_to_middle_json.py

## A6. Page structure

Documented `pdf_info` page fields include:

```text
preproc_blocks
page_idx
page_size = [width, height]
images
tables
interline_equations
discarded_blocks
para_blocks
```

`para_blocks` is the main segmented content list.

## A7. Hierarchy

Documented pipeline-style structure:

```text
Level 1 visual block (table | image | chart)
  -> Level 2 block
      -> line
          -> span
```

Common nested block types documented/currently used include:

```text
image_body
image_caption
image_footnote
table_body
table_caption
table_footnote
chart_body
chart_caption
chart_footnote
text
title
index
list
interline_equation
code_body
code_caption
code_footnote
```

Hybrid adds top-level `code` with `sub_type` `code` or `algorithm`.

Discarded-block types may include:

```text
header
footer
page_number
aside_text
page_footnote
```

## A8. Lines and spans

Line commonly contains:

```text
bbox
spans
```

Span commonly contains:

```text
bbox
type
content | image_path
```

Documented span types include:

```text
text
inline_equation
interline_equation
image
table
chart
```

Table span may contain:

```text
html
image_path
```

MinerU's own content builder uses table span `html` preferentially and table `image_path` as a fallback.

Image span commonly contains `image_path`; chart span may contain `image_path` and `content`.

## A9. Coordinates

For middle JSON page/block structures, bbox coordinates are source-page coordinate values associated with `page_size`. Content-list coordinates must not be confused with middle JSON coordinates: content-list bboxes are normalized to 0-1000.

The Book2Epub adapter always computes ratios using the page's actual `page_size` and the middle block bbox.

## A10. Title levels

Current hybrid finalization calls title-leveling and then normalizes split title block types:

- document title -> common `title`, level 1
- paragraph title -> common `title`, level 2

Other title-leveling logic may provide deeper levels. Book2Epub reads `level` from middle title block when present.

Do not obtain level from content-list.

## A11. Cross-page processing

Current hybrid finalization calls `cross_page_table_merge(pdf_info_list)` when table parsing is enabled, then title leveling and cleanup. This is a reason to supply MinerU one multi-page book PDF and avoid arbitrary page chunking.

## A12. Table HTML details

Current MinerU builder logic for a `table_body` iterates table spans:

- if `span['html']` exists, structured HTML is preferred;
- else if `span['image_path']` exists, image can be used.

It also handles `<eq>...</eq>` in table HTML when producing downstream representations. Book2Epub performs its own safe conversion to MathML rather than importing MinerU content-list output.

Source:
https://github.com/opendatalab/MinerU/blob/master/mineru/backend/pipeline/pipeline_middle_json_mkcontent.py

## A13. Why not content lists

MinerU documentation explicitly describes `content_list.json` as a simplified version of `middle.json` that stores readable content in a flat reading-order structure and removes complex layout information. `content_list_v2` is a newer easier-to-consume representation, but Book2Epub's requirement is maximum retained source information and source-layout intent, so it is not the production input.

Source:
https://opendatalab.github.io/MinerU/reference/output_files/
