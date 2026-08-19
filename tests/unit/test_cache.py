"""Unit tests for the fetching and caching layer."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from pipeline.discovery.cache import (
    REDACTION,
    CacheMissError,
    LiveFetcher,
    ReplayFetcher,
    Response,
    cache_key,
    redact,
)
from tests.conftest import make_client_factory


def test_redact_replaces_secret_parameters_only() -> None:
    assert redact({"api_key": "SECRET", "state": "MN"}) == {
        "api_key": REDACTION,
        "state": "MN",
    }


def test_cache_key_is_independent_of_the_credential_value() -> None:
    """A cache recorded with DEMO_KEY must still replay under a personal key."""
    assert cache_key("https://x/y", {"api_key": "DEMO_KEY"}) == cache_key(
        "https://x/y", {"api_key": "personal-key"}
    )


def test_cache_key_depends_on_url_params_and_headers() -> None:
    base = cache_key("https://x/y", {})
    assert base != cache_key("https://x/z", {})
    assert base != cache_key("https://x/y", {"state": "MN"})
    assert base != cache_key("https://x/y", {}, {"Range": "bytes=0-10"})


def test_response_ok_and_sha256() -> None:
    ok = Response("u", {}, {}, 204, b"abc", {}, "t", 1.0, False)
    bad = Response("u", {}, {}, 500, b"", {}, "t", 1.0, False)
    assert ok.ok is True
    assert bad.ok is False
    assert ok.content_sha256 == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_live_fetcher_records_body_and_metadata(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-probe"] == "1"
        return httpx.Response(200, content=b"col\n1\n", headers={"X-RateLimit-Limit": "10"})

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    response = fetcher.get("src", "https://example.test/data", {"api_key": "SECRET"},
                           {"x-probe": "1"})

    assert response.status_code == 200
    assert response.content == b"col\n1\n"
    assert response.truncated is False
    assert response.params == {"api_key": REDACTION}
    assert response.headers["x-ratelimit-limit"] == "10"

    meta_files = list((tmp_path / "src").glob("*.meta.json"))
    assert len(meta_files) == 1
    meta = json.loads(meta_files[0].read_text())
    assert meta["params"] == {"api_key": REDACTION}, "the credential must never reach disk"
    assert meta["content_bytes"] == 6
    assert meta["truncated"] is False


def test_live_fetcher_truncates_at_max_bytes(tmp_path: Path) -> None:
    """A host that ignores Range must not be able to make the probe unbounded."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    response = fetcher.get("src", "https://example.test/big", max_bytes=1024)

    assert len(response.content) == 1024
    assert response.truncated is True


def test_live_fetcher_retries_then_succeeds(tmp_path: Path) -> None:
    attempts: list[int] = []
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=b"ok")

    fetcher = LiveFetcher(
        tmp_path,
        client_factory=make_client_factory(handler),
        sleep=slept.append,
        backoff_s=0.5,
    )
    assert fetcher.get("src", "https://example.test/x").content == b"ok"
    assert len(attempts) == 3
    assert slept == [0.5, 1.0], "backoff must widen on each retry"


def test_live_fetcher_raises_connection_error_after_exhausting_retries(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    fetcher = LiveFetcher(
        tmp_path, client_factory=make_client_factory(handler), sleep=lambda _: None
    )
    with pytest.raises(ConnectionError, match="failed after 3 attempts"):
        fetcher.get("src", "https://example.test/x")


def test_default_client_factory_is_constructed_with_settings(tmp_path: Path) -> None:
    fetcher = LiveFetcher(tmp_path, timeout_s=7.5)
    client = fetcher._default_client()
    assert client.timeout.read == 7.5
    assert client.follow_redirects is True
    client.close()


def test_replay_round_trips_a_recorded_response(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(206, content=b"a,b\n1,2\n", headers={"Last-Modified": "Mon"})

    LiveFetcher(tmp_path, client_factory=make_client_factory(handler)).get(
        "src", "https://example.test/x", {"state": "MN"}, {"Range": "bytes=0-7"}
    )
    replayed = ReplayFetcher(tmp_path).get(
        "src", "https://example.test/x", {"state": "MN"}, {"Range": "bytes=0-7"}
    )
    assert replayed.from_cache is True
    assert replayed.status_code == 206
    assert replayed.content == b"a,b\n1,2\n"
    assert replayed.headers["last-modified"] == "Mon"


def test_replay_raises_cache_miss_when_nothing_was_recorded(tmp_path: Path) -> None:
    with pytest.raises(CacheMissError, match="no recorded response"):
        ReplayFetcher(tmp_path).get("src", "https://example.test/never")
