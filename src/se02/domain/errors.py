"""Stable exception types shared by the application layers."""


class DomainError(Exception):
    """Base application error."""


class ValidationError(DomainError, ValueError):
    """An input violates a domain contract."""


class StorageError(DomainError):
    """A repository operation could not be completed."""


class ProviderError(DomainError):
    """A model call failed; retry policy belongs to the provider layer."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable
