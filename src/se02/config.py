"""Validated CLI/environment/TOML settings; credentials are environment-only."""
from dataclasses import dataclass, field, fields
import math
import os
from pathlib import Path
import tomllib
from urllib.parse import urlsplit
from se02.domain import ValidationError

@dataclass(frozen=True)
class Settings:
    provider: str = 'http'
    base_url: str | None = None
    model: str | None = None
    timeout: float = 60
    max_retries: int = 1
    retry_delay: float = .5
    max_repairs: int = 2
    output_dir: str = 'runs'
    api_key: str | None = field(default=None, repr=False)


def load_config(overrides=None, *, environ=None, config_path=None):
    environ = os.environ if environ is None else environ
    data = {}
    allowed = {f.name for f in fields(Settings)} - {'api_key'}
    if config_path is not None:
        try:
            with Path(config_path).open('rb') as stream:
                data = tomllib.load(stream)
        except (OSError, ValueError):
            raise ValidationError('cannot read valid TOML configuration') from None
        if set(data) - allowed:
            raise ValidationError('configuration contains unknown or forbidden fields')
    for name in allowed:
        raw = environ.get('SE02_' + name.upper())
        if raw is not None:
            try:
                data[name] = int(raw) if name in ('max_retries', 'max_repairs') else float(raw) if name in ('timeout', 'retry_delay') else raw
            except ValueError:
                raise ValidationError(f'invalid environment setting: {name}') from None
    overrides = overrides or {}
    if set(overrides) - allowed:
        raise ValidationError('unknown CLI configuration field')
    data.update({k: v for k, v in overrides.items() if v is not None})
    config = Settings(**data, api_key=environ.get('SE02_API_KEY'))
    if config.provider not in ('http', 'mock'):
        raise ValidationError('provider must be http or mock')
    for name in ('timeout', 'retry_delay'):
        value = getattr(config, name)
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0 or (name == 'timeout' and (value == 0 or value > 600)) or (name == 'retry_delay' and value > 30):
            raise ValidationError(f'invalid {name}')
    for name in ('max_retries', 'max_repairs'):
        value = getattr(config, name)
        if type(value) is not int or value < 0 or (name == 'max_repairs' and value > 2) or (name == 'max_retries' and value > 3):
            raise ValidationError(f'invalid {name}')
    for name in ('base_url', 'model'):
        value = getattr(config, name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValidationError(f'invalid {name}')
    if config.base_url is not None:
        try:
            parsed = urlsplit(config.base_url)
            parsed.port
        except ValueError:
            raise ValidationError("invalid base_url") from None
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1')):
            raise ValidationError('invalid base_url')
    if not isinstance(config.output_dir, str) or not config.output_dir.strip():
        raise ValidationError('invalid output_dir')
    return config
