"""Strict, immutable JSON contracts using only the standard library."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
import math
from pathlib import PurePosixPath
import re
from types import MappingProxyType, UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints

from .errors import ValidationError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValidationError(f"{name}: expected a safe identifier of 1..128 ASCII characters")


def text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name}: must not be blank")


def relative_ref(value: str) -> str:
    """Accept portable POSIX references, excluding Windows aliases and traversal."""
    text(value, "reference")
    path = PurePosixPath(value)
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)}
    parts = value.split("/")
    if (path.is_absolute() or any(c in value for c in '\\:<>"|?*')
            or any(ord(c) < 32 for c in value)
            or any(p in ("", ".", "..") or p.endswith((" ", "."))
                   or p.split(".")[0].upper() in reserved for p in parts)):
        raise ValidationError("reference: expected a safe relative POSIX path")
    return value


def _value(annotation, value, *, decode=False):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        for option in args:
            try:
                return _value(option, value, decode=decode)
            except ValidationError:
                pass
        raise ValidationError("value does not match any allowed type")
    if origin is Literal:
        if not any(type(value) is type(a) and value == a for a in args):
            raise ValidationError(f"expected one of {args}")
        return value
    if origin is tuple:
        if not isinstance(value, (tuple, list)):
            raise ValidationError("expected an array")
        return tuple(_value(args[0], v, decode=decode) for v in value)
    if origin is Mapping:
        if not isinstance(value, Mapping):
            raise ValidationError("expected an object")
        return MappingProxyType({_value(args[0], k, decode=decode): _value(args[1], v, decode=decode)
                                 for k, v in value.items()})
    if annotation is datetime:
        if decode and isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValidationError("invalid ISO 8601 datetime") from exc
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValidationError("expected a timezone-aware datetime")
        return value
    if isinstance(annotation, type) and issubclass(annotation, Contract):
        if decode and isinstance(value, Mapping):
            return annotation.from_dict(value)
        if not isinstance(value, annotation):
            raise ValidationError(f"expected {annotation.__name__}")
        return value
    if annotation is float:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValidationError("expected a finite number")
        return float(value)
    if type(value) is not annotation:
        raise ValidationError(f"expected {getattr(annotation, '__name__', annotation)}")
    return value


def _json(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_json(v) for v in value]
    return value


class Contract:
    def __post_init__(self):
        annotations = get_type_hints(type(self))
        for field in fields(self):
            try:
                object.__setattr__(self, field.name, _value(annotations[field.name], getattr(self, field.name)))
            except ValidationError as exc:
                raise ValidationError(f"{type(self).__name__}.{field.name}: {exc}") from exc
        self.validate()

    def validate(self):
        """Subclasses add semantic invariants after strict type checking."""

    def to_dict(self) -> dict:
        return _json(self)

    @classmethod
    def from_dict(cls, data: Mapping):
        if not isinstance(data, Mapping):
            raise ValidationError(f"{cls.__name__}: expected an object")
        annotations = get_type_hints(cls)
        if set(data) - set(annotations):
            raise ValidationError(f"{cls.__name__}: unknown fields")
        try:
            return cls(**{k: _value(annotations[k], v, decode=True) for k, v in data.items()})
        except TypeError as exc:
            raise ValidationError(f"{cls.__name__}: missing required fields") from exc
