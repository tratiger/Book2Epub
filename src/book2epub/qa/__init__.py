"""QA diagnostics, structural reconciliation checks, and evaluation metrics."""

from book2epub.qa.checks import run_structural_checks
from book2epub.qa.models import (
    EvaluationMetrics,
    PageQASummary,
    QAReportData,
    QAViolation,
    StructuralCheckResult,
)
from book2epub.qa.report import generate_qa_report
from book2epub.qa.stage import StageRecord, StageState, record_stage_status

__all__ = [
    "run_structural_checks",
    "generate_qa_report",
    "EvaluationMetrics",
    "PageQASummary",
    "QAReportData",
    "QAViolation",
    "StructuralCheckResult",
    "StageRecord",
    "StageState",
    "record_stage_status",
]
