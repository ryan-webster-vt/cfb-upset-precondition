"""Async HTTP adapter: retries, retry-after, typed errors, circuit breaker."""

from __future__ import annotations

import httpx
import pytest
import respx

from cfb_upset.adapters.http import (
    CircuitBreaker,
    HttpClient,
    RetryConfig,
    _retry_after_seconds,
)
from cfb_upset.errors import PermanentProviderError, TransientProviderError

URL = "https://example.test/resource"


def retry_config(max_attempts: int = 3) -> RetryConfig:
    return RetryConfig(max_attempts=max_attempts, base_backoff_s=0.0, jitter_s=0.0)


def make_client(*, max_attempts: int = 3, breaker: CircuitBreaker | None = None, slept=None):
    async def fake_sleep(seconds: float) -> None:
        if slept is not None:
            slept.append(seconds)

    return HttpClient(
        provider="test",
        retry=retry_config(max_attempts),
        breaker=breaker,
        sleep=fake_sleep,
        client=httpx.AsyncClient(base_url="https://example.test"),
    )


@respx.mock
async def test_success_returns_response_and_resets_breaker() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    breaker = CircuitBreaker()
    breaker.record_failure()
    client = make_client(breaker=breaker)

    response = await client.request("GET", "/resource")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert route.call_count == 1
    assert breaker.failures == 0
    await client.aclose()


@respx.mock
async def test_429_retries_and_honours_retry_after_header() -> None:
    slept: list[float] = []
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "1.5"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client = make_client(slept=slept)

    response = await client.request("GET", "/resource")

    assert response.status_code == 200
    assert route.call_count == 2
    assert slept == [1.5]
    await client.aclose()


@respx.mock
async def test_429_honours_retry_after_in_body() -> None:
    slept: list[float] = []
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, json={"retry_after_s": 2}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client = make_client(slept=slept)

    await client.request("GET", "/resource")

    assert route.call_count == 2
    assert slept == [2.0]
    await client.aclose()


@respx.mock
async def test_500_uses_exponential_backoff_without_jitter() -> None:
    slept: list[float] = []
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(502),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client = make_client(slept=slept)

    await client.request("GET", "/resource")

    assert route.call_count == 3
    assert slept == [0.0, 0.0]
    await client.aclose()


@respx.mock
async def test_retry_exhaustion_raises_transient_with_status() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(503, headers={"retry-after": "3"}))
    client = make_client(max_attempts=2)

    with pytest.raises(TransientProviderError) as caught:
        await client.request("GET", "/resource")

    assert caught.value.status_code == 503
    assert caught.value.retry_after_s == 3.0
    assert caught.value.provider == "test"
    assert route.call_count == 2
    await client.aclose()


@respx.mock
async def test_400_is_permanent_and_not_retried() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(400, json={"error": "bad"}))
    client = make_client()

    with pytest.raises(PermanentProviderError) as caught:
        await client.request("GET", "/resource")

    assert caught.value.status_code == 400
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_transport_error_retries_then_succeeds() -> None:
    slept: list[float] = []
    route = respx.get(URL).mock(
        side_effect=[
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    client = make_client(slept=slept)

    response = await client.request("GET", "/resource")

    assert response.status_code == 200
    assert route.call_count == 2
    assert slept == [0.0]
    await client.aclose()


@respx.mock
async def test_timeout_exhaustion_raises_transient() -> None:
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    client = make_client(max_attempts=2)

    with pytest.raises(TransientProviderError, match="ReadTimeout"):
        await client.request("GET", "/resource")

    await client.aclose()


@respx.mock
async def test_circuit_breaker_opens_after_failures() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(500))
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=60.0)
    client = make_client(max_attempts=2, breaker=breaker)

    with pytest.raises(TransientProviderError):
        await client.request("GET", "/resource")

    assert breaker.is_open is True

    with pytest.raises(TransientProviderError, match="circuit breaker open"):
        await client.request("GET", "/resource")

    assert route.call_count == 2
    await client.aclose()


async def test_circuit_breaker_open_short_circuits_request() -> None:
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure()
    client = make_client(breaker=breaker)

    with pytest.raises(TransientProviderError, match="circuit breaker open"):
        await client.request("GET", "/resource")

    await client.aclose()


def test_circuit_breaker_closes_after_success() -> None:
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure()
    assert breaker.is_open is True

    breaker.record_success()

    assert breaker.is_open is False
    assert breaker.failures == 0
    assert breaker.allow() is True


def test_circuit_breaker_resets_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    now = {"value": 100.0}

    def fake_monotonic() -> float:
        return now["value"]

    monkeypatch.setattr("cfb_upset.adapters.http.time.monotonic", fake_monotonic)
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=30.0)
    breaker.record_failure()

    assert breaker.is_open is True
    now["value"] += 31.0
    assert breaker.is_open is False
    assert breaker.failures == 0


def test_allow_defaults_to_true_and_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    assert breaker.allow() is True
    breaker.record_failure()
    assert breaker.allow() is True
    breaker.record_failure()
    assert breaker.allow() is False


@respx.mock
async def test_get_json_and_post_json_helpers() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"items": [1]}))
    respx.post(URL).mock(return_value=httpx.Response(200, json={"created": True}))
    client = make_client()

    assert await client.get_json("/resource") == {"items": [1]}
    assert await client.post_json("/resource", {"value": 1}) == {"created": True}

    await client.aclose()


def test_retry_after_seconds_from_header_body_and_nested_error() -> None:
    assert _retry_after_seconds(httpx.Response(429, headers={"retry-after": "2"})) == 2.0
    assert _retry_after_seconds(httpx.Response(429, json={"retry_after": 3})) == 3.0
    assert _retry_after_seconds(httpx.Response(429, json={"error": {"retry_after_s": 4}})) == 4.0
    assert _retry_after_seconds(httpx.Response(429, text="not-json")) is None
    assert _retry_after_seconds(httpx.Response(429, json={"retry_after": None})) is None


def test_retry_after_seconds_rejects_invalid_header_then_reads_body() -> None:
    response = httpx.Response(429, headers={"retry-after": "soon"}, json={"retry_after_s": 5})
    assert _retry_after_seconds(response) == 5.0
