"""Bounded non-streaming Chat Completions adapter, with redacted errors."""

from http.client import HTTPException
import json
import math
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from se02.domain import ProviderError, ValidationError
from .base import ProviderRequest
from .telemetry import ProviderAttempt, emit_attempt

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _finite(value, name, minimum, maximum, *, inclusive_min=True):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value > maximum or value < minimum or (not inclusive_min and value == minimum)):
        raise ValidationError(f"{name}: outside allowed numeric range")


def _valid_url(base_url):
    if not isinstance(base_url, str) or not base_url.strip() or any(c.isspace() or ord(c) < 32 for c in base_url):
        raise ValidationError("base_url: expected an absolute HTTP(S) URL")
    try:
        parsed = urlsplit(base_url)
        if not parsed.hostname or parsed.port == 0:
            raise ValueError("invalid host or port")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("HTTPS required except for loopback tests")
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError("credentials/query/fragment not allowed")
    except ValueError as exc:
        raise ValidationError("base_url: use HTTPS (loopback HTTP allowed), without credentials, query or fragment") from None
    return base_url.rstrip("/")


def _contains_credential(value, credential):
    if isinstance(value, str):
        return credential in value
    if isinstance(value, dict):
        return any(_contains_credential(k, credential) or _contains_credential(v, credential)
                   for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_credential(v, credential) for v in value)
    return False


class HttpProvider:
    """One retry by default. Socket timeouts do not impose a workflow-wide deadline."""

    def __init__(self, *, base_url: str, model: str, api_key: str, timeout: float = 60,
                 max_retries: int = 1, retry_delay: float = .5, reasoning_effort: str | None = None):
        self.base_url = _valid_url(base_url)
        if not isinstance(model, str) or not model.strip() or any(ord(c) < 32 for c in model):
            raise ValidationError("model: expected a nonempty model ID")
        if (not isinstance(api_key, str) or not api_key.strip()
                or any(ord(c) < 33 or ord(c) > 126 for c in api_key)):
            raise ValidationError("api_key: expected a nonempty ASCII credential without whitespace")
        _finite(timeout, "timeout", 0, 600, inclusive_min=False)
        _finite(retry_delay, "retry_delay", 0, 30)
        if type(max_retries) is not int or not 0 <= max_retries <= 3:
            raise ValidationError("max_retries: expected an integer in 0..3")
        if reasoning_effort not in (None, "none", "low", "high", "max"):
            raise ValidationError("unsupported reasoning_effort")
        self.model, self._api_key = model, api_key
        self.timeout, self.max_retries, self.retry_delay = timeout, max_retries, retry_delay
        self.reasoning_effort = reasoning_effort
        self._opener = build_opener(_NoRedirect())

    def __repr__(self):
        return f"HttpProvider(model={self.model!r}, timeout={self.timeout}, max_retries={self.max_retries})"

    def complete(self, request: ProviderRequest) -> str:
        if not isinstance(request, ProviderRequest):
            raise ValidationError("expected ProviderRequest")
        context = {"role": request.role, "task": request.task.to_dict(),
                   "code": request.code.to_dict() if request.code is not None else None,
                   "review": request.review.to_dict() if request.review is not None else None}
        body = {"model": self.model, "messages": [
            {"role": "system", "content": request.system_prompt or "Return one valid JSON object."},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, allow_nan=False)},
        ], "response_format": {"type": "json_object"}, "stream": False}
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        try:
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, UnicodeError):
            raise ProviderError("Cannot encode model request as UTF-8 JSON", retryable=False) from None

        for attempt in range(1, self.max_retries + 2):
            started = time.perf_counter()
            emit_attempt(ProviderAttempt(attempt=attempt, status="running", elapsed_ms=0, detail="HTTP request started"))
            try:
                content = self._perform(payload)
            except ProviderError as exc:
                emit_attempt(ProviderAttempt(attempt=attempt, status="failed",
                                             elapsed_ms=(time.perf_counter() - started) * 1000, detail=str(exc)))
                if not exc.retryable or attempt > self.max_retries:
                    raise
                time.sleep(min(30, self.retry_delay * 2 ** (attempt - 1)))
            else:
                emit_attempt(ProviderAttempt(attempt=attempt, status="completed",
                                             elapsed_ms=(time.perf_counter() - started) * 1000, detail="HTTP response accepted"))
                return content

    def _perform(self, payload: bytes) -> str:
        request = Request(self.base_url + "/chat/completions", data=payload, method="POST",
                          headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json",
                                   "Accept": "application/json", "User-Agent": "SE02-Workflow/0.2"})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise ProviderError(f"Model service returned HTTP {status}", retryable=status in RETRYABLE_STATUS) from None
        except (ssl.SSLError, ssl.CertificateError):
            raise ProviderError("TLS validation or handshake failed", retryable=False) from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("Model request timed out", retryable=True) from None
        except URLError as exc:
            if isinstance(exc.reason, (ssl.SSLError, ssl.CertificateError)):
                raise ProviderError("TLS validation or handshake failed", retryable=False) from None
            raise ProviderError("Model connection failed", retryable=True) from None
        except (OSError, HTTPException):
            raise ProviderError("Model connection interrupted", retryable=True) from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("Model response exceeded 2 MiB limit", retryable=False)
        try:
            data = json.loads(raw.decode("utf-8"))
            choice = data["choices"][0]
            message = choice["message"]
            content = message["content"]
            if (choice.get("finish_reason") != "stop" or message.get("tool_calls")
                    or message.get("refusal") or not isinstance(content, str) or not content.strip()):
                raise ValueError("incomplete or unsupported response")
        except (ValueError, UnicodeError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
            raise ProviderError("Invalid, incomplete or unsupported Chat Completions response", retryable=False) from None
        # Never let a server accidentally echo the credential into persisted model output.
        if self._api_key in content:
            raise ProviderError("Model response contained protected credential data", retryable=False)
        try:
            decoded = json.loads(content)
        except ValueError:
            decoded = None  # The consuming Agent will reject malformed model JSON.
        except RecursionError:
            raise ProviderError("Model response JSON is too deeply nested", retryable=False) from None
        try:
            sensitive = _contains_credential(decoded, self._api_key)
        except RecursionError:
            raise ProviderError("Model response JSON is too deeply nested", retryable=False) from None
        if sensitive:
            raise ProviderError("Model response contained protected credential data", retryable=False)
        return content
