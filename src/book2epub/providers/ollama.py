"""Ollama structured output provider adapter (M7 spec Section 6.3, Appendix G7)."""

import json
import os
import time
from typing import Any

from book2epub.errors import ConfigurationError, ProviderError
from book2epub.providers.base import TBaseModel
from book2epub.providers.models import (
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)
from book2epub.providers.retry import execute_with_retry_detailed


class OllamaProvider:
    """Provider adapter for local Ollama with JSON Schema structured outputs."""

    name: str = "ollama"

    def __init__(self, model: str, host: str | None = None) -> None:
        if not model:
            raise ConfigurationError(
                "Ollama provider requires a model identifier. "
                "Specify with '--semantic-model <model_name>'."
            )
        self.model = model
        self.host = host or os.environ.get("BOOK2EPUB_OLLAMA_HOST", "http://localhost:11434")

        try:
            import ollama
            self._client = ollama.Client(host=self.host)
        except ImportError as e:
            raise ConfigurationError(
                "Ollama Python SDK is not installed.\n"
                "Please install it with: uv sync --extra semantic-local"
            ) from e

    @property
    def supports_vision(self) -> bool:
        return True

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        """Execute structured inference against Ollama."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.system_instruction},
        ]

        if request.images:
            user_msg: dict[str, Any] = {
                "role": "user",
                "content": request.user_text,
                "images": [str(img.path) for img in request.images],
            }
        else:
            user_msg = {
                "role": "user",
                "content": request.user_text,
            }
        messages.append(user_msg)

        start_time = time.perf_counter()

        def _call_ollama() -> Any:
            return self._client.chat(
                model=self.model,
                messages=messages,
                format=request.response_schema,
                options={"temperature": 0},
                stream=False,
            )

        first_execution = execute_with_retry_detailed(_call_ollama, provider_name=self.name)
        resp = first_execution.value
        transport_attempt_count = first_execution.attempt_count
        response_objects = [resp]
        adopted_request_id = request.request_id
        schema_retry_count = 0

        # Extract message content
        def extract_content(response: Any) -> str:
            if isinstance(response, dict):
                return str(response.get("message", {}).get("content", ""))
            message = getattr(response, "message", None)
            return str(getattr(message, "content", "")) if message is not None else ""

        raw_text = extract_content(resp)

        # Validate with Pydantic locally (Section 4 rule 3)
        try:
            parsed_json = json.loads(raw_text)
            validated_obj = response_model.model_validate(parsed_json)
        except Exception as first_val_err:
            # Allow 1 schema retry on local Pydantic validation failure
            retry_req_id = f"{request.request_id}-schema-retry"
            try:
                schema_retry_count = 1
                retry_execution = execute_with_retry_detailed(
                    _call_ollama, provider_name=self.name
                )
                resp_retry = retry_execution.value
                response_objects.append(resp_retry)
                transport_attempt_count += retry_execution.attempt_count
                resp = resp_retry
                raw_text = extract_content(resp_retry)
                parsed_json = json.loads(raw_text)
                validated_obj = response_model.model_validate(parsed_json)
                adopted_request_id = retry_req_id
            except Exception as final_val_err:
                raise ProviderError(
                    f"Ollama response failed local Pydantic schema validation: {final_val_err}",
                    details={"provider": self.name, "request_id": retry_req_id},
                ) from first_val_err

        in_tok = getattr(resp, "prompt_eval_count", None)
        out_tok = getattr(resp, "eval_count", None)
        provider_request_ids = [
            response_id
            for response in response_objects
            if isinstance(
                response_id := (
                    response.get("id")
                    if isinstance(response, dict)
                    else getattr(response, "id", None)
                ),
                str,
            )
        ]
        total_in = sum(
            value
            for response in response_objects
            if isinstance(
                value := (
                    response.get("prompt_eval_count")
                    if isinstance(response, dict)
                    else getattr(response, "prompt_eval_count", None)
                ),
                int,
            )
        )
        total_out = sum(
            value
            for response in response_objects
            if isinstance(
                value := (
                    response.get("eval_count")
                    if isinstance(response, dict)
                    else getattr(response, "eval_count", None)
                ),
                int,
            )
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        final_response_id = (
            resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)
        )
        usage = ProviderUsage(
            input_tokens=in_tok if isinstance(in_tok, int) else None,
            output_tokens=out_tok if isinstance(out_tok, int) else None,
            raw_provider_request_id=(
                final_response_id if isinstance(final_response_id, str) else None
            ),
            provider_request_ids=provider_request_ids,
            total_input_tokens=total_in or None,
            total_output_tokens=total_out or None,
            attempt_count=transport_attempt_count,
            schema_retry_count=schema_retry_count,
        )

        result = StructuredInferenceResult(
            request_id=adopted_request_id,
            provider=self.name,
            model=self.model,
            raw_text=raw_text,
            parsed_json=parsed_json,
            usage=usage,
            latency_ms=latency_ms,
            attempt_count=transport_attempt_count,
            transport_attempt_count=transport_attempt_count,
            schema_retry_count=schema_retry_count,
            provider_request_ids=provider_request_ids,
        )

        return validated_obj, result
