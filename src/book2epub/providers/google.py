"""Google Gemini structured output provider adapter using Interactions API
(M7 spec Section 6.2, Appendix G6)."""

import base64
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
from book2epub.providers.retry import execute_with_retry

DEFAULT_GOOGLE_MODEL = "gemini-3.1-pro-preview"


class GoogleProvider:
    """Provider adapter for Google Gemini via Interactions API with Structured Outputs."""

    name: str = "google"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or DEFAULT_GOOGLE_MODEL
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ConfigurationError(
                "Environment variable 'GEMINI_API_KEY' is required for provider 'google'."
            )

        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        except ImportError as e:
            raise ConfigurationError(
                "Google GenAI Python SDK is not installed.\n"
                "Please install it with: uv sync --extra semantic-google"
            ) from e

    @property
    def supports_vision(self) -> bool:
        return True

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        """Execute structured inference against Google Gemini Interactions API."""
        if request.images:
            inputs: list[dict[str, Any]] = []
            for img in request.images:
                b64 = base64.b64encode(img.path.read_bytes()).decode("utf-8")
                inputs.append({
                    "type": "image",
                    "data": b64,
                    "mime_type": img.media_type,
                })
            inputs.append({"type": "text", "text": request.user_text})
            input_val: Any = inputs
        else:
            input_val = request.user_text

        response_format = {
            "type": "text",
            "mime_type": "application/json",
            "schema": request.response_schema,
        }

        generation_config = {
            "thinking_level": request.reasoning_effort,
            "max_output_tokens": request.max_output_tokens,
        }

        start_time = time.perf_counter()

        def _call_google() -> Any:
            return self._client.interactions.create(
                model=self.model,
                system_instruction=request.system_instruction,
                input=input_val,
                response_format=response_format,
                generation_config=generation_config,
                store=False,
            )

        interaction = execute_with_retry(_call_google, provider_name=self.name)
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        raw_text = getattr(interaction, "output_text", "")

        # Local Pydantic validation
        try:
            parsed_json = json.loads(raw_text)
            validated_obj = response_model.model_validate(parsed_json)
        except Exception as first_val_err:
            retry_req_id = f"{request.request_id}-schema-retry"
            try:
                interaction_retry = execute_with_retry(_call_google, provider_name=self.name)
                raw_text = getattr(interaction_retry, "output_text", "")
                parsed_json = json.loads(raw_text)
                validated_obj = response_model.model_validate(parsed_json)
            except Exception as final_val_err:
                raise ProviderError(
                    f"Google Gemini response failed local Pydantic validation: {final_val_err}",
                    details={"provider": self.name, "request_id": retry_req_id},
                ) from first_val_err

        usage_obj = getattr(interaction, "usage", None)
        in_tok = getattr(usage_obj, "input_tokens", None) if usage_obj else None
        out_tok = getattr(usage_obj, "output_tokens", None) if usage_obj else None
        resp_id = getattr(interaction, "id", None)
        usage = ProviderUsage(
            input_tokens=in_tok if isinstance(in_tok, int) else None,
            output_tokens=out_tok if isinstance(out_tok, int) else None,
            raw_provider_request_id=resp_id if isinstance(resp_id, str) else None,
        )

        result = StructuredInferenceResult(
            request_id=request.request_id,
            provider=self.name,
            model=self.model,
            raw_text=raw_text,
            parsed_json=parsed_json,
            usage=usage,
            latency_ms=latency_ms,
        )

        return validated_obj, result
