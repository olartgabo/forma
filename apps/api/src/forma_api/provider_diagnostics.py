"""Safe, provider-reported usage diagnostics shared by API runtimes.

Only counts actually reported by the provider for the current request are
exposed. Missing or malformed counts stay unknown; nothing here estimates
prices, billed cost or tokens the provider did not report.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import Field, StrictInt

from forma_domain.models import Record

MAX_MODEL_CALLS = 16
MAX_TOKENS_PER_CALL = 1_000_000_000
MAX_TOKENS_TOTAL = MAX_MODEL_CALLS * MAX_TOKENS_PER_CALL


class ProviderUsage(Record):
    """Bounded aggregate of provider-reported usage for one request."""

    model_calls: StrictInt = Field(ge=0, le=MAX_MODEL_CALLS)
    input_tokens: StrictInt | None = Field(default=None, ge=0, le=MAX_TOKENS_TOTAL)
    output_tokens: StrictInt | None = Field(default=None, ge=0, le=MAX_TOKENS_TOTAL)


def _reported(trace: Any, key: str) -> Any:
    if isinstance(trace, Mapping):
        return trace.get(key)
    return getattr(trace, key, None)


def _total(traces: list[Any], key: str) -> int | None:
    if not traces:
        return None
    values = [_reported(trace, key) for trace in traces]
    if any(
        type(value) is not int or not 0 <= value <= MAX_TOKENS_PER_CALL
        for value in values
    ):
        return None
    total = sum(values)
    return total if total <= MAX_TOKENS_TOTAL else None


def summarize_usage(traces: Iterable[Any] | None) -> ProviderUsage:
    """Aggregate request-local traces; any missing/malformed count is unknown."""

    local = list(traces) if traces is not None else []
    return ProviderUsage(
        model_calls=len(local),
        input_tokens=_total(local, "input_tokens"),
        output_tokens=_total(local, "output_tokens"),
    )


__all__ = ["ProviderUsage", "summarize_usage"]
