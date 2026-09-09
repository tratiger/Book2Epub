"""Factory for constructing structured inference providers (M7 spec Section 5, Appendix G12)."""

import os

from book2epub.config import JobConfig
from book2epub.errors import ConfigurationError
from book2epub.providers.base import StructuredProvider

CLOUD_PROVIDERS = {"openai", "google", "anthropic"}
LOCAL_PROVIDERS = {"ollama"}
SUPPORTED_PROVIDERS = CLOUD_PROVIDERS | LOCAL_PROVIDERS


def is_provider_required(cfg: JobConfig) -> bool:
    """Return True if any configured feature requires an LLM/VLM provider."""
    return (
        cfg.semantic.enabled
        or cfg.presentation.mode == "infer"
        or cfg.ocr_correction.mode != "off"
    )


def create_provider(cfg: JobConfig, purpose: str = "semantic") -> StructuredProvider:
    """
    Construct a validated StructuredProvider instance according to job configuration.

    Rules:
    - Verifies provider name is valid.
    - Cloud providers require cfg.semantic.allow_cloud before client construction.
    - Environment variable existence verified for cloud providers.
    - Ollama requires an explicit model parameter.
    """
    provider_name = cfg.semantic.provider.lower()

    if provider_name not in SUPPORTED_PROVIDERS:
        raise ConfigurationError(
            f"Unsupported provider '{provider_name}'. Must be one of: {sorted(SUPPORTED_PROVIDERS)}"
        )

    # Cloud opt-in check (M7 spec Section 5)
    if provider_name in CLOUD_PROVIDERS and not cfg.semantic.allow_cloud:
        raise ConfigurationError(
            f"Cloud provider '{provider_name}' requires explicit cloud opt-in. "
            "Please add the '--allow-cloud' flag."
        )

    # API key environment variable check
    if provider_name == "openai":
        if "OPENAI_API_KEY" not in os.environ or not os.environ["OPENAI_API_KEY"]:
            raise ConfigurationError(
                "Environment variable 'OPENAI_API_KEY' is required for provider 'openai'."
            )
        from book2epub.providers.openai import OpenAIProvider
        return OpenAIProvider(model=cfg.semantic.model)

    elif provider_name == "google":
        if "GEMINI_API_KEY" not in os.environ or not os.environ["GEMINI_API_KEY"]:
            raise ConfigurationError(
                "Environment variable 'GEMINI_API_KEY' is required for provider 'google'."
            )
        from book2epub.providers.google import GoogleProvider
        return GoogleProvider(model=cfg.semantic.model)

    elif provider_name == "anthropic":
        if "ANTHROPIC_API_KEY" not in os.environ or not os.environ["ANTHROPIC_API_KEY"]:
            raise ConfigurationError(
                "Environment variable 'ANTHROPIC_API_KEY' is required for provider 'anthropic'."
            )
        from book2epub.providers.anthropic import AnthropicProvider
        return AnthropicProvider(model=cfg.semantic.model)

    elif provider_name == "ollama":
        if not cfg.semantic.model:
            raise ConfigurationError(
                "Ollama provider requires a model name. Specify with '--semantic-model <model>'."
            )
        from book2epub.providers.ollama import OllamaProvider
        return OllamaProvider(model=cfg.semantic.model)

    raise ConfigurationError(f"Unexpected provider '{provider_name}'")
