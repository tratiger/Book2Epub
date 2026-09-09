"""Retry policy and transient error classification for provider requests (Appendix G9)."""

import logging
import random
import time
from collections.abc import Callable

from book2epub.errors import ProviderError

logger = logging.getLogger(__name__)


def is_transient_error(e: Exception) -> bool:
    """
    Classify whether an exception represents a retryable transient error:
    - connection reset / socket timeout
    - HTTP 408, 429, 5xx
    """
    msg = str(e).lower()

    # Explicit HTTP status codes
    status_code = getattr(e, "status_code", None) or getattr(e, "code", None)
    if isinstance(status_code, int):
        if status_code in (408, 429) or (500 <= status_code < 600):
            return True
        if status_code in (400, 401, 403, 404):
            return False

    # Check common transient substrings
    if any(
        kw in msg
        for kw in (
            "rate limit",
            "too many requests",
            "429",
            "connection reset",
            "connection refused",
            "timed out",
            "timeout",
            "temporary failure",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
            "500",
            "502",
            "503",
            "504",
        )
    ):
        return True

    return False


def execute_with_retry[T](
    func: Callable[[], T],
    provider_name: str,
    max_attempts: int = 3,
    initial_backoff: float = 2.0,
) -> T:
    """
    Execute a provider network call with bounded exponential backoff on transient errors
    (M7 spec Section 8, Appendix G9).
    """
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as e:
            last_error = e
            if not is_transient_error(e) or attempt == max_attempts:
                logger.warning(
                    "Provider '%s' error (attempt %d/%d, non-retryable or max reached): %s",
                    provider_name,
                    attempt,
                    max_attempts,
                    e,
                )
                if isinstance(e, ProviderError):
                    raise
                raise ProviderError(
                    f"Provider '{provider_name}' request failed: {e}",
                    details={"provider": provider_name, "attempt": attempt},
                ) from e

            # Jittered exponential delay
            delay = (initial_backoff ** (attempt - 1)) + random.uniform(0.1, 0.5)
            logger.info(
                "Provider '%s' transient error on attempt %d/%d; retrying in %.2fs: %s",
                provider_name,
                attempt,
                max_attempts,
                delay,
                e,
            )
            time.sleep(delay)

    assert last_error is not None
    raise ProviderError(
        f"Provider '{provider_name}' failed after {max_attempts} attempts: {last_error}",
        details={"provider": provider_name, "attempts": max_attempts},
    ) from last_error
