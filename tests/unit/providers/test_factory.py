"""Unit tests for StructuredProvider factory (M7 spec Section 5 & Appendix G12)."""

from unittest.mock import MagicMock, patch

import pytest

from book2epub.config import (
    JobConfig,
    OCRCorrectionConfig,
    PresentationConfig,
    SemanticConfig,
)
from book2epub.errors import ConfigurationError
from book2epub.providers.factory import create_provider, is_provider_required


def test_is_provider_required() -> None:
    cfg = JobConfig()
    assert is_provider_required(cfg) is False

    cfg_sem = JobConfig(semantic=SemanticConfig(enabled=True))
    assert is_provider_required(cfg_sem) is True

    cfg_infer = JobConfig(presentation=PresentationConfig(mode="infer"))
    assert is_provider_required(cfg_infer) is True

    cfg_ocr_safe = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    assert is_provider_required(cfg_ocr_safe) is True

    cfg_ocr_all = JobConfig(ocr_correction=OCRCorrectionConfig(mode="all"))
    assert is_provider_required(cfg_ocr_all) is True


def test_create_provider_unsupported_name() -> None:
    cfg = JobConfig()
    object.__setattr__(cfg.semantic, "provider", "unsupported_xyz")
    with pytest.raises(ConfigurationError) as exc_info:
        create_provider(cfg)
    assert "Unsupported provider 'unsupported_xyz'" in str(exc_info.value)


@pytest.mark.parametrize("cloud_provider", ["openai", "google", "anthropic"])
def test_create_provider_cloud_gate_rejection(cloud_provider: str) -> None:
    """Verify cloud providers are rejected immediately when allow_cloud is False."""
    cfg = JobConfig(
        semantic=SemanticConfig(
            provider=cloud_provider,
            allow_cloud=False,
        )
    )
    with pytest.raises(ConfigurationError) as exc_info:
        create_provider(cfg)
    msg = str(exc_info.value)
    assert "requires explicit cloud opt-in" in msg
    assert "--allow-cloud" in msg


def test_create_provider_missing_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = JobConfig(semantic=SemanticConfig(provider="openai", allow_cloud=True))
    with pytest.raises(ConfigurationError) as exc_info:
        create_provider(cfg)
    assert "OPENAI_API_KEY" in str(exc_info.value)


def test_create_provider_missing_google_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg = JobConfig(semantic=SemanticConfig(provider="google", allow_cloud=True))
    with pytest.raises(ConfigurationError) as exc_info:
        create_provider(cfg)
    assert "GEMINI_API_KEY" in str(exc_info.value)


def test_create_provider_missing_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = JobConfig(semantic=SemanticConfig(provider="anthropic", allow_cloud=True))
    with pytest.raises(ConfigurationError) as exc_info:
        create_provider(cfg)
    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


def test_create_provider_ollama_missing_model() -> None:
    cfg = JobConfig(semantic=SemanticConfig(provider="ollama", model=None))
    with pytest.raises(ConfigurationError) as exc_info:
        create_provider(cfg)
    assert "Ollama provider requires a model name" in str(exc_info.value)


@patch("book2epub.providers.ollama.OllamaProvider.__init__", return_value=None)
def test_create_provider_ollama_success(mock_init: MagicMock) -> None:
    cfg = JobConfig(semantic=SemanticConfig(provider="ollama", model="llama3.3"))
    provider = create_provider(cfg)
    assert provider.name == "ollama"
    mock_init.assert_called_once_with(model="llama3.3")
