"""Structured LLM/VLM provider abstraction package."""

from book2epub.providers.base import StructuredProvider
from book2epub.providers.factory import create_provider, is_provider_required
from book2epub.providers.models import (
    ImageInput,
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)

__all__ = [
    "create_provider",
    "ImageInput",
    "is_provider_required",
    "ProviderUsage",
    "StructuredInferenceRequest",
    "StructuredInferenceResult",
    "StructuredProvider",
]
