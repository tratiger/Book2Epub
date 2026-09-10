"""Data models for M3 reflowable XHTML rendering and publication manifest."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from book2epub.ir.models import BookIR


@dataclass
class PageMapEntry:
    """Entry for source page navigation in EPUB page-list."""

    page_idx: int
    label: str
    xhtml_path: str  # Relative to OEBPS, e.g. "text/part-0001.xhtml"
    fragment_id: str  # Anchor id on pagebreak span, e.g. "page-1" or "scan-page-000001"
    printed_label_confidence: str  # "high" or "low"


@dataclass
class TocEntry:
    """Logical heading tree entry for navigation."""

    title: str
    href: str  # Relative to OEBPS, e.g. "text/part-0001.xhtml#h-1-intro"
    level: int  # 1, 2, or 3
    children: list["TocEntry"] = field(default_factory=list)


@dataclass
class RenderedDocument:
    """Rendered XHTML content document metadata."""

    href: str  # Relative to OEBPS, e.g. "text/part-0001.xhtml"
    id: str  # XML ID, e.g. "part-0001"
    title: str
    contains_mathml: bool = False
    media_type: str = "application/xhtml+xml"


@dataclass
class RenderManifest:
    """Summary manifest of unpacked render tree for M4 EPUB packaging."""

    title: str
    language: str
    identifier: str
    page_map: list[PageMapEntry] = field(default_factory=list)
    toc: list[TocEntry] = field(default_factory=list)
    documents: list[RenderedDocument] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    styles: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    presentation_mode: str = "legacy"
    style_profile_hash: str | None = None
    component_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RenderResult:
    """Result of rendering BookIR to unpacked OEBPS tree."""

    oebps_dir: Path
    manifest: RenderManifest
    source_page_count: int
    xhtml_part_count: int
    figure_count: int
    chart_count: int
    table_count: int
    # Legacy aggregate: CodeBlock plus every PreformattedBlock subtype.
    # Detailed semantic component counts live in ``component_counts``.
    code_count: int
    math_count: int
    fallback_count: int
    warning_count: int
    presentation_mode: str = "legacy"
    style_profile_hash: str | None = None
    component_counts: dict[str, int] = field(default_factory=dict)
    rendered_ir: "BookIR | None" = None
