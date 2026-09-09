"""Unit tests for OpenAIProvider adapter using Responses API (M7 spec Section 6.1 & Appendix G5)."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict

from book2epub.errors import ConfigurationError, ProviderError
from book2epub.providers.models import StructuredInferenceRequest
from book2epub.providers.openai import DEFAULT_OPENAI_MODEL, OpenAIProvider
from book2epub.semantic.schemas import build_provider_schema


class SampleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    code: int


def test_openai_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-testkey12345678901234567890")
    with patch.dict(sys.modules, {"openai": None}):
        with pytest.raises(ConfigurationError) as exc_info:
            OpenAIProvider()
        assert "uv sync --extra semantic-openai" in str(exc_info.value)


def test_openai_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError) as exc_info:
        OpenAIProvider()
    assert "OPENAI_API_KEY" in str(exc_info.value)


@patch("book2epub.providers.openai.OpenAIProvider.__init__", return_value=None)
def test_openai_infer_success(mock_init: MagicMock) -> None:
    provider = OpenAIProvider()
    provider.model = DEFAULT_OPENAI_MODEL
    provider.name = "openai"
    mock_client = MagicMock()
    provider._client = mock_client

    mock_resp = MagicMock()
    mock_resp.status = "completed"
    mock_resp.id = "resp_abc123"
    mock_resp.output_text = json.dumps({"status": "openai_ok", "code": 200})
    mock_resp.usage.input_tokens = 120
    mock_resp.usage.output_tokens = 45
    mock_client.responses.create.return_value = mock_resp

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-openai-1",
        system_instruction="Instructions for model",
        user_text="User prompt text",
        response_model_name="SampleResponse",
        response_schema=schema,
        reasoning_effort="medium",
    )

    validated, result = provider.infer(req, SampleResponse)
    assert isinstance(validated, SampleResponse)
    assert validated.status == "openai_ok"
    assert validated.code == 200
    assert result.usage.raw_provider_request_id == "resp_abc123"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 45

    # Check exact keyword args passed to responses.create
    mock_client.responses.create.assert_called_once()
    kwargs = mock_client.responses.create.call_args.kwargs

    assert kwargs["model"] == "gpt-5.6-sol"
    assert kwargs["instructions"] == "Instructions for model"
    assert kwargs["input"] == "User prompt text"
    assert kwargs["store"] is False  # Must be stateless
    assert "tools" not in kwargs     # No tools permitted
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["text"] == {
        "format": {
            "type": "json_schema",
            "name": "SampleResponse",
            "strict": True,
            "schema": schema,
        }
    }


@patch("book2epub.providers.openai.OpenAIProvider.__init__", return_value=None)
def test_openai_infer_auth_error_not_retried(mock_init: MagicMock) -> None:
    provider = OpenAIProvider()
    provider.model = DEFAULT_OPENAI_MODEL
    provider.name = "openai"
    mock_client = MagicMock()
    provider._client = mock_client

    # 401 Unauthorized should fail immediately without retry
    class MockAuthError(Exception):
        status_code = 401

    mock_client.responses.create.side_effect = MockAuthError("Invalid API key")

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-auth-fail",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=schema,
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.infer(req, SampleResponse)
    assert "Invalid API key" in str(exc_info.value)
    # Must not retry
    assert mock_client.responses.create.call_count == 1


@patch("book2epub.providers.openai.OpenAIProvider.__init__", return_value=None)
def test_openai_infer_rate_limit_retry(mock_init: MagicMock) -> None:
    provider = OpenAIProvider()
    provider.model = DEFAULT_OPENAI_MODEL
    provider.name = "openai"
    mock_client = MagicMock()
    provider._client = mock_client

    class MockRateLimitError(Exception):
        status_code = 429

    good_resp = MagicMock()
    good_resp.status = "completed"
    good_resp.output_text = json.dumps({"status": "retry_ok", "code": 200})
    good_resp.usage = None

    mock_client.responses.create.side_effect = [
        MockRateLimitError("Rate limit reached"),
        good_resp,
    ]

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-rate-limit",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=schema,
    )

    with patch("time.sleep", return_value=None):
        validated, _ = provider.infer(req, SampleResponse)

    assert validated.status == "retry_ok"
    assert mock_client.responses.create.call_count == 2
