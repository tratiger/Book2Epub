"""Unit tests for GoogleProvider adapter using Interactions API
(M7 spec Section 6.2 & Appendix G6)."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict

from book2epub.errors import ConfigurationError
from book2epub.providers.google import DEFAULT_GOOGLE_MODEL, GoogleProvider
from book2epub.providers.models import StructuredInferenceRequest
from book2epub.semantic.schemas import build_provider_schema


class SampleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    code: int


def test_google_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTest12345678901234567890123456789")
    with patch.dict(sys.modules, {"google": None, "google.genai": None}):
        with pytest.raises(ConfigurationError) as exc_info:
            GoogleProvider()
        assert "uv sync --extra semantic-google" in str(exc_info.value)


def test_google_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError) as exc_info:
        GoogleProvider()
    assert "GEMINI_API_KEY" in str(exc_info.value)


@patch("book2epub.providers.google.GoogleProvider.__init__", return_value=None)
def test_google_infer_success(mock_init: MagicMock) -> None:
    provider = GoogleProvider()
    provider.model = DEFAULT_GOOGLE_MODEL
    provider.name = "google"
    mock_client = MagicMock()
    provider._client = mock_client

    mock_interaction = MagicMock()
    mock_interaction.id = "interaction_abc"
    mock_interaction.output_text = json.dumps({"status": "google_ok", "code": 200})
    mock_interaction.usage.input_tokens = 210
    mock_interaction.usage.output_tokens = 80
    mock_client.interactions.create.return_value = mock_interaction

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-google-1",
        system_instruction="Instructions for Gemini",
        user_text="User prompt for Gemini",
        response_model_name="SampleResponse",
        response_schema=schema,
        reasoning_effort="high",
        max_output_tokens=4096,
    )

    validated, result = provider.infer(req, SampleResponse)
    assert isinstance(validated, SampleResponse)
    assert validated.status == "google_ok"
    assert validated.code == 200
    assert result.usage.raw_provider_request_id == "interaction_abc"
    assert result.usage.input_tokens == 210
    assert result.usage.output_tokens == 80

    mock_client.interactions.create.assert_called_once()
    kwargs = mock_client.interactions.create.call_args.kwargs

    assert kwargs["model"] == "gemini-3.1-pro-preview"
    assert kwargs["system_instruction"] == "Instructions for Gemini"
    assert kwargs["input"] == "User prompt for Gemini"
    assert kwargs["store"] is False  # Stateless
    assert "tools" not in kwargs
    assert kwargs["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": schema,
    }
    assert kwargs["generation_config"] == {
        "thinking_level": "high",
        "max_output_tokens": 4096,
    }


@patch("book2epub.providers.google.GoogleProvider.__init__", return_value=None)
def test_google_infer_schema_retry(mock_init: MagicMock) -> None:
    provider = GoogleProvider()
    provider.model = DEFAULT_GOOGLE_MODEL
    provider.name = "google"
    mock_client = MagicMock()
    provider._client = mock_client

    bad_interaction = MagicMock()
    bad_interaction.output_text = "{ malformed json..."

    good_interaction = MagicMock()
    good_interaction.output_text = json.dumps({"status": "retry_ok", "code": 200})
    good_interaction.usage = None

    mock_client.interactions.create.side_effect = [bad_interaction, good_interaction]

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-schema-retry",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=schema,
    )

    validated, _ = provider.infer(req, SampleResponse)
    assert validated.status == "retry_ok"
    assert mock_client.interactions.create.call_count == 2
