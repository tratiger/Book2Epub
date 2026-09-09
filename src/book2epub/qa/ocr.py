"""OCR correction quality metrics and release safety invariants (M12/Appendix N5)."""

import json
from pathlib import Path
from typing import Any

from book2epub.qa.models import OCRQAMetrics


def evaluate_ocr_qa(
    ocr_corrections_path: Path | None,
    cfg_mode: str = "off",
) -> tuple[OCRQAMetrics, list[str]]:
    """
    Evaluate OCR correction metrics and assert safety invariants.
    Returns (metrics, violation_warnings).
    """
    metrics = OCRQAMetrics(ocr_mode=cfg_mode)
    violations: list[str] = []

    if not ocr_corrections_path or not ocr_corrections_path.is_file():
        if cfg_mode == "off":
            return metrics, violations
        return metrics, violations

    try:
        data = json.loads(ocr_corrections_path.read_text(encoding="utf-8"))
    except Exception as e:
        violations.append(f"Failed to parse ocr-corrections.json: {e}")
        return metrics, violations

    proposals: list[dict[str, Any]] = data.get("proposals", [])
    metrics.ocr_proposal_count = len(proposals)

    applied_count = 0
    rejected_count = 0
    changed_cps = 0
    sensitive_conf = 0
    sensitive_disagree = 0

    for p in proposals:
        status = p.get("application_status")
        is_applied = status == "applied"
        if is_applied:
            applied_count += 1
            old_t = p.get("original_text", "")
            new_t = p.get("proposed_text", "")
            diff = abs(len(new_t) - len(old_t)) + sum(
                1 for a, b in zip(old_t, new_t, strict=False) if a != b
            )
            changed_cps += diff

            # Invariant: mode == "off" must never apply
            if cfg_mode == "off":
                violations.append(
                    f"OCR mode is off but proposal for block '{p.get('block_id')}' was applied"
                )

            # Invariant: math source text is immutable
            if p.get("source_span_type") in ("inline_math", "display_math", "equation"):
                violations.append(
                    f"Math text was illegally modified by OCR proposal '{p.get('proposal_id')}'"
                )

        else:
            rejected_count += 1

        if p.get("category") == "sensitive":
            if is_applied:
                sensitive_conf += 1
            else:
                sensitive_disagree += 1

    metrics.ocr_applied_count = applied_count
    metrics.ocr_rejected_count = rejected_count
    metrics.ocr_sensitive_confirmation_count = sensitive_conf
    metrics.ocr_confirmation_disagreement_count = sensitive_disagree
    metrics.ocr_changed_codepoints = changed_cps
    metrics.ocr_budget_exceeded = data.get("budget_exceeded", False)

    return metrics, violations
