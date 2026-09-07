"""MathML conversion and fallback handler using latex2mathml."""

import logging
from typing import NamedTuple

import latex2mathml.converter
from lxml import etree

logger = logging.getLogger(__name__)

MATHML_NS = "http://www.w3.org/1998/Math/MathML"


class MathConvertResult(NamedTuple):
    """Result of converting LaTeX to MathML or fallback."""

    success: bool
    mathml_element: etree._Element | None
    fallback_latex: str
    error_message: str | None = None


def normalize_latex(latex: str) -> str:
    """Strip surrounding delimiters ($$, $, \\[, \\]) and outer whitespace."""
    s = latex.strip()
    if s.startswith("$$") and s.endswith("$$") and len(s) >= 4:
        s = s[2:-2].strip()
    elif s.startswith("$") and s.endswith("$") and len(s) >= 2:
        s = s[1:-1].strip()
    elif s.startswith("\\[") and s.endswith("\\]") and len(s) >= 4:
        s = s[2:-2].strip()
    elif s.startswith("\\(") and s.endswith("\\)") and len(s) >= 4:
        s = s[2:-2].strip()
    return s


def convert_latex_to_mathml(latex: str, display_block: bool = False) -> MathConvertResult:
    """
    Convert a LaTeX string into an lxml MathML Element.

    Returns MathConvertResult with success=True and mathml_element on success,
    or success=False with normalized latex and error message on failure.
    """
    clean_latex = normalize_latex(latex)
    if not clean_latex:
        return MathConvertResult(
            success=False,
            mathml_element=None,
            fallback_latex="",
            error_message="Empty equation content",
        )

    disp = "block" if display_block else "inline"
    try:
        mathml_str = latex2mathml.converter.convert(clean_latex, display=disp)
        # Parse result into lxml Element to guarantee valid XML and proper namespace
        mathml_elem = etree.fromstring(mathml_str.encode("utf-8"))

        # Verify root tag is MathML
        tag_str = str(mathml_elem.tag)
        if not (tag_str == f"{{{MATHML_NS}}}math" or tag_str == "math"):
            raise ValueError(f"Unexpected root tag in MathML: {tag_str}")

        # Ensure xmlns is set to MATHML_NS
        if not tag_str.startswith("{"):
            mathml_elem.tag = f"{{{MATHML_NS}}}{tag_str}"

        return MathConvertResult(
            success=True,
            mathml_element=mathml_elem,
            fallback_latex=clean_latex,
        )
    except Exception as e:
        logger.warning("latex2mathml conversion failed for '%s': %s", clean_latex[:50], e)
        return MathConvertResult(
            success=False,
            mathml_element=None,
            fallback_latex=clean_latex,
            error_message=str(e),
        )
