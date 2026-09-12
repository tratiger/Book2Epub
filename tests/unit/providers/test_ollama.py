"""Unit tests for OllamaProvider adapter (M7 spec Section 6.3 & Appendix G7)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict

from book2epub.errors import ConfigurationError, ProviderError
from book2epub.providers.models import StructuredInferenceRequest
from book2epub.providers.ollama import OllamaProvider
from book2epub.semantic.schemas import build_provider_schema


class SampleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    code: int


def test_ollama_missing_sdk() -> None:
    with patch.dict(sys.modules, {"ollama": None}):
        with pytest.raises(ConfigurationError) as exc_info:
            OllamaProvider(model="llama3.3")
        assert "uv sync --extra semantic-local" in str(exc_info.value)


def test_ollama_missing_model() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        OllamaProvider(model="")
    assert "requires a model identifier" in str(exc_info.value)


@patch("book2epub.providers.ollama.OllamaProvider.__init__", return_value=None)
def test_ollama_infer_success(mock_init: MagicMock) -> None:
    provider = OllamaProvider(model="llama3.3")
    provider.model = "llama3.3"
    provider.name = "ollama"
    provider.host = "http://localhost:11434"
    mock_client = MagicMock()
    provider._client = mock_client

    mock_resp = MagicMock()
    mock_resp.message.content = json.dumps({"status": "success", "code": 200})
    mock_resp.prompt_eval_count = 100
    mock_resp.eval_count = 50
    mock_client.chat.return_value = mock_resp

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-123",
        system_instruction="You are a classifier.",
        user_text="Classify this text.",
        response_model_name="SampleResponse",
        response_schema=schema,
    )

    validated, res = provider.infer(req, SampleResponse)
    assert isinstance(validated, SampleResponse)
    assert validated.status == "success"
    assert validated.code == 200
    assert res.request_id == "req-123"
    assert res.provider == "ollama"
    assert res.model == "llama3.3"
    assert res.usage.input_tokens == 100
    assert res.usage.output_tokens == 50

    mock_client.chat.assert_called_once_with(
        model="llama3.3",
        messages=[
            {"role": "system", "content": "You are a classifier."},
            {"role": "user", "content": "Classify this text."},
        ],
        format=schema,
        options={"temperature": 0, "num_predict": 8192},
        stream=False,
    )


@patch("book2epub.providers.ollama.OllamaProvider.__init__", return_value=None)
def test_ollama_infer_extra_field_rejected(mock_init: MagicMock) -> None:
    """Extra fields must be rejected by Pydantic validation (M7 Section 4 & 12)."""
    provider = OllamaProvider(model="llama3.3")
    provider.model = "llama3.3"
    provider.name = "ollama"
    provider.host = "http://localhost:11434"
    mock_client = MagicMock()
    provider._client = mock_client

    # Model returns forbidden extra field
    bad_resp = MagicMock()
    bad_resp.message.content = json.dumps(
        {"status": "ok", "code": 200, "extra_field": "disallowed"}
    )
    mock_client.chat.return_value = bad_resp

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-extra",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=schema,
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.infer(req, SampleResponse)
    assert "failed local Pydantic schema validation" in str(exc_info.value)
    # Ensure it retried once for schema validation
    assert mock_client.chat.call_count == 2


@patch("book2epub.providers.ollama.OllamaProvider.__init__", return_value=None)
def test_ollama_infer_transient_retry(mock_init: MagicMock) -> None:
    provider = OllamaProvider(model="llama3.3")
    provider.model = "llama3.3"
    provider.name = "ollama"
    provider.host = "http://localhost:11434"
    mock_client = MagicMock()
    provider._client = mock_client

    good_resp = MagicMock()
    good_resp.message.content = json.dumps({"status": "retry_ok", "code": 200})

    # First call raises connection error, second succeeds
    mock_client.chat.side_effect = [
        ConnectionResetError("Connection reset by peer"),
        good_resp,
    ]

    schema = build_provider_schema(SampleResponse)
    req = StructuredInferenceRequest(
        request_id="req-transient",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=schema,
    )

    with patch("time.sleep", return_value=None):
        validated, res = provider.infer(req, SampleResponse)

    assert validated.status == "retry_ok"
    assert mock_client.chat.call_count == 2


@patch("book2epub.providers.ollama.OllamaProvider.__init__", return_value=None)
def test_ollama_length_truncation_skips_schema_retry(
    mock_init: MagicMock, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    provider = OllamaProvider(model="qwen3-vl:8b-instruct")
    provider.model = "qwen3-vl:8b-instruct"
    provider.name = "ollama"
    provider._client = MagicMock()
    provider._client.chat.return_value = {
        "message": {"content": '{"status":"incomplete"'},
        "done_reason": "length",
        "prompt_eval_count": 321,
        "eval_count": 4096,
    }
    req = StructuredInferenceRequest(
        request_id="req-length",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=build_provider_schema(SampleResponse),
        debug_artifact_path=tmp_path / "ollama-truncation.json",
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.infer(req, SampleResponse)

    assert provider._client.chat.call_count == 1
    assert exc_info.value.details["error_type"] == "structured_output_truncated"
    assert exc_info.value.details["done_reason"] == "length"
    assert exc_info.value.details["prompt_eval_count"] == 321
    assert exc_info.value.details["eval_count"] == 4096
    assert exc_info.value.details["raw_response_chars"] > 0
    assert "Ollama truncation" in caplog.text
    assert "error_type=structured_output_truncated" in caplog.text
    assert "request_id=req-length" in caplog.text
    assert "done_reason=length" in caplog.text
    assert "prompt_tokens=321" in caplog.text
    assert "output_tokens=4096" in caplog.text
    debug_artifact = tmp_path / "ollama-truncation.json"
    assert debug_artifact.is_file()
    artifact = json.loads(debug_artifact.read_text(encoding="utf-8"))
    assert artifact["error_type"] == "structured_output_truncated"
    assert artifact["raw_text"] == '{"status":"incomplete"'


@patch("book2epub.providers.ollama.OllamaProvider.__init__", return_value=None)
def test_ollama_stop_malformed_json_retries_once(mock_init: MagicMock) -> None:
    provider = OllamaProvider(model="llama3.3")
    provider.model = "llama3.3"
    provider.name = "ollama"
    provider._client = MagicMock()
    provider._client.chat.side_effect = [
        SimpleNamespace(message=SimpleNamespace(content='{"status":"bad"')),
        SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({"status": "ok", "code": 200})),
            done_reason="stop",
        ),
    ]
    req = StructuredInferenceRequest(
        request_id="req-malformed",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=build_provider_schema(SampleResponse),
    )

    validated, result = provider.infer(req, SampleResponse)

    assert validated.status == "ok"
    assert result.schema_retry_count == 1
    assert result.request_id == "req-malformed-schema-retry"
    assert provider._client.chat.call_count == 2


@patch("book2epub.providers.ollama.OllamaProvider.__init__", return_value=None)
def test_ollama_schema_mismatch_is_classified_after_one_retry(mock_init: MagicMock) -> None:
    provider = OllamaProvider(model="llama3.3")
    provider.model = "llama3.3"
    provider.name = "ollama"
    provider._client = MagicMock()
    bad = {"message": {"content": json.dumps({"status": "bad", "code": 200, "x": 1})}}
    provider._client.chat.return_value = bad
    req = StructuredInferenceRequest(
        request_id="req-schema",
        system_instruction="sys",
        user_text="user",
        response_model_name="SampleResponse",
        response_schema=build_provider_schema(SampleResponse),
    )

    with pytest.raises(ProviderError) as exc_info:
        provider.infer(req, SampleResponse)

    assert provider._client.chat.call_count == 2
    assert exc_info.value.details["error_type"] == "structured_output_schema_mismatch"
