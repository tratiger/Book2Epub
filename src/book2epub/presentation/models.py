"""Presentation models and finite token schemas for BookStyleProfile (M10)."""

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PageMargin = Literal["compact", "standard", "generous"]
LineHeight = Literal["compact", "normal", "relaxed"]
ParagraphGap = Literal["none", "tight", "normal", "open"]
FirstLineIndent = Literal["none", "small", "medium"]
TextAlign = Literal["start", "justify"]

HeadingScale = Literal["s", "m", "l", "xl", "xxl"]
HeadingWeight = Literal["semibold", "bold"]
HeadingAlignment = Literal["start", "center"]
HeadingRule = Literal["none", "bottom_thin", "bottom_medium", "accent_left"]
HeadingSpaceBefore = Literal["m", "l", "xl", "xxl"]
HeadingSpaceAfter = Literal["s", "m", "l", "xl"]

PreTheme = Literal["plain", "subtle", "dark", "outline"]
PreBorder = Literal["none", "thin", "accent_left"]
PrePadding = Literal["s", "m", "l"]
PreRadius = Literal["none", "small"]
PreFontScale = Literal["small", "normal"]
PreLineHeight = Literal["compact", "normal"]
PreWrap = Literal["soft", "preserve"]

InlineCodeBackground = Literal["none", "subtle"]
InlineCodeBorder = Literal["none", "thin"]
InlineCodePadding = Literal["none", "xs"]
InlineCodeFontScale = Literal["normal", "small"]

CalloutVariant = Literal["plain", "accent_left", "boxed"]
CalloutAccent = Literal["neutral", "blue", "teal", "amber", "red"]
CalloutSpacing = Literal["tight", "normal", "open"]

TableRules = Literal["full", "horizontal", "minimal"]
TableHeaderEmphasis = Literal["none", "subtle", "strong"]
TableCellPadding = Literal["compact", "normal", "generous"]
TableFontScale = Literal["small", "normal"]
TableCaptionAlign = Literal["start", "center"]

FigureSpacing = Literal["tight", "normal", "open"]
FigureCaptionAlign = Literal["start", "center"]
FigureCaptionScale = Literal["small", "normal"]
FigureCaptionPosition = Literal["after", "before"]

ListItemSpacing = Literal["compact", "normal", "open"]
ListIndent = Literal["compact", "normal", "generous"]
ListUnorderedMarker = Literal["disc", "circle", "square", "dash"]
ListOrderedMarker = Literal["decimal", "lower_alpha", "lower_roman"]

QuoteVariant = Literal["indent", "accent_left", "boxed"]
QuoteFontStyle = Literal["normal", "italic"]
QuoteSpacing = Literal["normal", "open"]


class BodyStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_margin: PageMargin = "standard"
    line_height: LineHeight = "normal"
    paragraph_gap: ParagraphGap = "normal"
    first_line_indent: FirstLineIndent = "none"
    text_align: TextAlign = "start"


class HeadingStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scale: HeadingScale = "l"
    weight: HeadingWeight = "bold"
    alignment: HeadingAlignment = "start"
    rule: HeadingRule = "none"
    space_before: HeadingSpaceBefore = "l"
    space_after: HeadingSpaceAfter = "m"
    chapter_break_before: bool = False


class HeadingStyles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    h1: HeadingStyle
    h2: HeadingStyle
    h3: HeadingStyle
    h4: HeadingStyle
    h5_6: HeadingStyle


class InlineCodeStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background: InlineCodeBackground = "subtle"
    border: InlineCodeBorder = "none"
    padding: InlineCodePadding = "xs"
    font_scale: InlineCodeFontScale = "small"


class PreStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: PreTheme = "subtle"
    border: PreBorder = "accent_left"
    padding: PrePadding = "m"
    radius: PreRadius = "small"
    font_scale: PreFontScale = "small"
    line_height: PreLineHeight = "compact"
    wrap: PreWrap = "soft"


class CalloutStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant: CalloutVariant = "accent_left"
    accent: CalloutAccent = "neutral"
    spacing: CalloutSpacing = "normal"
    show_label: bool = False


class CalloutStyles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: CalloutStyle
    tip: CalloutStyle
    warning: CalloutStyle
    caution: CalloutStyle
    important: CalloutStyle
    sidebar: CalloutStyle


class TableStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: TableRules = "horizontal"
    header_emphasis: TableHeaderEmphasis = "subtle"
    cell_padding: TableCellPadding = "normal"
    font_scale: TableFontScale = "normal"
    caption_align: TableCaptionAlign = "start"


class FigureStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spacing: FigureSpacing = "normal"
    caption_align: FigureCaptionAlign = "start"
    caption_scale: FigureCaptionScale = "small"
    caption_position: FigureCaptionPosition = "after"


class ListStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_spacing: ListItemSpacing = "normal"
    indent: ListIndent = "normal"
    unordered_marker: ListUnorderedMarker = "disc"
    ordered_marker: ListOrderedMarker = "decimal"


class QuoteStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant: QuoteVariant = "accent_left"
    font_style: QuoteFontStyle = "normal"
    spacing: QuoteSpacing = "normal"


_py_list = list


class BookStyleProfile(BaseModel):
    """Reflow styling profile for Book2Epub composed exclusively of finite tokens."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    body: BodyStyle
    headings: HeadingStyles
    inline_code: InlineCodeStyle
    source_code: PreStyle
    terminal: PreStyle
    log: PreStyle
    config: PreStyle
    callout: CalloutStyles
    table: TableStyle
    figure: FigureStyle
    list: ListStyle
    quote: QuoteStyle

    # Profile metadata
    mode_source: Literal["enhanced_default", "inferred"] = "enhanced_default"
    provider: str | None = None
    model: str | None = None
    request_id: str | None = None
    confidence: float = 1.0
    representative_page_indices: _py_list[int] = Field(default_factory=_py_list)


class BookStyleProfileDecision(BaseModel):
    """Structured Output response model for style profile inference (M10/Appendix L15)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    profile: BookStyleProfile
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_page_indices: list[int] = Field(default_factory=list)
    uncertainty_codes: list[str] = Field(default_factory=list)


def compute_profile_hash(profile: BookStyleProfile) -> str:
    """Compute deterministic SHA-256 hash of profile visual choices (excluding volatile fields)."""
    data = profile.model_dump(
        exclude={
            "mode_source",
            "provider",
            "model",
            "request_id",
            "confidence",
            "representative_page_indices",
        }
    )
    import json
    canonical = json.dumps(data, sort_keys=True)
    return sha256(canonical.encode("utf-8")).hexdigest()
