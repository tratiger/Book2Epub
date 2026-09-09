"""Anthropic structured output provider adapter (M7 spec Section 6.4, Appendix G8)."""

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

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"


class AnthropicProvider:
    """Provider adapter for Anthropic Claude with strict Structured Outputs."""

    name: str = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ConfigurationError(
                "Environment variable 'ANTHROPIC_API_KEY' is required for provider 'anthropic'."
            )

        try:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        except ImportError as e:
            raise ConfigurationError(
                "Anthropic Python SDK is not installed.\n"
                "Please install it with: uv sync --extra semantic-anthropic"
            ) from e

    @property
    def supports_vision(self) -> bool:
        return True

    def _extract_raw_text(self, response: Any) -> str:
        """
        Safely extract the single structured-output text block, ignoring adaptive
        thinking blocks (SPEC_AUDIT_REPORT Section 3.J, Appendix G8).
        """
        content_blocks = getattr(response, "content", [])
        text_blocks = [
            b
            for b in content_blocks
            if getattr(b, "type", None) == "text"
            or (hasattr(b, "text") and getattr(b, "type", None) != "thinking")
        ]
        if len(text_blocks) != 1:
            raise ProviderError(
                f"Anthropic returned {len(text_blocks)} text blocks; expected exactly 1.",
                details={"provider": self.name, "total_blocks": len(content_blocks)},
            )
        return getattr(text_blocks[0], "text", "")

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        """Execute structured inference against Anthropic API."""
        if request.images:
            content: list[dict[str, Any]] = []
            for img in request.images:
                b64 = base64.b64encode(img.path.read_bytes()).decode("ascii")
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type,
                        "data": b64,
                    },
                })
            content.append({"type": "text", "text": request.user_text})
            messages = [{"role": "user", "content": content}]
        else:
            messages = [{"role": "user", "content": request.user_text}]

        output_config = {
            "format": {
                "type": "json_schema",
                "schema": request.response_schema,
            }
        }

        start_time = time.perf_counter()

        def _call_anthropic() -> Any:
            return self._client.messages.create(
                model=self.model,
                max_tokens=request.max_output_tokens,
                system=request.system_instruction,
                messages=messages,
                output_config=output_config,
            )

        resp = execute_with_retry(_call_anthropic, provider_name=self.name)
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        raw_text = self._extract_raw_text(resp)

        # Local Pydantic validation
        try:
            parsed_json = json.loads(raw_text)
            validated_obj = response_model.model_validate(parsed_json)
        except Exception as first_val_err:
            retry_req_id = f"{request.request_id}-schema-retry"
            try:
                resp_retry = execute_with_retry(_call_anthropic, provider_name=self.name)
                raw_text = self._extract_raw_text(resp_retry)
                parsed_json = json.loads(raw_text)
                validated_obj = response_model.model_validate(parsed_json)
            except Exception as final_val_err:
                raise ProviderError(
                    f"Anthropic response failed local Pydantic validation: {final_val_err}",
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
