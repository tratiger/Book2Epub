"""Data models for EPUB 3.3 packaging, OCF container, and validation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass
class ManifestItem:
    """Entry in package.opf manifest."""

    id: str
    href: str  # Relative to package.opf, e.g. "text/part-0001.xhtml"
    media_type: str
    properties: str | None = None  # e.g. "nav", "mathml", "cover-image"


@dataclass
class SpineItem:
    """Entry in package.opf spine."""

    idref: str
    linear: bool = True


@dataclass
class ValidationIssue:
    """Issue detected during internal validation or EPUBCheck."""

    severity: Literal["FATAL", "ERROR", "WARNING", "INFO"]
    message: str
    location: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass
class ValidationReport:
    """Comprehensive validation result including internal checks and EPUBCheck."""

    is_valid: bool
    epubcheck_exit_code: int
    fatal_count: int
    error_count: int
    warning_count: int
    info_count: int
    issues: list[ValidationIssue] = field(default_factory=list)
    raw_epubcheck_json: dict[str, Any] | None = None
    raw_epubcheck_text: str = ""


@dataclass
class PackagingResult:
    """Result of packaging and validating EPUB publication."""

    epub_path: Path
    file_size_bytes: int
    source_page_count: int
    xhtml_part_count: int
    figure_count: int
    chart_count: int
    table_count: int
    code_count: int
    math_count: int
    fallback_count: int
    warning_count: int
    validation_report: ValidationReport
    qa_report_path: Path | None = None
