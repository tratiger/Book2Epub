"""Schema-retry audit contract tests for every provider adapter."""

from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field

from book2epub.providers.anthropic import AnthropicProvider
from book2epub.providers.google import GoogleProvider
from book2epub.providers.models import StructuredInferenceRequest
from book2epub.providers.ollama import OllamaProvider
from book2epub.providers.openai import OpenAIProvider
from book2epub.semantic.schemas import build_provider_schema


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    confidence: float = Field(ge=0.0, le=1.0)


def _request() -> StructuredInferenceRequest:
    return StructuredInferenceRequest(
        request_id="retry-contract",
        system_instruction="system",
        user_text="user",
        response_model_name="Response",
        response_schema=build_provider_schema(_Response),
    )


def _assert_adopted(result) -> None:  # type: ignore[no-untyped-def]
    assert result.request_id == "retry-contract-schema-retry"
    assert result.raw_text == '{"status": "B", "confidence": 0.9}'
    assert result.parsed_json["status"] == "B"
    assert result.usage.raw_provider_request_id == "response-B"
    assert result.usage.provider_request_ids == ["response-A", "response-B"]
    assert result.usage.total_input_tokens == 30
    assert result.usage.total_output_tokens == 3
    assert result.usage.attempt_count == 2
    assert result.usage.schema_retry_count == 1
    assert result.attempt_count == 2
    assert result.schema_retry_count == 1


def test_openai_schema_retry_adopts_second_response() -> None:
    provider = object.__new__(OpenAIProvider)
    provider.model = "test-model"
    provider.name = "openai"
    first = SimpleNamespace(
        status="completed",
        id="response-A",
        output_text='{"status": "A", "confidence": 2.0}',
        usage=SimpleNamespace(input_tokens=10, output_tokens=1),
    )
    second = SimpleNamespace(
        status="completed",
        id="response-B",
        output_text='{"status": "B", "confidence": 0.9}',
        usage=SimpleNamespace(input_tokens=20, output_tokens=2),
    )
    calls = iter([first, second])
    provider._client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **_: next(calls))
    )

    _, result = provider.infer(_request(), _Response)
    _assert_adopted(result)


def test_google_schema_retry_adopts_second_response() -> None:
    provider = object.__new__(GoogleProvider)
    provider.model = "test-model"
    provider.name = "google"
    first = SimpleNamespace(
        id="response-A",
        output_text='{"status": "A", "confidence": 2.0}',
        usage=SimpleNamespace(input_tokens=10, output_tokens=1),
    )
    second = SimpleNamespace(
        id="response-B",
        output_text='{"status": "B", "confidence": 0.9}',
        usage=SimpleNamespace(input_tokens=20, output_tokens=2),
    )
    calls = iter([first, second])
    provider._client = SimpleNamespace(
        interactions=SimpleNamespace(create=lambda **_: next(calls))
    )

    _, result = provider.infer(_request(), _Response)
    _assert_adopted(result)


def test_anthropic_schema_retry_adopts_second_response() -> None:
    provider = object.__new__(AnthropicProvider)
    provider.model = "test-model"
    provider.name = "anthropic"
    first = SimpleNamespace(
        id="response-A",
        content=[SimpleNamespace(type="text", text='{"status": "A", "confidence": 2.0}')],
        usage=SimpleNamespace(input_tokens=10, output_tokens=1),
    )
    second = SimpleNamespace(
        id="response-B",
        content=[SimpleNamespace(type="text", text='{"status": "B", "confidence": 0.9}')],
        usage=SimpleNamespace(input_tokens=20, output_tokens=2),
    )
    calls = iter([first, second])
    provider._client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **_: next(calls))
    )

    _, result = provider.infer(_request(), _Response)
    _assert_adopted(result)


def test_ollama_schema_retry_adopts_second_response() -> None:
    provider = object.__new__(OllamaProvider)
    provider.model = "test-model"
    provider.name = "ollama"
    first = SimpleNamespace(
        id="response-A",
        message=SimpleNamespace(content='{"status": "A", "confidence": 2.0}'),
        prompt_eval_count=10,
        eval_count=1,
    )
    second = SimpleNamespace(
        id="response-B",
        message=SimpleNamespace(content='{"status": "B", "confidence": 0.9}'),
        prompt_eval_count=20,
        eval_count=2,
    )
    calls = iter([first, second])
    provider._client = SimpleNamespace(chat=lambda **_: next(calls))

    _, result = provider.infer(_request(), _Response)
    _assert_adopted(result)


def test_anthropic_schema_adapter_preserves_local_constraints() -> None:
    canonical = build_provider_schema(_Response)
    anthropic = build_provider_schema(_Response, provider="anthropic")
    assert canonical["properties"]["confidence"]["minimum"] == 0.0
    assert "minimum" not in anthropic["properties"]["confidence"]
