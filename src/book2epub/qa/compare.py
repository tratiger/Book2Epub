"""Job comparison tool comparing QA report JSON between two conversion runs (M12 Section 15)."""

import json
from pathlib import Path
from typing import Any


def compare_qa_reports(
    report_a_path: Path,
    report_b_path: Path,
) -> dict[str, Any]:
    """
    Compare two QA reports (JSON) and produce an objective structural difference summary.
    """
    data_a = json.loads(report_a_path.read_text(encoding="utf-8"))
    data_b = json.loads(report_b_path.read_text(encoding="utf-8"))

    env_a = data_a.get("environment", {})
    env_b = data_b.get("environment", {})

    epubcheck_a = data_a.get("epubcheck_validation", {})
    epubcheck_b = data_b.get("epubcheck_validation", {})

    sem_a = data_a.get("semantic_metrics") or {}
    sem_b = data_b.get("semantic_metrics") or {}

    ocr_a = data_a.get("ocr_metrics") or {}
    ocr_b = data_b.get("ocr_metrics") or {}

    pres_a = data_a.get("presentation_metrics") or {}
    pres_b = data_b.get("presentation_metrics") or {}

    return {
        "job_a": data_a.get("job_id"),
        "job_b": data_b.get("job_id"),
        "environment_diff": {
            "a": env_a,
            "b": env_b,
        },
        "epubcheck_diff": {
            "a_errors": epubcheck_a.get("error_count", 0),
            "b_errors": epubcheck_b.get("error_count", 0),
            "a_warnings": epubcheck_a.get("warning_count", 0),
            "b_warnings": epubcheck_b.get("warning_count", 0),
        },
        "semantic_diff": {
            "a_change_rate": sem_a.get("semantic_change_rate", 0.0),
            "b_change_rate": sem_b.get("semantic_change_rate", 0.0),
            "a_transitions": sem_a.get("type_transitions", {}),
            "b_transitions": sem_b.get("type_transitions", {}),
            "a_conflicts": sem_a.get("semantic_conflict_rate", 0.0),
            "b_conflicts": sem_b.get("semantic_conflict_rate", 0.0),
        },
        "ocr_diff": {
            "a_applied": ocr_a.get("ocr_applied_count", 0),
            "b_applied": ocr_b.get("ocr_applied_count", 0),
            "a_changed_cps": ocr_a.get("ocr_changed_codepoints", 0),
            "b_changed_cps": ocr_b.get("ocr_changed_codepoints", 0),
        },
        "presentation_diff": {
            "a_mode": pres_a.get("presentation_mode", "legacy"),
            "b_mode": pres_b.get("presentation_mode", "legacy"),
            "a_components": pres_a.get("component_counts", {}),
            "b_components": pres_b.get("component_counts", {}),
            "a_dup_markers": pres_a.get("list_duplicate_marker_count", 0),
            "b_dup_markers": pres_b.get("list_duplicate_marker_count", 0),
        },
    }


def format_comparison_text(diff: dict[str, Any]) -> str:
    """Format comparison dictionary as human-readable CLI summary."""
    lines = [
        f"=== Comparison: {diff['job_a']} vs {diff['job_b']} ===",
        "",
        "1. EPUBCheck Validation:",
        (
            f"   Job A: {diff['epubcheck_diff']['a_errors']} errors, "
            f"{diff['epubcheck_diff']['a_warnings']} warnings"
        ),
        (
            f"   Job B: {diff['epubcheck_diff']['b_errors']} errors, "
            f"{diff['epubcheck_diff']['b_warnings']} warnings"
        ),
        "",
        "2. Semantic Reconstruction:",
        (
            f"   Change Rate: A={diff['semantic_diff']['a_change_rate']} | "
            f"B={diff['semantic_diff']['b_change_rate']}"
        ),
        (
            f"   Conflicts:   A={diff['semantic_diff']['a_conflicts']} | "
            f"B={diff['semantic_diff']['b_conflicts']}"
        ),
        "",
        "3. OCR Corrections:",
        (
            f"   Applied: A={diff['ocr_diff']['a_applied']} edits "
            f"({diff['ocr_diff']['a_changed_cps']} cps) | "
            f"B={diff['ocr_diff']['b_applied']} edits "
            f"({diff['ocr_diff']['b_changed_cps']} cps)"
        ),
        "",
        "4. Presentation & Typography:",
        (
            f"   Mode: A={diff['presentation_diff']['a_mode']} | "
            f"B={diff['presentation_diff']['b_mode']}"
        ),
        (
            f"   Duplicate list markers: A={diff['presentation_diff']['a_dup_markers']} | "
            f"B={diff['presentation_diff']['b_dup_markers']}"
        ),
        "=======================================================",
    ]
    return "\n".join(lines)
