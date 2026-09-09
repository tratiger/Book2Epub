"""Unit tests for OCR QA metrics and safety invariants (M12/Appendix N5)."""

import json
from pathlib import Path

from book2epub.qa.ocr import evaluate_ocr_qa


def test_ocr_qa_mode_off_clean(tmp_path: Path) -> None:
    """Verify OCR mode 'off' returns 0 applied and 0 violations."""
    metrics, violations = evaluate_ocr_qa(None, cfg_mode="off")
    assert metrics.ocr_mode == "off"
    assert metrics.ocr_applied_count == 0
    assert len(violations) == 0


def test_ocr_qa_detects_invariants(tmp_path: Path) -> None:
    """Verify OCR QA flags applied proposals in 'off' mode or modifications to math text."""
    corrections_file = tmp_path / "ocr-corrections.json"
    data = {
        "budget_exceeded": False,
        "proposals": [
            {
                "proposal_id": "prop-1",
                "block_id": "b-1",
                "original_text": "foo",
                "proposed_text": "bar",
                "application_status": "applied",
                "category": "safe",
            },
            {
                "proposal_id": "prop-2",
                "block_id": "b-math",
                "original_text": "x = 1",
                "proposed_text": "x = 2",
                "source_span_type": "inline_math",
                "application_status": "applied",
                "category": "sensitive",
            },
        ],
    }
    corrections_file.write_text(json.dumps(data), encoding="utf-8")

    # Mode "off" should flag applied proposal
    metrics_off, violations_off = evaluate_ocr_qa(corrections_file, cfg_mode="off")
    assert any("OCR mode is off but proposal" in v for v in violations_off)
    assert any("Math text was illegally modified" in v for v in violations_off)
    assert metrics_off.ocr_applied_count == 2
    assert metrics_off.ocr_sensitive_confirmation_count == 1
