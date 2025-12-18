"""
LLM Retry Decorator Module
==========================

Provides decorators for handling API errors with exponential backoff retry logic.

Features:
- Exponential backoff (2s, 4s, 8s, 16s, ...)
- Configurable max retries and base delay
- Handles common API errors: timeout, rate limit, connection errors
- Detailed logging for debugging

Usage:
    from odoo.addons.llm_security.models.llm_retry_decorator import llm_retry

    @llm_retry(max_retries=3, base_delay=2.0)
    def call_api(self, prompt):
        return self.client.chat(prompt)
"""

import functools
import logging
import random
import time
from typing import Callable, Optional, Tuple, Type

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Common API error types to retry
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,  # Includes network-related errors
)

# HTTP status codes that should trigger retry
RETRYABLE_STATUS_CODES = {
    408,  # Request Timeout
    429,  # Too Many Requests (Rate Limit)
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}


class LLMAPIError(Exception):
    """Base exception for LLM API errors"""
    def __init__(self, message, status_code=None, provider=None, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.retryable = retryable


class RateLimitError(LLMAPIError):
    """Raised when API rate limit is exceeded"""
    def __init__(self, message, retry_after=None, **kwargs):
        super().__init__(message, retryable=True, **kwargs)
        self.retry_after = retry_after


class TimeoutAPIError(LLMAPIError):
    """Raised when API request times out"""
    def __init__(self, message, **kwargs):
        super().__init__(message, retryable=True, **kwargs)


class ConnectionAPIError(LLMAPIError):
    """Raised when connection to API fails"""
    def __init__(self, message, **kwargs):
        super().__init__(message, retryable=True, **kwargs)


def _is_retryable_exception(exc: Exception) -> bool:
    """
    Check if an exception should trigger a retry.

    Args:
        exc: The exception to check

    Returns:
        bool: True if the exception is retryable
    """
    # Check if it's one of our custom retryable exceptions
    if isinstance(exc, LLMAPIError) and exc.retryable:
        return True

    # Check for common retryable exceptions
    if isinstance(exc, RETRYABLE_EXCEPTIONS):
        return True

    # Check for HTTP errors with retryable status codes
    # Handle various HTTP error libraries
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        # Try to get from response attribute (requests library)
        response = getattr(exc, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)

    if status_code in RETRYABLE_STATUS_CODES:
        return True

    # Check exception message for common retryable patterns
    exc_message = str(exc).lower()
    retryable_patterns = [
        "rate limit",
        "too many requests",
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "service unavailable",
        "server error",
        "overloaded",
    ]

    for pattern in retryable_patterns:
        if pattern in exc_message:
            return True

    return False


def _get_retry_after(exc: Exception) -> Optional[float]:
    """
    Extract retry-after delay from exception if available.

    Args:
        exc: The exception to extract retry-after from

    Returns:
        float or None: Seconds to wait before retry, or None if not specified
    """
    # Check our custom exception
    if isinstance(exc, RateLimitError) and exc.retry_after:
        return float(exc.retry_after)

    # Check response headers
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", {})
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

    return None


def llm_retry(
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = None,
    on_retry: Callable = None,
):
    """
    Decorator for retrying LLM API calls with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 2.0)
        max_delay: Maximum delay between retries (default: 60.0)
        exponential_base: Base for exponential backoff (default: 2.0)
        jitter: Add random jitter to prevent thundering herd (default: True)
        retryable_exceptions: Additional exception types to retry
        on_retry: Callback function called on each retry with (attempt, exception, delay)

    Returns:
        Decorated function with retry logic

    Example:
        @llm_retry(max_retries=5, base_delay=1.0)
        def call_openai(self, messages):
            return self.client.chat.completions.create(messages=messages)
    """
    if retryable_exceptions is None:
        retryable_exceptions = RETRYABLE_EXCEPTIONS

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as exc:
                    last_exception = exc

                    # Check if we should retry
                    if attempt >= max_retries:
                        _logger.error(
                            f"LLM API call failed after {max_retries + 1} attempts: {exc}"
                        )
                        raise

                    if not _is_retryable_exception(exc):
                        _logger.error(f"LLM API call failed (non-retryable): {exc}")
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )

                    # Check for retry-after header
                    retry_after = _get_retry_after(exc)
                    if retry_after:
                        delay = min(retry_after, max_delay)

                    # Add jitter to prevent thundering herd
                    if jitter:
                        delay = delay * (0.5 + random.random())

                    _logger.warning(
                        f"LLM API call failed (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay:.2f}s: {exc}"
                    )

                    # Call retry callback if provided
                    if on_retry:
                        try:
                            on_retry(attempt + 1, exc, delay)
                        except Exception as callback_exc:
                            _logger.warning(f"Retry callback failed: {callback_exc}")

                    time.sleep(delay)

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def llm_retry_generator(
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
):
    """
    Decorator for retrying LLM API calls that return generators (streaming).

    Similar to llm_retry but handles generator functions properly.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        jitter: Add random jitter to prevent thundering herd

    Example:
        @llm_retry_generator(max_retries=3)
        def stream_chat(self, messages):
            for chunk in self.client.chat.completions.create(messages=messages, stream=True):
                yield chunk
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    # Get the generator
                    gen = func(*args, **kwargs)

                    # Yield items from generator
                    # If an error occurs during iteration, it will be caught
                    for item in gen:
                        yield item

                    # If we get here, streaming completed successfully
                    return

                except Exception as exc:
                    last_exception = exc

                    if attempt >= max_retries:
                        _logger.error(
                            f"LLM streaming API call failed after {max_retries + 1} attempts: {exc}"
                        )
                        raise

                    if not _is_retryable_exception(exc):
                        _logger.error(f"LLM streaming API call failed (non-retryable): {exc}")
                        raise

                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )

                    retry_after = _get_retry_after(exc)
                    if retry_after:
                        delay = min(retry_after, max_delay)

                    if jitter:
                        delay = delay * (0.5 + random.random())

                    _logger.warning(
                        f"LLM streaming API call failed (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay:.2f}s: {exc}"
                    )

                    time.sleep(delay)

            if last_exception:
                raise last_exception

        return wrapper
    return decorator


class RetryConfig:
    """
    Configuration class for retry behavior.

    Can be used to create reusable retry configurations.

    Example:
        OPENAI_RETRY = RetryConfig(max_retries=5, base_delay=1.0)

        @OPENAI_RETRY.decorator
        def call_openai(self, messages):
            ...
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    @property
    def decorator(self):
        """Get the retry decorator with this configuration."""
        return llm_retry(
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            jitter=self.jitter,
        )

    @property
    def generator_decorator(self):
        """Get the generator retry decorator with this configuration."""
        return llm_retry_generator(
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            jitter=self.jitter,
        )


# Pre-configured retry configs for common use cases
DEFAULT_RETRY = RetryConfig(max_retries=3, base_delay=2.0)
AGGRESSIVE_RETRY = RetryConfig(max_retries=5, base_delay=1.0, max_delay=120.0)
CONSERVATIVE_RETRY = RetryConfig(max_retries=2, base_delay=5.0)
