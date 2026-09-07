"""Asset registry and media type resolution for BookIR."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from book2epub.errors import IRError
from book2epub.ir.models import Asset
from book2epub.util.hashing import file_sha256

logger = logging.getLogger(__name__)

MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


@dataclass
class AssetRegistry:
    """Registry that tracks and deduplicates external assets."""

    assets: dict[str, Asset] = field(default_factory=dict)
    _hash_to_id: dict[str, str] = field(default_factory=dict)

    def register_asset(
        self,
        source_path: Path,
        role: Literal["figure", "chart", "table-fallback", "equation-fallback", "cover"],
    ) -> str:
        """
        Register a content asset from disk, deduplicating by SHA-256.

        Returns the asset_id.
        """
        if not source_path.is_file():
            raise IRError(f"Asset file not found on disk: {source_path}")

        # Compute hash
        sha = file_sha256(source_path)
        if sha in self._hash_to_id:
            return self._hash_to_id[sha]

        ext = source_path.suffix.lower()
        media_type = MIME_TYPES.get(ext)
        if not media_type:
            raise IRError(f"Unsupported asset image format '{ext}' for file: {source_path}")

        byte_size = source_path.stat().st_size
        width: int | None = None
        height: int | None = None

        if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            try:
                with Image.open(source_path) as img:
                    width, height = img.size
            except Exception as e:
                logger.warning("Could not read dimensions for asset %s: %s", source_path, e)

        asset_id = f"asset-{sha[:16]}"
        asset = Asset(
            asset_id=asset_id,
            source_path=source_path,
            media_type=media_type,
            sha256=sha,
            byte_size=byte_size,
            width=width,
            height=height,
            role=role,
        )

        self.assets[asset_id] = asset
        self._hash_to_id[sha] = asset_id
        return asset_id

    def register_existing(self, asset: Asset) -> None:
        """Register an existing Asset object."""
        self.assets[asset.asset_id] = asset
        self._hash_to_id[asset.sha256] = asset.asset_id

    def get_asset(self, asset_id: str) -> Asset | None:
        """Retrieve an asset by ID."""
        return self.assets.get(asset_id)

    def list_assets(self) -> list[Asset]:
        """List all registered assets in deterministic ID order."""
        return [self.assets[k] for k in sorted(self.assets.keys())]
