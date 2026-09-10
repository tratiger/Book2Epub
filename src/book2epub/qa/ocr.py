"""OCR correction quality metrics and release safety invariants (M12/Appendix N5)."""

import json
import logging
from pathlib import Path
from typing import Any

from book2epub.qa.models import OCRQAMetrics
from book2epub.visual.models import OCRCorrectionAuditFile
from book2epub.visual.validation import calculate_changed_codepoints, is_sensitive_change

logger = logging.getLogger(__name__)


def evaluate_ocr_qa(
    ocr_corrections_path: Path | None,
    cfg_mode: str = "off",
) -> tuple[OCRQAMetrics, list[str]]:
    """
    Evaluate OCR correction metrics and assert safety invariants.
    Supports authoritative OCRCorrectionAuditFile schema with legacy fallback.
    Returns (metrics, violation_warnings).
    """
    metrics = OCRQAMetrics(ocr_mode=cfg_mode)
    violations: list[str] = []

    if not ocr_corrections_path or not ocr_corrections_path.is_file():
        return metrics, violations

    try:
        data = json.loads(ocr_corrections_path.read_text(encoding="utf-8"))
    except Exception as e:
        violations.append(f"Failed to parse ocr-corrections.json: {e}")
        return metrics, violations

    # 1. Authoritative OCRCorrectionAuditFile schema
    if isinstance(data, dict) and "audits" in data:
        try:
            audit_file = OCRCorrectionAuditFile.model_validate(data)
        except Exception as e:
            violations.append(f"OCRCorrectionAuditFile schema validation failed: {e}")
            return metrics, violations

        metrics.eligible_segment_count = audit_file.eligible_segment_count
        metrics.ocr_candidate_count = audit_file.candidate_count
        metrics.ocr_proposal_count = len(audit_file.audits)
        metrics.ocr_applied_count = audit_file.applied_count
        metrics.ocr_rejected_count = audit_file.rejected_count
        metrics.ocr_changed_codepoints = audit_file.changed_codepoints
        metrics.ocr_budget_exceeded = audit_file.budget_exceeded
        if audit_file.total_codepoints > 0:
            metrics.ocr_changed_fraction = (
                audit_file.changed_codepoints / audit_file.total_codepoints
            )

        # Invariant: OCR mode recorded in audit must match configured mode
        if audit_file.mode != cfg_mode:
            violations.append(
                f"OCR correction audit mode mismatch: file recorded '{audit_file.mode}', "
                f"expected configured mode '{cfg_mode}'"
            )

        # Invariant: candidate count == applied + rejected == len(audits)
        if audit_file.candidate_count != audit_file.applied_count + audit_file.rejected_count:
            violations.append(
                f"Candidate count ({audit_file.candidate_count}) != applied "
                f"({audit_file.applied_count}) + rejected ({audit_file.rejected_count})"
            )
        if len(audit_file.audits) != audit_file.candidate_count:
            violations.append(
                f"Audits count ({len(audit_file.audits)}) != candidate count "
                f"({audit_file.candidate_count})"
            )

        # Invariant: budget exceeded flag
        if audit_file.budget_exceeded:
            violations.append("OCR edit budget was exceeded during correction stage")

        actual_changed_cps = 0
        from book2epub.semantic.hashing import compute_text_sha256

        for a in audit_file.audits:
            if a.confirmation_result is not None:
                if a.status == "applied":
                    metrics.ocr_sensitive_confirmation_count += 1
                else:
                    metrics.ocr_confirmation_disagreement_count += 1

            # Invariant: mode == "off" must never apply
            if cfg_mode == "off" and a.status == "applied":
                violations.append(
                    f"OCR mode is off but proposal for block '{a.block_id}' was applied"
                )

            if a.status == "applied":
                # Compute changed codepoints using authoritative SequenceMatcher logic
                diff = calculate_changed_codepoints(a.old_text, a.new_text)
                actual_changed_cps += diff

                # Hash resolution check
                if compute_text_sha256(a.old_text) != a.old_sha256:
                    violations.append(
                        f"Applied OCR proposal old text SHA-256 mismatch "
                        f"for segment '{a.segment_id}'"
                    )
                if compute_text_sha256(a.new_text) != a.new_sha256:
                    violations.append(
                        f"Applied OCR proposal new text SHA-256 mismatch "
                        f"for segment '{a.segment_id}'"
                    )

                # Visual bbox/page evidence check
                if not a.bbox or len(a.bbox) < 4 or a.page_idx < 0:
                    violations.append(
                        f"Applied OCR proposal for segment '{a.segment_id}' "
                        f"lacks visual bbox/page evidence"
                    )

                # Math source text is immutable
                if (
                    a.content_role == "math"
                    or "math" in a.block_id.lower()
                    or "math" in a.segment_id.lower()
                ):
                    violations.append(
                        f"Math text was illegally modified by OCR proposal for block '{a.block_id}'"
                    )

                # Table HTML is immutable
                is_table = a.content_role == "table" or "table" in a.block_id.lower()
                is_caption_or_fn = (
                    a.content_role in ("caption", "footnote")
                    or "caption" in a.segment_id.lower()
                    or "fn" in a.segment_id.lower()
                )
                if (a.content_role == "table") or (is_table and not is_caption_or_fn):
                    violations.append(
                        f"Table HTML was illegally modified by OCR proposal "
                        f"for block '{a.block_id}'"
                    )

                # Sensitive / code confirmation check
                is_code = a.content_role in ("code_body", "preformatted_body")
                is_sensitive = is_sensitive_change(
                    a.old_text, a.new_text, is_code_or_preformatted=is_code
                )
                needs_conf = is_sensitive or is_code
                if needs_conf:
                    if a.confirmation_result is not True:
                        violations.append(
                            f"Sensitive OCR proposal for segment '{a.segment_id}' "
                            f"was applied without confirmation_result=True"
                        )
                    if a.first_confidence < 0.995:
                        violations.append(
                            f"Sensitive OCR proposal for segment '{a.segment_id}' "
                            f"was applied with first_confidence={a.first_confidence} < 0.995"
                        )
                    if a.confirmation_confidence is None or a.confirmation_confidence < 0.995:
                        violations.append(
                            f"Sensitive OCR proposal for segment '{a.segment_id}' "
                            f"was applied with "
                            f"confirmation_confidence={a.confirmation_confidence} < 0.995"
                        )
                    if a.confirmation_observed_text != a.new_text:
                        violations.append(
                            f"Sensitive OCR proposal for segment '{a.segment_id}' "
                            f"was applied with mismatched confirmation text: "
                            f"'{a.confirmation_observed_text}' != '{a.new_text}'"
                        )
                elif a.confirmation_result is not None and a.confirmation_result is False:
                    violations.append(
                        f"OCR proposal for segment '{a.segment_id}' "
                        f"was applied despite confirmation disagreement"
                    )

        # Changed codepoints accuracy check
        if audit_file.changed_codepoints != actual_changed_cps:
            violations.append(
                f"Changed codepoints calculation mismatch: recorded "
                f"{audit_file.changed_codepoints} != actual {actual_changed_cps}"
            )

        return metrics, violations

    # 2. Legacy schema support (e.g. dict with "proposals")
    proposals: list[dict[str, Any]] = (
        data.get("proposals", []) if isinstance(data, dict) else []
    )
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
            diff = calculate_changed_codepoints(old_t, new_t)
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
    metrics.ocr_budget_exceeded = (
        data.get("budget_exceeded", False) if isinstance(data, dict) else False
    )

    return metrics, violations


