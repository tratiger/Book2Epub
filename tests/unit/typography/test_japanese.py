"""Unit tests for Japanese and Latin character classification (M11/Appendix M3)."""

from book2epub.typography.japanese import (
    classify_char,
    is_cjk_char,
    is_close_punct,
    is_open_punct,
)
from book2epub.typography.models import CharClass


def test_classify_cjk_characters() -> None:
    """Verify Kanji, Hiragana, Katakana, and Prolonged sound marks are classified as CJK."""
    assert classify_char("漢") == CharClass.CJK_HAN_KANA
    assert classify_char("あ") == CharClass.CJK_HAN_KANA
    assert classify_char("カ") == CharClass.CJK_HAN_KANA
    assert classify_char("ー") == CharClass.CJK_HAN_KANA
    assert classify_char("々") == CharClass.CJK_HAN_KANA

    assert is_cjk_char("漢")
    assert is_cjk_char("あ")
    assert is_cjk_char("カ")
    assert not is_cjk_char("A")
    assert not is_cjk_char("1")
    assert not is_cjk_char("。")


def test_classify_punctuation() -> None:
    """Verify Japanese and ASCII opening and closing punctuation are distinguished."""
    # Japanese opening
    for ch in "（［【〈《「『〔〖〘〚":
        assert classify_char(ch) == CharClass.OPEN_JP_PUNCT
        assert is_open_punct(ch)
        assert not is_close_punct(ch)

    # Japanese closing
    for ch in "、。，．！？：；）］】〉》」』〕〗〙〛":
        assert classify_char(ch) == CharClass.CLOSE_JP_PUNCT
        assert is_close_punct(ch)
        assert not is_open_punct(ch)

    # ASCII opening
    for ch in "([{":
        assert classify_char(ch) == CharClass.OPEN_ASCII_PUNCT
        assert is_open_punct(ch)

    # ASCII closing
    for ch in ",.;:!?)]}":
        assert classify_char(ch) == CharClass.CLOSE_ASCII_PUNCT
        assert is_close_punct(ch)


def test_classify_words_and_digits() -> None:
    """Verify Latin letters, ASCII digits, and fullwidth digits."""
    assert classify_char("a") == CharClass.LATIN_ASCII_WORD
    assert classify_char("Z") == CharClass.LATIN_ASCII_WORD
    assert classify_char("_") == CharClass.LATIN_ASCII_WORD

    assert classify_char("0") == CharClass.DIGIT
    assert classify_char("9") == CharClass.DIGIT
    assert classify_char("５") == CharClass.DIGIT


def test_classify_whitespace() -> None:
    """Verify whitespace characters."""
    assert classify_char(" ") == CharClass.WHITESPACE
    assert classify_char("\t") == CharClass.WHITESPACE
    assert classify_char("\n") == CharClass.WHITESPACE
    assert classify_char("\u3000") == CharClass.WHITESPACE  # Ideographic space
    assert classify_char("\u00a0") == CharClass.WHITESPACE  # NBSP
