"""Data models for ingest manifest and page metadata."""

from pydantic import BaseModel, Field


class PageManifestItem(BaseModel):
    """Metadata for an individual page image in the ingest manifest."""

    page_index: int = Field(description="Zero-based natural sort index")
    filename: str = Field(description="Image file name")
    relative_path: str = Field(description="Path relative to source directory")
    sha256: str = Field(description="Hex SHA-256 hash of image file")
    byte_size: int = Field(description="File size in bytes")
    width: int = Field(description="Image width in pixels")
    height: int = Field(description="Image height in pixels")
    suffix: str = Field(description="Normalized lowercase file extension (e.g. .jpg)")
    aspect_ratio: float = Field(description="Width / Height ratio")
    is_duplicate: bool = Field(default=False, description="True if byte-identical page detected")
    extreme_aspect_ratio: bool = Field(
        default=False, description="True if aspect ratio < 0.35 or > 2.0"
    )


class IngestManifest(BaseModel):
    """Complete manifest of ingested pages for a conversion job."""

    schema_version: str = Field(default="1.0", description="Ingest manifest schema version")
    source_dir: str = Field(description="Original input directory string")
    total_pages: int = Field(description="Number of valid page images")
    pages: list[PageManifestItem] = Field(default_factory=list, description="Ordered page list")
    duplicate_count: int = Field(default=0, description="Count of duplicate pages detected")
    warnings: list[str] = Field(default_factory=list, description="Warnings logged during ingest")
