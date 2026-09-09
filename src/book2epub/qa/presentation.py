"""Presentation and component rendering QA metrics and invariant assertions (M12/Appendix N6)."""

import re
from pathlib import Path

from lxml import etree

from book2epub.presentation.models import BookStyleProfile
from book2epub.qa.models import PresentationQAMetrics
from book2epub.render.models import RenderManifest

# Detect obvious duplicate list marker prefixes at start of rendered <li> text
_DUPLICATE_MARKER_PATTERN = re.compile(
    r"^[ \t]*([•●○◦▪■□‣・*+–—]|-(?!\d))[ \t]*([•●○◦▪■□‣・*+–—]|-(?!\d)|\(\d+\))[ \t]+"
)


def evaluate_presentation_qa(
    oebps_dir: Path,
    manifest: RenderManifest | None = None,
    profile: BookStyleProfile | None = None,
    mode: str = "legacy",
) -> tuple[PresentationQAMetrics, list[str]]:
    """
    Evaluate presentation quality metrics and assert structural EPUB 3.3 invariants.
    Returns (metrics, violation_warnings).
    """
    metrics = PresentationQAMetrics(
        presentation_mode=mode,
        style_profile_hash=manifest.style_profile_hash if manifest else None,
    )
    violations: list[str] = []

    if manifest:
        metrics.component_counts = dict(manifest.component_counts)

    if profile:
        metrics.style_inference_confidence = profile.confidence
        metrics.style_inference_fallback = profile.mode_source == "enhanced_default"

    # 1. CSS Invariant Checks
    css_path = oebps_dir / "styles" / "book.css"
    if css_path.is_file():
        lowered = css_path.read_text(encoding="utf-8").lower()
        if "position: absolute" in lowered or "position:absolute" in lowered:
            violations.append("book.css contains forbidden 'position: absolute'")

    # 2. XHTML Invariant Checks (No JavaScript, No Duplicate List Markers)
    text_dir = oebps_dir / "text"
    dup_markers_count = 0

    if text_dir.is_dir():
        for xhtml_file in text_dir.glob("*.xhtml"):
            try:
                tree = etree.parse(str(xhtml_file))
                root = tree.getroot()

                # Check no script tags
                for script in root.iter("{http://www.w3.org/1999/xhtml}script"):
                    violations.append(f"Forbidden <script> tag detected in {xhtml_file.name}")

                # Check list duplicate markers
                for li in root.iter("{http://www.w3.org/1999/xhtml}li"):
                    li_text = "".join(li.itertext()).strip()
                    if _DUPLICATE_MARKER_PATTERN.match(li_text):
                        dup_markers_count += 1
                        violations.append(
                            f"Duplicate list marker detected in {xhtml_file.name}: '{li_text[:30]}'"
                        )

            except Exception as e:
                violations.append(f"Failed to parse XHTML file {xhtml_file.name}: {e}")

    metrics.list_duplicate_marker_count = dup_markers_count
    return metrics, violations
