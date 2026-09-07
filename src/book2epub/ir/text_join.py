"""Deterministic text joining and dehyphenation rules across lines and spans."""

import re
from dataclasses import dataclass

# Unicode ranges for CJK characters (Han ideographs, Kana, Hangul, Fullwidth)
_CJK_REGEX = re.compile(
    r"[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef\uac00-\ud7af]"
)


def is_cjk(char: str) -> bool:
    """Return True if character belongs to CJK script ranges."""
    return bool(_CJK_REGEX.match(char))


@dataclass
class TextJoinStats:
    dehyphenation_count: int = 0


def join_prose_texts(texts: list[str], stats: TextJoinStats | None = None) -> str:
    """
    Join adjacent prose lines/spans using Book2Epub text join rules.

    Rules:
    1. Normalize CRLF/CR to LF.
    2. CJK-to-CJK line boundaries concatenate without injected ASCII space.
    3. Latin-like words normally join with one space.
    4. Remove hyphen at line end if followed by lowercase Latin letter (when both tokens are letters
       and not URL/math/code).
    5. Collapse multiple spaces to single space, preserving NBSP (\u00a0).
    """
    if not texts:
        return ""

    joined = ""
    for piece in texts:
        # Normalize newlines and basic space
        piece = piece.replace("\r\n", "\n").replace("\r", "\n")
        if not joined:
            joined = piece
            continue

        if not piece:
            continue

        # Check hyphenation on boundary
        # If joined ends with letter + '-' and piece starts with lowercase Latin letter
        s1_stripped = joined.rstrip(" \t\n")
        s2_stripped = piece.lstrip(" \t\n")

        if not s1_stripped:
            joined = piece
            continue
        if not s2_stripped:
            continue

        if (
            s1_stripped.endswith("-")
            and len(s1_stripped) >= 2
            and s1_stripped[-2].isalpha()
            and s2_stripped[0].islower()
            and s2_stripped[0].isascii()
        ):
            # Check previous token is not URL/code
            prev_token = s1_stripped.split()[-1]
            if not any(marker in prev_token for marker in ("http:", "https:", "/", "\\", "=")):
                # Remove the hyphen
                joined = s1_stripped[:-1] + s2_stripped
                if stats is not None:
                    stats.dehyphenation_count += 1
                continue

        c1 = s1_stripped[-1]
        c2 = s2_stripped[0]

        if is_cjk(c1) and is_cjk(c2):
            # CJK to CJK: concatenate directly without space
            joined = s1_stripped + s2_stripped
        else:
            # Join with single space if not already separated
            joined = s1_stripped + " " + s2_stripped

    # Collapse runs of ordinary spaces to one, preserving NBSP
    joined = re.sub(r"[ \t]+", " ", joined)
    return joined.strip()
