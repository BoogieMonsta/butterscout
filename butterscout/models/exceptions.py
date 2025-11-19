"""Custom exceptions for Butterscout."""


class ButterscoutError(Exception):
    """Base class for Butterscout exceptions."""

    def __init__(self, message: str, headers: dict[str, str] | None = None):
        self.message = message
        self.headers = headers or {}
        super().__init__(message)


class UpstreamProviderError(ButterscoutError):
    """Raised when an upstream provider (SearXNG, Crawl4AI) fails."""

    def __init__(
        self,
        message: str,
        component: str,
        is_timeout: bool = False,
        headers: dict[str, str] | None = None,
    ):
        self.component = component
        self.is_timeout = is_timeout
        super().__init__(message, headers)


class RateLimitExceededError(ButterscoutError):
    """Raised when rate limit is exceeded."""

    def __init__(
        self, message: str, retry_after: float | None = None, headers: dict[str, str] | None = None
    ):
        self.retry_after = retry_after
        super().__init__(message, headers)


class MaxResultsExceededError(ButterscoutError):
    """Raised when requested max_results exceeds limit."""

    def __init__(
        self, message: str, requested: int, allowed: int, headers: dict[str, str] | None = None
    ):
        self.requested = requested
        self.allowed = allowed
        super().__init__(message, headers)


class UnauthorizedError(ButterscoutError):
    """Raised when authentication fails."""

    def __init__(self, message: str, headers: dict[str, str] | None = None):
        super().__init__(message, headers)
