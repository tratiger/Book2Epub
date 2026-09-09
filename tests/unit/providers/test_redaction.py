"""Unit tests for secret and token redaction (M7 spec Section 9 & Appendix G11)."""

from book2epub.providers.redaction import (
    redact_dict,
    redact_secrets_from_text,
    redact_sensitive_headers,
)


def test_redact_secrets_from_text() -> None:
    text = (
        "Calling api with sk-proj-12345678901234567890123456 "
        "and Bearer eyJhbGciOiJSUzI1NiJ9.test"
    )
    redacted = redact_secrets_from_text(text)
    assert "sk-proj" not in redacted
    assert "[REDACTED_API_KEY]" in redacted
    assert "[REDACTED_TOKEN]" in redacted
    assert "Calling api with" in redacted


def test_redact_sensitive_headers() -> None:
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer some-super-secret-token",
        "x-api-key": "secret-key-123",
        "User-Agent": "Book2Epub/1.0",
    }
    redacted = redact_sensitive_headers(headers)
    assert redacted["Content-Type"] == "application/json"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["x-api-key"] == "[REDACTED]"
    assert redacted["User-Agent"] == "Book2Epub/1.0"


def test_redact_dict_nested() -> None:
    data = {
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "api_key": "sk-secret12345678901234567890",
        "nested": {
            "token": "sensitive_token_val",
            "safe_field": "hello world",
            "list_items": [
                {"secret": "nested_secret_123"},
                "plain string",
                "string with AIzaSyD1234567890123456789012345678901 in it",
            ],
        },
    }
    redacted = redact_dict(data)
    assert redacted["provider"] == "openai"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["safe_field"] == "hello world"
    assert redacted["nested"]["list_items"][0]["secret"] == "[REDACTED]"
    assert redacted["nested"]["list_items"][1] == "plain string"
    assert "AIzaSyD" not in redacted["nested"]["list_items"][2]
    assert "[REDACTED_API_KEY]" in redacted["nested"]["list_items"][2]
