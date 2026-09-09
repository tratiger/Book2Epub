"""OpenAI structured output provider adapter using Responses API
(M7 spec Section 6.1, Appendix G5)."""

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

DEFAULT_OPENAI_MODEL = "gpt-5.6-sol"


class OpenAIProvider:
    """Provider adapter for OpenAI Responses API with strict Structured Outputs."""

    name: str = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or DEFAULT_OPENAI_MODEL
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ConfigurationError(
                "Environment variable 'OPENAI_API_KEY' is required for provider 'openai'."
            )

        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        except ImportError as e:
            raise ConfigurationError(
                "OpenAI Python SDK is not installed.\n"
                "Please install it with: uv sync --extra semantic-openai"
            ) from e

    @property
    def supports_vision(self) -> bool:
        return True

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        """Execute structured inference against OpenAI Responses API."""
        if request.images:
            content: list[dict[str, Any]] = []
            for img in request.images:
                b64 = base64.b64encode(img.path.read_bytes()).decode("ascii")
                data_url = f"data:{img.media_type};base64,{b64}"
                content.append({
                    "type": "input_image",
                    "image_url": data_url,
                    "detail": "high",
                })
            content.append({"type": "input_text", "text": request.user_text})
            input_val: Any = [{"role": "user", "content": content}]
        else:
            input_val = request.user_text

        text_config: dict[str, Any] = {
            "format": {
                "type": "json_schema",
                "name": request.response_model_name,
                "strict": True,
                "schema": request.response_schema,
            }
        }

        start_time = time.perf_counter()

        def _call_openai() -> Any:
            return self._client.responses.create(
                model=self.model,
                instructions=request.system_instruction,
                input=input_val,
                text=text_config,
                reasoning={"effort": request.reasoning_effort},
                max_output_tokens=request.max_output_tokens,
                store=False,
            )

        resp = execute_with_retry(_call_openai, provider_name=self.name)
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # Check completed status
        resp_status = getattr(resp, "status", "completed")
        if resp_status != "completed":
            raise ProviderError(
                f"OpenAI response status was not 'completed': '{resp_status}'",
                details={"provider": self.name, "status": resp_status},
            )

        raw_text = getattr(resp, "output_text", "")

        # Local Pydantic validation
        try:
            parsed_json = json.loads(raw_text)
            validated_obj = response_model.model_validate(parsed_json)
        except Exception as first_val_err:
            retry_req_id = f"{request.request_id}-schema-retry"
            try:
                resp_retry = execute_with_retry(_call_openai, provider_name=self.name)
                raw_text = getattr(resp_retry, "output_text", "")
                parsed_json = json.loads(raw_text)
                validated_obj = response_model.model_validate(parsed_json)
            except Exception as final_val_err:
                raise ProviderError(
                    f"OpenAI response failed local Pydantic validation: {final_val_err}",
                    details={"provider": self.name, "request_id": retry_req_id},
                ) from first_val_err

        usage_obj = getattr(resp, "usage", None)
        in_tok = getattr(usage_obj, "input_tokens", None) if usage_obj else None
        out_tok = getattr(usage_obj, "output_tokens", None) if usage_obj else None
        resp_id = getattr(resp, "id", None)
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
