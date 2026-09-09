"""Unit tests for BookStyleProfile schema, tokens, and deterministic hashing (M10)."""

import pytest
from pydantic import ValidationError

from book2epub.presentation.defaults import DEFAULT_ENHANCED_PROFILE
from book2epub.presentation.models import (
    BookStyleProfile,
    BookStyleProfileDecision,
    compute_profile_hash,
)


def test_default_enhanced_profile_valid() -> None:
    """Verify default enhanced profile conforms to schema."""
    profile = DEFAULT_ENHANCED_PROFILE
    assert profile.schema_version == "1.0"
    assert profile.body.page_margin == "standard"
    assert profile.body.line_height == "normal"
    assert profile.headings.h1.scale == "xxl"
    assert profile.headings.h2.rule == "bottom_thin"
    assert profile.source_code.border == "accent_left"
    assert profile.terminal.theme == "outline"
    assert profile.mode_source == "enhanced_default"


def test_profile_hash_deterministic() -> None:
    """Verify hash calculation is strictly deterministic and visual-choice sensitive."""
    h1 = compute_profile_hash(DEFAULT_ENHANCED_PROFILE)
    h2 = compute_profile_hash(DEFAULT_ENHANCED_PROFILE)
    assert h1 == h2
    assert len(h1) == 64

    # Volatile metadata change should not affect hash
    copy_meta = DEFAULT_ENHANCED_PROFILE.model_copy(
        update={"request_id": "different-req-123", "confidence": 0.85}
    )
    assert compute_profile_hash(copy_meta) == h1

    # Visual choice change MUST affect hash
    copy_visual = DEFAULT_ENHANCED_PROFILE.model_copy(
        update={
            "body": DEFAULT_ENHANCED_PROFILE.body.model_copy(update={"page_margin": "compact"})
        }
    )
    assert compute_profile_hash(copy_visual) != h1


def test_schema_forbids_raw_css_and_extra_fields() -> None:
    """Verify raw CSS, html, or arbitrary attributes are strictly rejected by Pydantic."""
    data = DEFAULT_ENHANCED_PROFILE.model_dump()
    data["raw_css"] = "body { color: red; }"

    with pytest.raises(ValidationError):
        BookStyleProfile.model_validate(data)

    dec_data = {
        "schema_version": "1.0",
        "profile": DEFAULT_ENHANCED_PROFILE.model_dump(),
        "confidence": 0.95,
        "evidence_page_indices": [1, 2],
        "custom_html": "<style>bad</style>",
    }
    with pytest.raises(ValidationError):
        BookStyleProfileDecision.model_validate(dec_data)
