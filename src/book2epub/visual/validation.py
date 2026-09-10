"""
Safety validation and edit-budget tracking for OCR correction proposals
(M9 Section 12, Appendix K9-K13).
"""

import difflib
import math
import re
from typing import Literal

from book2epub.visual.models import OCRCorrectionProposal

ASCII_OPERATORS_PUNCTUATION = set("+-*/%=<>!&|^~:;.,()[]{}_$#@\\/")


def calculate_changed_codepoints(old_text: str, new_text: str) -> int:
    """Calculate total inserted, deleted, and replaced codepoints using SequenceMatcher."""
    matcher = difflib.SequenceMatcher(None, old_text, new_text)
    changed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            changed += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            changed += i2 - i1
        elif tag == "insert":
            changed += j2 - j1
    return changed


def is_sensitive_change(
    old_text: str,
    proposed_text: str,
    is_code_or_preformatted: bool = False,
) -> bool:
    """
    Detect whether an OCR proposed correction is sensitive (Appendix K10).
    Sensitive changes include digits, code operators, identifiers, hex, URLs, or paths.
    """
    if is_code_or_preformatted:
        if old_text != proposed_text:
            return True

    # Digit changes (0-9)
    old_digits = "".join(c for c in old_text if c.isdigit())
    new_digits = "".join(c for c in proposed_text if c.isdigit())
    if old_digits != new_digits:
        return True

    # ASCII operator / punctuation changes
    old_ops = "".join(c for c in old_text if c in ASCII_OPERATORS_PUNCTUATION)
    new_ops = "".join(c for c in proposed_text if c in ASCII_OPERATORS_PUNCTUATION)
    if old_ops != new_ops:
        return True

    # High-sensitivity tokens
    patterns = [
        r"https?://",
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",  # IP
        r"\bv?\d+(\.\d+)+",                          # version
        r"--?[a-zA-Z0-9_-]+",                        # command flag
        r"0x[0-9a-fA-F]+",                           # hex
        r"/[a-zA-Z0-9_\.\-]+",                       # unix path
    ]
    for pat in patterns:
        if re.search(pat, old_text) or re.search(pat, proposed_text):
            return True

    return False


class EditBudgetTracker:
    """
    Tracks book-level OCR edit budget to prevent runaway overcorrection (Appendix K13).
    """

    def __init__(
        self,
        mode: Literal["safe", "all"],
        total_segments: int,
        total_codepoints: int,
    ) -> None:
        self.mode = mode
        self.total_segments = max(1, total_segments)
        self.total_codepoints = max(1, total_codepoints)
        self.changed_segments = 0
        self.changed_codepoints = 0
        self.budget_exceeded = False

    @property
    def max_changed_segments(self) -> int:
        ratio = 0.005 if self.mode == "safe" else 0.01
        return max(1, int(self.total_segments * ratio))

    @property
    def max_changed_codepoints(self) -> int:
        if self.mode == "safe":
            return min(500, max(10, int(self.total_codepoints * 0.005)))
        else:
            return min(1000, max(20, int(self.total_codepoints * 0.01)))

    def can_apply(self, additional_codepoints: int) -> bool:
        if (self.changed_segments + 1) > self.max_changed_segments:
            self.budget_exceeded = True
            return False
        if (self.changed_codepoints + additional_codepoints) > self.max_changed_codepoints:
            self.budget_exceeded = True
            return False
        return True

    def record_applied(self, changed_codepoints: int) -> None:
        self.changed_segments += 1
        self.changed_codepoints += changed_codepoints


def validate_ocr_proposal(
    proposal: OCRCorrectionProposal,
    old_text: str,
    is_code_or_preformatted: bool,
    is_math: bool,
    is_table_html: bool,
    mode: Literal["safe", "all"],
    budget_tracker: EditBudgetTracker,
) -> tuple[bool, str, list[str]]:
    """
    Validate an OCR correction proposal against safety and budget rules.
    Returns (valid, status, rejection_reasons).
    """
    reasons: list[str] = []

    # 1. Math is strictly immutable (Appendix K6, AGENTS.md rule 11)
    if is_math:
        return False, "rejected", ["Math source text is strictly immutable in M6-M12"]

    # 2. Table HTML cells excluded (Appendix K6)
    if is_table_html:
        return False, "rejected", ["Structured Table HTML cell mutation is excluded"]

    # 3. Proposed text must be non-empty and different
    if proposal.proposed_text is None or proposal.proposed_text == old_text:
        return False, "rejected", ["Proposed text is empty or identical to source"]

    # 4. Length expansion check
    max_len = max(4 * len(old_text), len(old_text) + 16)
    if len(proposal.proposed_text) > max_len:
        return False, "rejected", [f"Proposed text length exceeds limit ({max_len})"]

    changed_cp = calculate_changed_codepoints(old_text, proposal.proposed_text)

    # 5. Confidence threshold check (raised: sensitive/code >= 0.995, ordinary prose >= 0.98)
    sensitive = is_sensitive_change(
        old_text, proposal.proposed_text, is_code_or_preformatted=is_code_or_preformatted
    )
    required_conf = 0.995 if (sensitive or is_code_or_preformatted) else 0.98
    if proposal.confidence < required_conf:
        return False, "suggested_below_threshold", [
            f"Confidence ({proposal.confidence}) below threshold {required_conf}"
        ]

    # 6. Mode-specific rules
    if mode == "safe":
        if is_code_or_preformatted:
            return False, "rejected", ["CodeBlock / PreformattedBlock excluded in safe mode"]

        if "\n" in proposal.proposed_text and "\n" not in old_text:
            return False, "rejected", ["Cannot introduce newline in safe mode"]

        if changed_cp > 24:
            return False, "rejected", [
                f"Changed codepoints ({changed_cp}) exceeds safe limit (24)"
            ]

        lev_limit = max(2, math.ceil(0.12 * len(old_text)))
        if changed_cp > lev_limit:
            return False, "rejected", [
                f"Edit distance ({changed_cp}) exceeds safe budget ({lev_limit})"
            ]

    elif mode == "all":
        if is_code_or_preformatted:
            if changed_cp > 12:
                return False, "rejected", [
                    f"Changed codepoints ({changed_cp}) in code exceeds limit (12)"
                ]
            lev_limit = max(3, math.ceil(0.15 * len(old_text)))
            if changed_cp > lev_limit:
                return False, "rejected", [
                    f"Edit distance ({changed_cp}) exceeds code budget ({lev_limit})"
                ]

    # 7. Book-level cumulative edit budget
    if not budget_tracker.can_apply(changed_cp):
        return False, "budget_exceeded", ["Book-level cumulative OCR edit budget exceeded"]

    return True, "valid", reasons

