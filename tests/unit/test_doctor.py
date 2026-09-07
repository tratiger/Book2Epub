"""Unit tests for doctor component result model and formatting."""

from book2epub.doctor import CheckResult, CheckStatus, print_doctor_report


def test_check_result_formatting_pass() -> None:
    res = CheckResult(name="Python Version", status=CheckStatus.PASS, message="Python 3.12.10")
    formatted = res.formatted_line()
    assert "[PASS]" in formatted
    assert "Python Version" in formatted
    assert "Python 3.12.10" in formatted
    assert "->" not in formatted


def test_check_result_formatting_with_recommendation() -> None:
    res = CheckResult(
        name="MinerU Version",
        status=CheckStatus.FAIL,
        message="Not installed",
        recommendation='Run: uv pip install -U "mineru[all]==3.4.5"',
    )
    formatted = res.formatted_line()
    assert "[FAIL]" in formatted
    assert "MinerU Version" in formatted
    assert "Not installed" in formatted
    assert "-> Run:" in formatted


def test_print_doctor_report_status() -> None:
    pass_results = [
        CheckResult("Item1", CheckStatus.PASS, "ok"),
        CheckResult("Item2", CheckStatus.WARN, "warning note"),
    ]
    assert print_doctor_report(pass_results) is True

    fail_results = [
        CheckResult("Item1", CheckStatus.PASS, "ok"),
        CheckResult("Item2", CheckStatus.FAIL, "broken", recommendation="fix it"),
    ]
    assert print_doctor_report(fail_results) is False
