# Appendix C - Windows Setup and Operations

## C1. Supported environment

- Windows 11 x64
- PowerShell 7+
- Python 3.12 through `uv`
- NVIDIA RTX 50-series primary GPU target
- no WSL
- no Docker

## C2. Initial bootstrap

From repository root:

```powershell
.\scripts\setup.ps1
```

If MinerU models are not downloaded:

```powershell
uv run mineru-models-download -s huggingface -m all
```

Alternative:

```powershell
uv run mineru-models-download -s modelscope -m all
```

Then verify:

```powershell
$env:MINERU_MODEL_SOURCE = "local"
uv run book2epub doctor
```

## C3. Normal conversion

```powershell
$env:MINERU_MODEL_SOURCE = "local"
uv run book2epub convert "D:\Books\Book Name\pages" -o "D:\Books\Book Name\Book Name.epub"
```

The program itself also forces the MinerU subprocess environment to local unless the user explicitly selects a setup/bootstrap source.

## C4. Rerender without OCR

```powershell
uv run book2epub from-middle ".work\jobs\<job-id>\mineru\canonical\book_middle.json" -o rerender.epub
```

Use this for CSS, renderer, and EPUB logic development.

## C5. Validate existing EPUB

```powershell
uv run book2epub validate "D:\Books\Book.epub"
```

## C6. MinerU direct diagnostic command

If Book2Epub reports MinerU failure, reproduction command is conceptually:

```powershell
$env:MINERU_MODEL_SOURCE = "local"
uv run mineru -p ".work\jobs\<job-id>\input\source.pdf" -o ".work\jobs\<job-id>\mineru\manual" --backend hybrid-engine --effort high --method ocr --formula true --table true --image-analysis true
```

Do not switch backend as a troubleshooting shortcut before reporting the original failure.

## C7. RTX 50xx CUDA contract

MinerU current FAQ says Blackwell users on direct Windows installation should use the `lmdeploy 0.11.1 + cu128` Windows wheel.

Python 3.12 wheel URL pattern is frozen in M0.

Use `book2epub doctor` to report:

- GPU name;
- CUDA availability;
- torch CUDA runtime;
- lmdeploy import.

## C8. EPUBCheck

Frozen location:

```text
.tools\epubcheck-5.3.0\epubcheck.jar
```

Manual command:

```powershell
java -jar .tools\epubcheck-5.3.0\epubcheck.jar book.epub
```

JSON report:

```powershell
java -jar .tools\epubcheck-5.3.0\epubcheck.jar book.epub --json report.json
```

## C9. Paths

Book2Epub must work with:

- spaces;
- Japanese filenames;
- long-ish Windows paths within normal Python/Windows support;
- different drives for input and output.

Never rely on current drive being `C:`.

Use `Path.resolve()` only when it does not break nonexistent future output targets. Never manually prepend `\\?\` unless a tested Windows-path need requires it.

## C10. Offline normal operation

After setup/model download:

- MinerU subprocess environment uses local models;
- Book2Epub fetches no resources;
- images/table resources are local only;
- math conversion is local pure Python;
- EPUBCheck is local Java.

This is important for privacy of scanned books.
