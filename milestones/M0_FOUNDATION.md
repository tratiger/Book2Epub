# M0 - Foundation, Windows Environment, CLI, and Contracts

## Objective

Create the repository skeleton, Windows-native setup, dependency locking, CLI shell, configuration models, logging, and test/lint/typecheck gates. No MinerU parsing or EPUB rendering is implemented in this milestone.

## Required repository layout

```text
AGENTS.md
README.md
00_PRODUCT_AND_ARCHITECTURE.md
pyproject.toml
uv.lock
src/book2epub/
  __init__.py
  __main__.py
  cli.py
  config.py
  errors.py
  logging.py
  paths.py
  version.py
  util/
    hashing.py
    natural_sort.py
    subprocess.py
scripts/
  setup.ps1
  download_epubcheck.ps1
  smoke_gpu.ps1
tests/
  unit/
  integration/
  fixtures/
.tools/
  .gitkeep
.work/
  .gitkeep
```

`.tools/` and `.work/` contents other than `.gitkeep` are gitignored.

## Python and dependency contract

Use Python `>=3.12,<3.13`.

Runtime dependencies for Book2Epub itself:

- `pydantic>=2.11,<3`
- `typer>=0.16,<1`
- `rich>=14,<15`
- `img2pdf==0.6.3`
- `latex2mathml==3.81.0`
- `lxml>=5,<7`

Development dependencies:

- `pytest>=8,<10`
- `pytest-cov>=6,<8`
- `ruff>=0.12,<1`
- `mypy>=1.16,<2`
- `types-lxml` if needed by the chosen lxml version/tooling

MinerU is a heavy production dependency and must be installed by `scripts/setup.ps1` as exactly:

```powershell
uv pip install -U "mineru[all]==3.4.5"
```

Do not depend on MinerU internals by importing private modules in Book2Epub production code. MinerU is invoked as a subprocess and integrated via its documented/observed output contract.

## `scripts/setup.ps1`

Requirements:

1. Works in Windows PowerShell 7+.
2. Does not require Administrator privileges.
3. Fails with a clear message if `uv` is not on PATH.
4. Creates/updates `.venv` with Python 3.12.
5. Installs Book2Epub dev dependencies.
6. Installs MinerU 3.4.5 with all extras.
7. Detects NVIDIA GPU name using `nvidia-smi` when available.
8. For an RTX 50xx / Blackwell GPU, installs CUDA 12.8 PyTorch wheels and MinerU's documented Windows lmdeploy wheel contract:

```powershell
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
$LMDEPLOY_VERSION = "0.11.1"
$PYTHON_VERSION = "312"
$wheel = "https://github.com/InternLM/lmdeploy/releases/download/v$LMDEPLOY_VERSION/lmdeploy-$LMDEPLOY_VERSION+cu128-cp$PYTHON_VERSION-cp$PYTHON_VERSION-win_amd64.whl"
uv pip install $wheel --no-dependencies
```

9. Calls `scripts/download_epubcheck.ps1`.
10. Runs `uv run book2epub doctor` at the end.

If non-Blackwell NVIDIA is detected, do not invent a CUDA command; print that the current primary target path is Blackwell and let `doctor` report GPU acceleration state.

## EPUBCheck bootstrap

Pin EPUBCheck 5.3.0.

Download from the official GitHub release URL into `.tools/downloads/`, verify that the ZIP exists and is non-empty, extract to `.tools/epubcheck-5.3.0/`, and verify:

```powershell
java -jar .tools\epubcheck-5.3.0\epubcheck.jar --version
```

Canonical download URL:

```text
https://github.com/w3c/epubcheck/releases/download/v5.3.0/epubcheck-5.3.0.zip
```

Do not use the currently incorrect `curl | tar` pattern found in older W3C installation text for a ZIP archive.

## MinerU model bootstrap

`setup.ps1` must NOT silently download tens of GB without user-visible output. After package installation, print the exact optional bootstrap command:

```powershell
uv run mineru-models-download -s huggingface -m all
```

Also support ModelScope:

```powershell
uv run mineru-models-download -s modelscope -m all
```

MinerU writes model paths into the user `mineru.json`. Normal conversion uses `MINERU_MODEL_SOURCE=local`.

## CLI skeleton

Implement Typer app with the required commands. In M0, commands not yet implemented must raise a typed `NotImplementedStageError` and exit nonzero; do not pretend success.

`doctor` is implemented now.

### `doctor` checks

Report PASS/WARN/FAIL for:

- Windows platform and x64;
- Python major/minor exactly 3.12;
- `uv` executable;
- `mineru --version` equals 3.4.5;
- `nvidia-smi` executable and GPU name;
- Python `torch.cuda.is_available()`;
- `torch.version.cuda`;
- ability to import `lmdeploy` on Blackwell;
- `java -version`;
- `.tools/epubcheck-5.3.0/epubcheck.jar` present;
- EPUBCheck version command succeeds;
- writable `.work` directory;
- `MINERU_MODEL_SOURCE` value, with WARN unless it is `local` during normal operation.

`doctor` does not require models to be fully downloaded to pass M0, but must explain how to download them.

## Configuration

Create Pydantic configuration models with at least:

```text
AppConfig
  work_dir: Path = .work
  strict: bool = true
  logging_level: str = INFO

MinerUConfig
  version: str = 3.4.5
  backend: str = hybrid-engine
  effort: str = high
  method: str = ocr
  formula: bool = true
  table: bool = true
  image_analysis: bool = true
  model_source: str = local

RenderConfig
  language: str = auto
  math_mode: str = mathml
  table_mode: str = auto
  preserve_page_list: bool = true
  max_xhtml_chars: int = 100000
  max_source_pages_per_xhtml: int = 50

MetadataConfig
  title: str | None
  authors: list[str]
  language: str = auto
  identifier: str | None
  publisher: str | None
  cover_image: Path | None
```

Validate enum-like values. Environment/CLI overrides may be added, but file configuration is optional in M0.

## Subprocess policy

All external commands go through one wrapper that:

- accepts `list[str]`, never a shell command string;
- uses `shell=False`;
- logs executable and arguments with secrets redacted;
- streams stdout/stderr to the job log when requested;
- returns a typed result containing exit code/stdout/stderr;
- raises a typed error when `check=True` and exit code is nonzero;
- handles Windows path spaces correctly.

## Logging

Every CLI run has:

- human-readable Rich console output;
- file logging once a job directory exists;
- UTC ISO timestamps in file logs;
- no ANSI escape codes in file logs.

## Tests

M0 unit tests must cover:

- natural sorting: `1.jpg, 2.jpg, 10.jpg`;
- mixed case extensions;
- SHA-256 deterministic hashing;
- config validation;
- Windows path with spaces in subprocess wrapper using a harmless Python child process;
- doctor component result model formatting;
- CLI help returns exit code 0.

## Acceptance criteria

M0 is complete only if:

```powershell
uv run ruff check .
uv run pytest -q
uv run mypy src/book2epub
uv run book2epub --help
uv run book2epub doctor
```

all run without an unhandled exception. `doctor` may report WARN for missing model files, but dependency/version contract failures must be FAIL.

## Authoritative facts used

- MinerU supports Windows and Python 3.10-3.12 for Windows in the documented current stack; Python 3.13 is excluded because a key dependency (`ray`) does not support it on Windows.
- MinerU 3.4.5 is the latest stable release as of the specification freeze; 4.0.0a* is pre-release.
- MinerU FAQ explicitly documents `lmdeploy 0.11.1 + cu128` Windows wheel for RTX 50xx.
- EPUBCheck 5.3.0 is the latest production-ready checker and validates EPUB 3.3.
