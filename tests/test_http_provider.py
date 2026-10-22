import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from http_fixture import completion, http_service
from se02.domain import ProviderError, Task, ValidationError
from se02.providers import HttpProvider, ProviderRequest
from se02.providers.telemetry import attempt_scope


REQUEST = ProviderRequest(role="coder", task=Task(task_id="sum", description="求和"), system_prompt="Return JSON code.")


class HttpProviderTests(unittest.TestCase):
    def test_request_transmits_role_context_and_response_format_without_secret_in_body(self):
        with http_service([{"body": completion('{"hello":"world"}')}]) as (base, requests):
            provider = HttpProvider(base_url=base, model="fixture", api_key="unit-test-key")
            self.assertEqual(provider.complete(REQUEST), '{"hello":"world"}')
        body = requests[0]["body"]
        self.assertEqual(requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(requests[0]["authorization"], "Bearer unit-test-key")
        self.assertEqual(body["model"], "fixture")
        self.assertEqual(body["messages"][0]["content"], "Return JSON code.")
        context = json.loads(body["messages"][1]["content"])
        self.assertEqual(context["task"]["description"], "求和")
        self.assertEqual(context["role"], "coder")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("unit-test-key", json.dumps(body))
        self.assertNotIn("unit-test-key", repr(provider))

    def test_retryable_status_retries_once_and_records_separate_attempts(self):
        for status in (408, 429, 500, 502, 503, 504):
            events = []
            with self.subTest(status=status), http_service([
                {"status": status}, {"body": completion("{}")},
            ]) as (base, requests):
                with attempt_scope(events.append):
                    result = HttpProvider(base_url=base, model="fixture", api_key="unit-test-key", retry_delay=0).complete(REQUEST)
                self.assertEqual(result, "{}")
                self.assertEqual(len(requests), 2)
                self.assertEqual([(e.attempt, e.status) for e in events], [(1, "running"), (1, "failed"), (2, "running"), (2, "completed")])

    def test_persistent_retryable_error_stops_after_allowed_attempts(self):
        with http_service([{"status": 503}, {"status": 503}]) as (base, requests):
            with self.assertRaises(ProviderError) as caught:
                HttpProvider(base_url=base, model="fixture", api_key="unit-test-key", retry_delay=0).complete(REQUEST)
            self.assertTrue(caught.exception.retryable)
            self.assertEqual(len(requests), 2)

    def test_auth_and_client_errors_do_not_retry_or_expose_server_body(self):
        for status in (400, 401, 402, 403, 404, 422):
            with self.subTest(status=status), http_service([
                {"status": status, "body": {"error": "unit-test-key server private detail"}},
            ]) as (base, requests):
                with self.assertRaises(ProviderError) as caught:
                    HttpProvider(base_url=base, model="fixture", api_key="unit-test-key").complete(REQUEST)
                self.assertFalse(caught.exception.retryable)
                self.assertNotIn("unit-test-key", str(caught.exception))
                self.assertNotIn("server private detail", str(caught.exception))
                self.assertEqual(len(requests), 1)

    def test_redirect_is_not_followed_with_bearer_token(self):
        with http_service([{"status": 302, "headers": {"Location": "http://127.0.0.1:1/steal"}}]) as (base, requests):
            with self.assertRaises(ProviderError) as caught:
                HttpProvider(base_url=base, model="fixture", api_key="unit-test-key").complete(REQUEST)
            self.assertFalse(caught.exception.retryable)
            self.assertEqual(len(requests), 1)

    def test_socket_timeout_retries_then_reports_failure(self):
        with http_service([{"delay": .2}, {"delay": .2}]) as (base, requests):
            with self.assertRaises(ProviderError) as caught:
                HttpProvider(base_url=base, model="fixture", api_key="unit-test-key", timeout=.03, retry_delay=0).complete(REQUEST)
            self.assertTrue(caught.exception.retryable)
            self.assertEqual(len(requests), 2)

    def test_connection_failures_retry_without_leaking_exception_details(self):
        provider = HttpProvider(base_url="https://example.invalid/v1", model="fixture", api_key="unit-test-key", retry_delay=0)
        with patch("se02.providers.http.OpenerDirector.open", side_effect=URLError("unit-test-key")) as open_call:
            with self.assertRaises(ProviderError) as caught:
                provider.complete(REQUEST)
            self.assertEqual(open_call.call_count, 2)
            self.assertNotIn("unit-test-key", str(caught.exception))

    def test_invalid_response_does_not_retry(self):
        bad = [b"not json", b"\xff", {}, {"choices": []}, completion(None), completion(" "),
               {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]},
               {"choices": [{"message": {"content": "{}", "tool_calls": [{"name": "x"}]}, "finish_reason": "tool_calls"}]},
               b'x' * (2 * 1024 * 1024 + 1)]
        for body in bad:
            with self.subTest(body_type=type(body).__name__), http_service([{"body": body}]) as (base, requests):
                with self.assertRaises(ProviderError) as caught:
                    HttpProvider(base_url=base, model="fixture", api_key="unit-test-key").complete(REQUEST)
                self.assertFalse(caught.exception.retryable)
                self.assertEqual(len(requests), 1)

    def test_retry_disabled_and_context_observer_is_reset(self):
        events = []
        with http_service([{"status": 500}, {"body": completion("{}")}]) as (base, requests):
            provider = HttpProvider(base_url=base, model="fixture", api_key="unit-test-key", max_retries=0)
            with attempt_scope(events.append), self.assertRaises(ProviderError):
                provider.complete(REQUEST)
            count = len(events)
            self.assertEqual(provider.complete(REQUEST), "{}")
            self.assertEqual(len(events), count)

    def test_configuration_validates_url_and_numeric_limits(self):
        base = dict(base_url="https://example.invalid/v1", model="fixture", api_key="unit-test-key")
        invalid = [dict(api_key=""), dict(api_key="bad\nkey"), dict(model=" "), dict(timeout=0),
                   dict(timeout=float("nan")), dict(timeout=True), dict(max_retries=4), dict(max_retries=True),
                   dict(retry_delay=-1), dict(base_url="http://remote.example/v1"),
                   dict(base_url="https://user:password@example.com"), dict(base_url="https://example.com?key=secret"),
                   dict(base_url="https://example.com/#fragment"), dict(base_url="file:///tmp/x")]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                HttpProvider(**(base | values))

    def test_escaped_credential_in_model_json_is_rejected_before_persistence(self):
        for content in ('{"source":"unit-test-key"}',
                        '{"source":"unit\\u002dtest-key"}',
                        '{"unit\\u002dtest-key":{"nested":["value"]}}'):
            with self.subTest(content=content), http_service([{"body": completion(content)}]) as (base, requests):
                with self.assertRaises(ProviderError) as caught:
                    HttpProvider(base_url=base, model="fixture", api_key="unit-test-key").complete(REQUEST)
                self.assertNotIn("unit-test-key", str(caught.exception))
                self.assertEqual(len(requests), 1)


if __name__ == "__main__":
    unittest.main()
