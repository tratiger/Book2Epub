"""Serialization and metrics reporting for typography normalization (M11/Appendix M17)."""

import json
from pathlib import Path

from .models import NormalizationReport


def save_normalization_report(report: NormalizationReport, output_path: Path) -> None:
    """Save NormalizationReport to JSON with deterministic indent."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report.model_dump(mode="json"), f, indent=2, ensure_ascii=False)
