"""Typed error taxonomy used across adapters, domain code, and agents.

The rule is simple: adapters *raise* typed errors, agents *translate* them into
degraded results, and the UI renders the degraded state. Nothing catches a bare
``Exception`` and continues silently.
"""

from __future__ import annotations


class CFBError(Exception):
    """Base class for every expected application error."""


class ConfigError(CFBError):
    """Invalid or unsafe configuration detected at startup."""


class ContractError(CFBError):
    """An inter-agent payload failed schema or semantic validation."""


class LeakageError(CFBError):
    """A field, label, or score attempted to use post-kickoff information."""


class BudgetExhausted(CFBError):
    """A run, provider, or phase exceeded its wall-clock/token/page budget."""


class ProviderError(CFBError):
    """Base class for external provider failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider: str | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.retry_after_s = retry_after_s


class TransientProviderError(ProviderError):
    """A failure that may succeed on retry (timeout, 429, 5xx, connection reset)."""


class PermanentProviderError(ProviderError):
    """A failure that must not be retried (400, 401, 403, 404, schema mismatch)."""


class SystemOneError(ProviderError):
    """Base class for the VT ARC decision-model (``systemone``) envelope."""


class SystemOneThrottled(SystemOneError):
    """HTTP 429 ``user_concurrent`` or HTTP 503 ``queue_timeout``."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_s: float,
        status_code: int = 429,
        provider: str = "systemone",
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            provider=provider,
            retry_after_s=retry_after_s,
        )


class SystemOneOverloaded(SystemOneError):
    """HTTP 502 ``replica_unavailable``."""


class SystemOnePayloadTooLarge(SystemOneError):
    """HTTP 413: the request body exceeded the 8 MiB limit."""


class SystemOneInputLimit(SystemOneError):
    """HTTP 500 caused by exceeding the per-question 8,192-token input limit."""
