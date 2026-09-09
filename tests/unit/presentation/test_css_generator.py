"""Unit tests for deterministic CSS generation from BookStyleProfile (M10)."""

from book2epub.presentation.css_generator import compute_css_hash, generate_book_css
from book2epub.presentation.defaults import DEFAULT_ENHANCED_PROFILE


def test_generate_book_css_determinate() -> None:
    """Verify repeated CSS generation produces identical bytes and hashes."""
    css1 = generate_book_css(DEFAULT_ENHANCED_PROFILE)
    css2 = generate_book_css(DEFAULT_ENHANCED_PROFILE)
    assert css1 == css2
    assert compute_css_hash(css1) == compute_css_hash(css2)
    assert css1.startswith('@charset "UTF-8";')


def test_no_forbidden_css_patterns() -> None:
    """Verify generated CSS has no absolute positioning, JavaScript, or fixed dimensions."""
    css = generate_book_css(DEFAULT_ENHANCED_PROFILE)
    assert "position: absolute" not in css
    assert "position: fixed" not in css
    assert "display: grid" not in css
    assert "javascript:" not in css
    assert "http://" not in css
    assert "https://" not in css


def test_h2_bottom_thin_rule_emitted() -> None:
    """Verify h2 bottom_thin rule emits border-bottom in generated CSS."""
    css = generate_book_css(DEFAULT_ENHANCED_PROFILE)
    assert "h2, .h2 {" in css
    assert "border-bottom: 0.06em solid currentColor;" in css
    assert "padding-bottom: 0.22em;" in css


def test_paragraph_and_body_tokens_apply() -> None:
    """Verify body margin, line height, and paragraph margins conform to profile."""
    css = generate_book_css(DEFAULT_ENHANCED_PROFILE)
    assert "margin-inline: 5%;" in css
    assert "line-height: 1.55;" in css
    assert "margin-block-start: 0.65em;" in css
    assert "margin-block-end: 0.65em;" in css


def test_preformatted_themes_distinct() -> None:
    """Verify source code, terminal, log, and config receive distinct treatment."""
    css = generate_book_css(DEFAULT_ENHANCED_PROFILE)
    # source code has accent_left border and subtle bg
    assert "border-left: 0.22em solid currentColor;" in css
    # terminal has outline thin border
    assert "border: 1px solid #d6d6d6;" in css


def test_callout_accents_emitted() -> None:
    """Verify callout subtypes have distinct color borders and styling."""
    css = generate_book_css(DEFAULT_ENHANCED_PROFILE)
    assert "aside.callout-note" in css
    assert "#2563eb" in css  # blue accent
    assert "aside.callout-warning" in css
    assert "#b45309" in css  # amber accent
    assert "aside.callout-caution" in css
    assert "#b91c1c" in css  # red accent
