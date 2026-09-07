"""Page label recognition and monotonic validation algorithm."""

import re

# Regex patterns for page numbers
_DECIMAL_REGEX = re.compile(
    r"^\s*(?:p(?:age|\.)?\s*)?([0-9]+)(?:\s*(?:ページ|p|pp)?)?\s*$",
    re.IGNORECASE,
)
_ROMAN_REGEX = re.compile(r"^\s*([ivxlcdmIVXLCDM]+)\s*$")

# Roman numeral values
_ROMAN_MAP = {
    "i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000
}


def parse_roman_numeral(s: str) -> int | None:
    """Parse Roman numeral to integer, or None if invalid."""
    s = s.lower().strip()
    if not s or not all(c in _ROMAN_MAP for c in s):
        return None
    val = 0
    prev = 0
    for c in reversed(s):
        curr = _ROMAN_MAP[c]
        if curr >= prev:
            val += curr
            prev = curr
        else:
            val -= curr
    return val if val > 0 else None


def extract_candidate_page_label(text: str) -> tuple[str | None, int | None, str]:
    """
    Extract candidate page label, numeric value, and kind ('decimal' | 'roman' | 'unknown').

    Returns (label_str, numeric_value, kind).
    """
    cleaned = text.strip().strip("-—~ ")
    if not cleaned:
        return None, None, "unknown"

    m_dec = _DECIMAL_REGEX.match(cleaned)
    if m_dec:
        num_str = m_dec.group(1)
        return num_str, int(num_str), "decimal"

    m_rom = _ROMAN_REGEX.match(cleaned)
    if m_rom:
        rom_str = m_rom.group(1)
        val = parse_roman_numeral(rom_str)
        if val is not None:
            return rom_str, val, "roman"

    return None, None, "unknown"


def compute_validated_page_labels(
    raw_labels: list[str | None],
) -> list[tuple[str | None, float]]:
    """
    Validate page labels across neighboring pages requiring monotonically plausible sequence.

    Returns list of (final_label_or_none, confidence).
    """
    candidates: list[tuple[str | None, int | None, str]] = [
        extract_candidate_page_label(text) if text else (None, None, "unknown")
        for text in raw_labels
    ]

    results: list[tuple[str | None, float]] = []

    for i, (label, val, kind) in enumerate(candidates):
        if label is None or val is None:
            results.append((None, 0.0))
            continue

        # Check local monotonicity against preceding and succeeding pages
        is_consistent = True

        # Check previous recognized numeric page of same kind
        prev_idx = None
        for j in range(i - 1, -1, -1):
            if candidates[j][1] is not None and candidates[j][2] == kind:
                prev_idx = j
                break

        if prev_idx is not None:
            prev_val = candidates[prev_idx][1]
            page_diff = i - prev_idx
            # Expected value difference is <= page_diff (usually exactly page_diff or small skip)
            val_diff = val - (prev_val if prev_val is not None else 0)
            if val_diff <= 0 or val_diff > page_diff + 5:
                # Contradictory jump
                is_consistent = False

        # Check next recognized numeric page of same kind
        next_idx = None
        for j in range(i + 1, len(candidates)):
            if candidates[j][1] is not None and candidates[j][2] == kind:
                next_idx = j
                break

        if next_idx is not None:
            next_val = candidates[next_idx][1]
            page_diff = next_idx - i
            val_diff = (next_val if next_val is not None else 0) - val
            if val_diff <= 0 or val_diff > page_diff + 5:
                is_consistent = False

        if is_consistent:
            results.append((label, 1.0))
        else:
            # Downgrade contradictory label
            results.append((None, 0.2))

    return results
