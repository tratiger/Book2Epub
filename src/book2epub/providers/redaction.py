"""Utilities for redacting API keys, bearer tokens, and secrets from logs and artifacts."""

import re
from typing import Any

SENSITIVE_KEY_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "proxy_authorization",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
}

API_KEY_REGEX = re.compile(
    r"(sk-[a-zA-Z0-9_\-]{20,}|AIza[0-9A-Za-z\-_]{30,45}|ghp_[0-9a-zA-Z]{36}|xox[baprs]-[0-9a-zA-Z]{10,})"
)


def redact_secrets_from_text(text: str) -> str:
    """Redact known API key patterns and Bearer tokens from text."""
    if not text:
        return ""
    redacted = API_KEY_REGEX.sub("[REDACTED_API_KEY]", text)
    redacted = re.sub(
        r"(Bearer\s+)[A-Za-z0-9\-_.~+/]+=*",
        r"\1[REDACTED_TOKEN]",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


def redact_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with sensitive authorization fields redacted."""
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in ("authorization", "x-api-key", "api-key", "proxy-authorization"):
            out[k] = "[REDACTED]"
        else:
            out[k] = redact_secrets_from_text(v)
    return out


def redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact dictionary keys and string values."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if k.lower() in SENSITIVE_KEY_NAMES:
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = redact_dict(v)
        elif isinstance(v, list):
            out[k] = [
                redact_dict(item)
                if isinstance(item, dict)
                else (redact_secrets_from_text(item) if isinstance(item, str) else item)
                for item in v
            ]
        elif isinstance(v, str):
            out[k] = redact_secrets_from_text(v)
        else:
            out[k] = v
    return out
