"""Context-local attempt events; provider calls need no workflow dependency."""

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, kw_only=True)
class ProviderAttempt:
    attempt: int
    status: Literal["running", "completed", "failed"]
    elapsed_ms: float
    detail: str


_observer: ContextVar[Callable[[ProviderAttempt], None] | None] = ContextVar("se02_provider_observer", default=None)


@contextmanager
def attempt_scope(callback: Callable[[ProviderAttempt], None]):
    token = _observer.set(callback)
    try:
        yield
    finally:
        _observer.reset(token)


def emit_attempt(event: ProviderAttempt) -> None:
    callback = _observer.get()
    if callback is not None:
        callback(event)
