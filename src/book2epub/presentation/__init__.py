"""Presentation and styling subsystem for Book2Epub (M10)."""

from .css_generator import compute_css_hash, generate_book_css
from .defaults import DEFAULT_ENHANCED_PROFILE
from .models import (
    BookStyleProfile,
    BookStyleProfileDecision,
    compute_profile_hash,
)
from .stage import resolve_style_profile

__all__ = [
    "BookStyleProfile",
    "BookStyleProfileDecision",
    "DEFAULT_ENHANCED_PROFILE",
    "compute_profile_hash",
    "compute_css_hash",
    "generate_book_css",
    "resolve_style_profile",
]
