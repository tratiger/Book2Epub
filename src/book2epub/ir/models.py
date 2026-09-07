"""Data models for Book2Epub Intermediate Representation (BookIR)."""

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """Bounding box coordinates [x0, y0, x1, y1] on the source page."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0


class SourceRef(BaseModel):
    """Provenance tracking link back to source page image coordinates."""

    page_idx: int
    bbox: BBox | None = None
    source_type: str
    source_index: int | None = None
    line_bboxes: list[BBox] = Field(default_factory=list)
    span_bboxes: list[BBox] = Field(default_factory=list)
    raw_extensions: dict[str, Any] = Field(default_factory=dict)


class LayoutHint(BaseModel):
    """Deterministic layout intent derived from source bbox without absolute positioning."""

    width_ratio: float
    size_class: Literal["small", "medium", "large"]
    alignment: Literal["left", "center", "right"]
    source_bbox: BBox | None = None


class Asset(BaseModel):
    """External content resource (figure, chart, fallback table/math image)."""

    asset_id: str = Field(description="Deterministic ID, e.g. sha256:<hex>")
    source_path: Path = Field(description="Path to local image file on disk")
    media_type: str = Field(description="MIME media type, e.g. image/png")
    sha256: str = Field(description="Hex SHA-256 hash of image content")
    byte_size: int = Field(description="Size in bytes")
    width: int | None = None
    height: int | None = None
    role: Literal[
        "figure", "chart", "table-fallback", "equation-fallback", "cover"
    ] = Field(description="Role of asset in publication")

    @property
    def id(self) -> str:
        return self.asset_id

    @property
    def rel_path(self) -> str:
        return f"images/{self.source_path.name}"

    @property
    def local_path(self) -> Path:
        return self.source_path


class InlineBase(BaseModel):
    """Base class for all inline nodes."""

    sources: list[SourceRef] = Field(default_factory=list)


class Text(InlineBase):
    kind: Literal["text"] = "text"
    text: str


class InlineMath(InlineBase):
    kind: Literal["inline_math"] = "inline_math"
    latex: str
    fallback_asset_id: str | None = None
    mathml: str | None = None


class Hyperlink(InlineBase):
    kind: Literal["hyperlink"] = "hyperlink"
    url: str
    children: list["Inline"] = Field(default_factory=list)


class LineBreak(InlineBase):
    kind: Literal["line_break"] = "line_break"


class PageBoundary(InlineBase):
    """Source-page boundary inside a merged paragraph."""

    kind: Literal["page_boundary"] = "page_boundary"
    page_idx: int
    label: str | None = None


Inline = Annotated[
    Text | InlineMath | Hyperlink | LineBreak | PageBoundary,
    Field(discriminator="kind"),
]


class BlockBase(BaseModel):
    """Base class for all structural block nodes."""

    id: str = Field(description="Stable publication-unique node ID")
    sources: list[SourceRef] = Field(default_factory=list)


class Heading(BlockBase):
    kind: Literal["heading"] = "heading"
    level: int | None = None
    inlines: list[Inline] = Field(default_factory=list)


class Paragraph(BlockBase):
    kind: Literal["paragraph"] = "paragraph"
    inlines: list[Inline] = Field(default_factory=list)


class Figure(BlockBase):
    kind: Literal["figure"] = "figure"
    asset_id: str
    caption: list[Inline] = Field(default_factory=list)
    footnotes: list[Inline] = Field(default_factory=list)
    layout_hint: LayoutHint | None = None
    description: str | None = None


class Chart(BlockBase):
    kind: Literal["chart"] = "chart"
    asset_id: str
    caption: list[Inline] = Field(default_factory=list)
    footnotes: list[Inline] = Field(default_factory=list)
    layout_hint: LayoutHint | None = None
    description: str | None = None


class Table(BlockBase):
    kind: Literal["table"] = "table"
    html: str
    fallback_asset_id: str | None = None
    caption: list[Inline] = Field(default_factory=list)
    footnotes: list[Inline] = Field(default_factory=list)
    layout_hint: LayoutHint | None = None


class CodeBlock(BlockBase):
    kind: Literal["code"] = "code"
    text: str
    subtype: Literal["code", "algorithm"] = "code"
    caption: list[Inline] = Field(default_factory=list)
    footnotes: list[Inline] = Field(default_factory=list)
    language: str | None = None


class DisplayMath(BlockBase):
    kind: Literal["display_math"] = "display_math"
    latex: str
    fallback_asset_id: str | None = None
    mathml: str | None = None


class ListBlock(BlockBase):
    kind: Literal["list"] = "list"
    ordered: bool | None = None
    items: list[list[Inline]] = Field(default_factory=list)
    subtype: str | None = None


class Aside(BlockBase):
    kind: Literal["aside"] = "aside"
    inlines: list[Inline] = Field(default_factory=list)
    subtype: str = "aside"


class Footnote(BlockBase):
    kind: Literal["footnote"] = "footnote"
    inlines: list[Inline] = Field(default_factory=list)
    scope: Literal["page", "figure", "table", "code"] = "page"


class IndexBlock(BlockBase):
    kind: Literal["index"] = "index"
    items: list[list[Inline]] = Field(default_factory=list)


class PageBreak(BlockBase):
    kind: Literal["page_break"] = "page_break"
    page_idx: int
    label: str | None = None


class UnknownBlock(BlockBase):
    kind: Literal["unknown"] = "unknown"
    source_type: str
    extracted_text: str | None = None
    asset_id: str | None = None


Block = Annotated[
    (
        Heading
        | Paragraph
        | Figure
        | Chart
        | Table
        | CodeBlock
        | DisplayMath
        | ListBlock
        | Aside
        | Footnote
        | IndexBlock
        | PageBreak
        | UnknownBlock
    ),
    Field(discriminator="kind"),
]


class SourcePage(BaseModel):
    """Metadata for one source page."""

    page_idx: int
    width: float
    height: float
    printed_label: str | None = None
    printed_label_confidence: float = 0.0


class SourceDocument(BaseModel):
    """Metadata for the entire source document as recognized by MinerU."""

    mineru_version: str = "3.4.5"
    mineru_backend: str = "hybrid"
    mineru_effort: str | None = "high"
    source_pdf_sha256: str | None = None
    page_count: int
    pages: list[SourcePage] = Field(default_factory=list)


class BookMetadata(BaseModel):
    """Metadata for publication."""

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    language: str = "auto"
    identifier: str | None = None
    publisher: str | None = None
    cover_image_id: str | None = None


class IRWarning(BaseModel):
    """Warning recorded during BookIR parsing and normalization."""

    code: str
    message: str
    page_idx: int | None = None
    severity: Literal["info", "warning", "error"] = "warning"
    details: dict[str, Any] = Field(default_factory=dict)


class BookIR(BaseModel):
    """Root model for Book2Epub Intermediate Representation."""

    schema_version: str = "1.0"
    source: SourceDocument
    metadata: BookMetadata = Field(default_factory=BookMetadata)
    blocks: list[Block] = Field(default_factory=list)
    assets: dict[str, Asset] = Field(default_factory=dict)
    warnings: list[IRWarning] = Field(default_factory=list)
