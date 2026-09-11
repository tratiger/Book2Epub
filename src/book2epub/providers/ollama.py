"""Ollama structured output provider adapter (M7 spec Section 6.3, Appendix G7)."""

import json
import logging
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

logger = logging.getLogger(__name__)


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
                options={"temperature": 0, "num_predict": request.max_output_tokens},
                stream=False,
            )

        first_execution = execute_with_retry_detailed(_call_ollama, provider_name=self.name)
        resp = first_execution.value
        transport_attempt_count = first_execution.attempt_count
        response_objects = [resp]
        adopted_request_id = request.request_id
        schema_retry_count = 0

        def response_value(response: Any, key: str) -> Any:
            if isinstance(response, dict):
                return response.get(key)
            return getattr(response, key, None)

        def metadata(response: Any) -> dict[str, Any]:
            values: dict[str, Any] = {}
            for key in (
                "id",
                "done_reason",
                "prompt_eval_count",
                "eval_count",
                "total_duration",
                "load_duration",
                "prompt_eval_duration",
                "eval_duration",
            ):
                value = response_value(response, key)
                if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                    values[key] = value
            return values

        def is_truncation(response: Any) -> bool:
            reason = metadata(response).get("done_reason")
            if not isinstance(reason, str):
                return False
            normalized = reason.lower().replace("-", "_")
            return normalized in {
                "length",
                "max_tokens",
                "max_output_tokens",
                "context_length",
                "context_limit",
            } or "length" in normalized or "context" in normalized

        # Extract message content
        def extract_content(response: Any) -> str:
            if isinstance(response, dict):
                return str(response.get("message", {}).get("content", ""))
            message = getattr(response, "message", None)
            return str(getattr(message, "content", "")) if message is not None else ""

        raw_text = extract_content(resp)

        def failure_details(response: Any, error_type: str) -> dict[str, Any]:
            details = metadata(response)
            details.update(
                {
                    "error_type": error_type,
                    "provider": self.name,
                    "model": self.model,
                    "request_id": request.request_id,
                    "raw_response_chars": len(extract_content(response)),
                }
            )
            return details

        def validation_error_type(error: Exception) -> str:
            return (
                "structured_output_invalid_json"
                if isinstance(error, json.JSONDecodeError)
                else "structured_output_schema_mismatch"
            )

        # Validate with Pydantic locally (Section 4 rule 3)
        try:
            parsed_json = json.loads(raw_text)
            validated_obj = response_model.model_validate(parsed_json)
        except Exception as first_val_err:
            if is_truncation(resp):
                details = failure_details(resp, "structured_output_truncated")
                raise ProviderError(
                    "Ollama structured output was truncated; same-request schema retry "
                    "was skipped",
                    details=details,
                ) from first_val_err

            # A completed response with malformed JSON/schema mismatch may have
            # one schema retry.  A length/context termination never does.
            retry_req_id = f"{request.request_id}-schema-retry"
            logger.info(
                "Ollama structured output schema retry 1/1 request_id=%s reason=%s",
                request.request_id,
                validation_error_type(first_val_err),
            )
            resp_retry = resp
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
                final_response = resp_retry
                final_type = (
                    "structured_output_truncated"
                    if is_truncation(final_response)
                    else validation_error_type(final_val_err)
                )
                details = failure_details(final_response, final_type)
                details["request_id"] = retry_req_id
                raise ProviderError(
                    f"Ollama response failed local Pydantic schema validation: {final_val_err}",
                    details=details,
                ) from first_val_err

        final_metadata = metadata(resp)
        in_tok = final_metadata.get("prompt_eval_count")
        out_tok = final_metadata.get("eval_count")
        provider_request_ids = [
            response_id
            for response in response_objects
            if isinstance(response_id := metadata(response).get("id"), str)
        ]
        total_in = sum(
            value
            for response in response_objects
            if isinstance(value := metadata(response).get("prompt_eval_count"), int)
        )
        total_out = sum(
            value
            for response in response_objects
            if isinstance(value := metadata(response).get("eval_count"), int)
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        final_response_id = final_metadata.get("id")
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
            done_reason=(
                final_metadata.get("done_reason")
                if isinstance(final_metadata.get("done_reason"), str)
                else None
            ),
            prompt_eval_count=in_tok if isinstance(in_tok, int) else None,
            eval_count=out_tok if isinstance(out_tok, int) else None,
            total_duration=final_metadata.get("total_duration"),
            load_duration=final_metadata.get("load_duration"),
            prompt_eval_duration=final_metadata.get("prompt_eval_duration"),
            eval_duration=final_metadata.get("eval_duration"),
            response_chars=len(raw_text),
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
            done_reason=usage.done_reason,
            response_chars=len(raw_text),
        )

        return validated_obj, result
