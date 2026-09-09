"""Character classification for Japanese and Latin typography (M11/Appendix M3)."""

from .models import CharClass

OPEN_JP_PUNCT_CHARS = frozenset("（［【〈《「『〔〖〘〚")
CLOSE_JP_PUNCT_CHARS = frozenset("、。，．！？：；）］】〉》」』〕〗〙〛")

OPEN_ASCII_PUNCT_CHARS = frozenset("([{")
CLOSE_ASCII_PUNCT_CHARS = frozenset(",.;:!?)]}")

WHITESPACE_CHARS = frozenset(" \t\r\n\u3000\u00a0\u200b\u202f")


def is_cjk_code(cp: int) -> bool:
    """Return True if codepoint is Kanji, Hiragana, or Katakana."""
    return (
        (0x3040 <= cp <= 0x309F)  # Hiragana
        or (0x30A0 <= cp <= 0x30FF)  # Katakana
        or (0x31F0 <= cp <= 0x31FF)  # Katakana Phonetic Extensions
        or (0xFF65 <= cp <= 0xFF9F)  # Halfwidth Katakana
        or (0x4E00 <= cp <= 0x9FFF)  # CJK Unified Ideographs
        or (0x3400 <= cp <= 0x4DBF)  # CJK Extension A
        or (0xF900 <= cp <= 0xFAFF)  # CJK Compatibility Ideographs
        or (0x20000 <= cp <= 0x2A6DF)  # CJK Extension B
        or cp == 0x3005  # Ideographic iteration mark (々)
        or cp == 0x30FC  # Katakana-Hiragana Prolonged Sound Mark (ー)
    )


def classify_char(ch: str) -> CharClass:
    """Classify a single character into one of the nine typography character classes."""
    if not ch:
        return CharClass.OTHER

    if ch in WHITESPACE_CHARS:
        return CharClass.WHITESPACE

    if ch in OPEN_JP_PUNCT_CHARS:
        return CharClass.OPEN_JP_PUNCT

    if ch in CLOSE_JP_PUNCT_CHARS:
        return CharClass.CLOSE_JP_PUNCT

    if ch in OPEN_ASCII_PUNCT_CHARS:
        return CharClass.OPEN_ASCII_PUNCT

    if ch in CLOSE_ASCII_PUNCT_CHARS:
        return CharClass.CLOSE_ASCII_PUNCT

    cp = ord(ch[0])
    if is_cjk_code(cp):
        return CharClass.CJK_HAN_KANA

    if ch.isascii() and (ch.isalpha() or ch == "_"):
        return CharClass.LATIN_ASCII_WORD

    if ch.isdigit() or (0xFF10 <= cp <= 0xFF19):  # ASCII digit or fullwidth digit
        return CharClass.DIGIT

    return CharClass.OTHER


def is_cjk_char(ch: str) -> bool:
    """Return True if character is Japanese Kanji or Kana."""
    return classify_char(ch) == CharClass.CJK_HAN_KANA


def is_open_punct(ch: str) -> bool:
    """Return True if character is opening punctuation (Japanese or ASCII)."""
    cls = classify_char(ch)
    return cls in (CharClass.OPEN_JP_PUNCT, CharClass.OPEN_ASCII_PUNCT)


def is_close_punct(ch: str) -> bool:
    """Return True if character is closing punctuation (Japanese or ASCII)."""
    cls = classify_char(ch)
    return cls in (CharClass.CLOSE_JP_PUNCT, CharClass.CLOSE_ASCII_PUNCT)
