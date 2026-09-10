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
    css_classes: set[str] = set()
    if css_path.is_file():
        css_content = css_path.read_text(encoding="utf-8")
        lowered = css_content.lower()
        if "position: absolute" in lowered or "position:absolute" in lowered:
            violations.append("book.css contains forbidden 'position: absolute'")
        # Extract declared classes for coverage
        css_classes = set(re.findall(r"\.([a-zA-Z0-9_\-]+)", css_content))

    # 2. XHTML Invariant Checks (No JS, No Remote Resources, Duplicate Markers, Components)
    text_dir = oebps_dir / "text"
    dup_markers_count = 0
    total_semantic_components = 0
    styled_semantic_components = 0

    known_preformatted_classes = {
        "source-code",
        "shell-command",
        "terminal-output",
        "terminal-session",
        "repl-session",
        "log-output",
        "config-file",
        "generic-preformatted",
        "code-block",
        "preformatted",
    }

    if text_dir.is_dir():
        for xhtml_file in text_dir.glob("*.xhtml"):
            try:
                tree = etree.parse(str(xhtml_file))
                root = tree.getroot()

                # Check no script tags
                for script in root.iter("{http://www.w3.org/1999/xhtml}script"):
                    violations.append(f"Forbidden <script> tag detected in {xhtml_file.name}")

                # Check no remote resources in href or src (offline EPUB requirement)
                for elem in root.iter():
                    for attr in ("src", "href"):
                        val = elem.attrib.get(attr)
                        if val and val.startswith(("http://", "https://", "//", "ftp://")):
                            violations.append(
                                f"Forbidden remote resource reference '{val}' in {xhtml_file.name}"
                            )
                    # Check inline style for forbidden absolute positioning
                    style_attr = elem.attrib.get("style", "").lower()
                    if "position: absolute" in style_attr or "position:absolute" in style_attr:
                        violations.append(
                            f"Forbidden inline 'position: absolute' detected in {xhtml_file.name}"
                        )

                # Check list duplicate markers
                for li in root.iter("{http://www.w3.org/1999/xhtml}li"):
                    li_text = "".join(li.itertext()).strip()
                    if _DUPLICATE_MARKER_PATTERN.match(li_text):
                        dup_markers_count += 1
                        violations.append(
                            f"Duplicate list marker detected in {xhtml_file.name}: '{li_text[:30]}'"
                        )

                # Check preformatted subtype classes and semantic component coverage
                for pre in root.iter("{http://www.w3.org/1999/xhtml}pre"):
                    total_semantic_components += 1
                    cls = pre.attrib.get("class", "")
                    classes = set(cls.split())
                    if classes & css_classes:
                        styled_semantic_components += 1
                    if mode in ("enhanced", "infer"):
                        if not (classes & known_preformatted_classes):
                            violations.append(
                                f"Preformatted element in {xhtml_file.name} lacks "
                                f"expected subtype class"
                            )

                # Check figure/callout/aside components
                for tag in ("figure", "table", "aside", "blockquote"):
                    for comp in root.iter(f"{{http://www.w3.org/1999/xhtml}}{tag}"):
                        total_semantic_components += 1
                        cls = comp.attrib.get("class", "")
                        classes = set(cls.split())
                        if tag in css_classes or (classes & css_classes):
                            styled_semantic_components += 1

                for div in root.iter("{http://www.w3.org/1999/xhtml}div"):
                    cls = div.attrib.get("class", "")
                    classes = set(cls.split())
                    if any("callout" in c or "example" in c or "exercise" in c for c in classes):
                        total_semantic_components += 1
                        if classes & css_classes:
                            styled_semantic_components += 1

                # Check image responsiveness and alt presence
                for img in root.iter("{http://www.w3.org/1999/xhtml}img"):
                    alt = img.attrib.get("alt")
                    if alt is None:
                        violations.append(
                            f"Image in {xhtml_file.name} lacks required 'alt' attribute"
                        )

            except Exception as e:
                violations.append(f"Failed to parse XHTML file {xhtml_file.name}: {e}")

    metrics.list_duplicate_marker_count = dup_markers_count
    if total_semantic_components > 0:
        metrics.component_style_coverage = round(
            styled_semantic_components / total_semantic_components, 4
        )
    else:
        metrics.component_style_coverage = 1.0

    return metrics, violations
