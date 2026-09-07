"""Deterministic natural sorting by filename.

Case-insensitive comparison with case-sensitive tie-breaker.
"""

import re
from pathlib import Path
from typing import Any


def natural_sort_key(item: str | Path) -> tuple[list[tuple[int, Any]], str]:
    """
    Compute natural sort key for a filename or Path.

    Sorts by filename in natural numerical order:
    - Numeric chunks are compared as integers, then by string length (fewer leading zeros first).
    - Text chunks are compared case-insensitively.
    - Tie-breaker is the original name/path string.
    """
    name = item.name if isinstance(item, Path) else Path(item).name
    original_str = str(item)

    parts: list[tuple[int, Any]] = []
    for chunk in re.split(r"(\d+)", name):
        if not chunk:
            continue
        if chunk.isdigit():
            # 0 indicator for digits, integer value, then length of digits for leading zero ordering
            parts.append((0, (int(chunk), len(chunk))))
        else:
            # 1 indicator for non-digits, lowercase text
            parts.append((1, chunk.casefold()))

    return parts, original_str


def natural_sort[T: (str, Path)](items: list[T]) -> list[T]:
    """Return a new list of items sorted deterministically in natural order."""
    return sorted(items, key=natural_sort_key)
