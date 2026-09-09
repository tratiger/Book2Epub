"""Unit tests for AnthropicProvider adapter (M7 spec Section 6.4 & Appendix G8)."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict

from book2epub.errors import ConfigurationError, ProviderError
from book2epub.providers.anthropic import DEFAULT_ANTHROPIC_MODEL, AnthropicProvider
from book2epub.providers.models import StructuredInferenceRequest
from book2epub.semantic.schemas import build_provider_schema


class SampleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    code: int


def test_anthropic_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-testkey12345678901234567890")
    with patch.dict(sys.modules, {"anthropic": None}):
        with pytest.raises(ConfigurationError) as exc_info:
            AnthropicProvider()
        assert "uv sync --extra semantic-anthropic" in str(exc_info.value)


def test_anthropic_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigurationError) as exc_info:
        AnthropicProvider()
    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


@patch("book2epub.providers.anthropic.AnthropicProvider.__init__", return_value=None)
def test_anthropic_infer_success_with_thinking_block(mock_init: MagicMock) -> None:
    provider = AnthropicProvider()
    provider.model = DEFAULT_ANTHROPIC_MODEL
    provider.name = "anthropic"
    mock_client = MagicMock()
    provider._client = mock_client

    # Response contains an adaptive thinking block AND the structured text block
    thinking_block = SimpleNamespace(type="thinking", thinking="pondering...")
    text_block = SimpleNamespace(type="text", text=json.dumps({"status": "claude_ok", "code": 200}))

    mock_resp = MagicMock()
    mock_resp.id = "msg_anthropic_1"
    mock_resp.content = [thinking_block, text_block]
    mock_resp.usage.input_tokens = 180
    mock_resp.usage.output_tokens = 55
    mock_client.messages.create.return_value = mock_resp

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-ant-1",
        system_instruction="Instructions for Claude",
        user_text="User prompt for Claude",
        response_model_name="SampleResponse",
        response_schema=schema,
        max_output_tokens=4096,
    )

    validated, result = provider.infer(req, SampleResponse)
    assert isinstance(validated, SampleResponse)
    assert validated.status == "claude_ok"
    assert validated.code == 200
    assert result.usage.raw_provider_request_id == "msg_anthropic_1"
    assert result.usage.input_tokens == 180
    assert result.usage.output_tokens == 55

    mock_client.messages.create.assert_called_once()
    kwargs = mock_client.messages.create.call_args.kwargs

    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["max_tokens"] == 4096
    assert kwargs["system"] == "Instructions for Claude"
    assert kwargs["messages"] == [{"role": "user", "content": "User prompt for Claude"}]
    assert kwargs["output_config"] == {
        "format": {
            "type": "json_schema",
            "schema": schema,
        }
    }


@patch("book2epub.providers.anthropic.AnthropicProvider.__init__", return_value=None)
def test_anthropic_infer_multiple_text_blocks_error(mock_init: MagicMock) -> None:
    provider = AnthropicProvider()
    provider.model = DEFAULT_ANTHROPIC_MODEL
    provider.name = "anthropic"
    mock_client = MagicMock()
    provider._client = mock_client

    mock_resp = MagicMock()
    mock_resp.id = "msg_bad"
    mock_resp.content = [
        SimpleNamespace(type="text", text="block1"),
        SimpleNamespace(type="text", text="block2"),
    ]
    mock_client.messages.create.return_value = mock_resp

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-bad-blocks",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=schema,
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.infer(req, SampleResponse)
    assert "expected exactly 1" in str(exc_info.value)
