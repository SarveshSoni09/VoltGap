"""Adapter behaviour under every failure mode a production API can present.

These are mocked, not live: deliberately provoking 429 or 500 on a production service
would be antisocial and, for rate limits, destructive to a shared credential. Phase 0
already established the real 429 path by exhausting DEMO_KEY. What matters here is that
the *adapter* behaves correctly when the response arrives.

Required behaviour in every case: bounded retries, no infinite loop, no silent empty
dataset, explicit degradation (directive D8), and diagnostics that never leak a secret.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from pipeline.discovery.cache import LiveFetcher, ReplayFetcher
from pipeline.discovery.probe import probe_remote
from pipeline.discovery.registry import ProbeSpec
from pipeline.sources.base import DelimitedSource, JsonRecordsSource
from tests.conftest import make_client_factory

SECRET = "super-secret-token-value"


def responder(
    status: int, body: bytes = b"", content_type: str = "application/json"
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body,
                              headers={"content-type": content_type})
    return handler


# --- HTTP status codes ----------------------------------------------------------------

@pytest.mark.parametrize("status", [403, 404, 500, 503])
def test_error_statuses_degrade_explicitly_rather_than_returning_empty_data(
    tmp_path: Path, status: int
) -> None:
    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(responder(status)))
    observation = probe_remote(ProbeSpec("s", "remote_csv", url="https://x"), fetcher)
    assert observation.status in {"unavailable", "gated"}
    assert observation.measurement is None, "never a silent empty dataset"
    assert str(status) in observation.note


def test_a_401_is_classified_as_gated_because_it_means_a_credential_is_needed(
    tmp_path: Path,
) -> None:
    """HUD returns 401 for both a missing and an invalid token."""
    fetcher = LiveFetcher(tmp_path,
                          client_factory=make_client_factory(responder(401, b"{}")))
    observation = probe_remote(
        ProbeSpec("s", "rest_json", url="https://x", needs_bearer="hud"), fetcher)
    assert observation.status == "gated"
    assert "HUD_USER_TOKEN" in observation.note
    assert observation.measurement is None


def test_a_429_is_classified_as_gated_with_its_limit_recorded(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b"{}", headers={
            "x-ratelimit-limit": "60", "retry-after": "30"})

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    observation = probe_remote(ProbeSpec("s", "rest_json", url="https://x"), fetcher)
    assert observation.status == "gated"
    assert "x-ratelimit-limit=60" in observation.note
    assert "retry-after=30s" in observation.note


def test_a_credential_error_page_returned_with_status_200_is_still_caught(
    tmp_path: Path,
) -> None:
    """The Census trap: HTTP 200 with an HTML 'Missing Key' body."""
    handler = responder(200, b"<html><title>Missing Key</title></html>", "text/html")
    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    observation = probe_remote(
        ProbeSpec("s", "rest_json", url="https://x", needs_api_key="census"), fetcher)
    assert observation.status == "gated", (
        "an adapter checking only status_code would have called this a success"
    )


# --- transport failures ------------------------------------------------------------------

def test_a_timeout_is_retried_a_bounded_number_of_times_then_reported(
    tmp_path: Path,
) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ReadTimeout("timed out")

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler),
                          sleep=lambda _: None)
    observation = probe_remote(ProbeSpec("s", "remote_csv", url="https://x"), fetcher)
    assert len(attempts) == 3, "bounded retries, never an infinite loop"
    assert observation.status == "unavailable"
    assert observation.measurement is None


def test_a_dns_failure_is_reported_not_swallowed(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known")

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler),
                          sleep=lambda _: None)
    observation = probe_remote(ProbeSpec("s", "rest_json", url="https://x"), fetcher)
    assert observation.status == "unavailable"
    assert "ConnectionError" in observation.note


def test_retry_backoff_widens_and_is_finite(tmp_path: Path) -> None:
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler),
                          sleep=slept.append, backoff_s=0.5)
    with pytest.raises(ConnectionError):
        fetcher.get("s", "https://x")
    assert slept == [0.5, 1.0], "exponential-ish widening, and it terminates"


# --- payload failures ----------------------------------------------------------------------

def test_malformed_json_is_reported_as_degraded_not_parsed_into_nothing(
    tmp_path: Path,
) -> None:
    handler = responder(200, b"{not valid json")
    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    observation = probe_remote(ProbeSpec("s", "rest_json", url="https://x"), fetcher)
    assert observation.status == "degraded"
    assert "could not be measured" in observation.note


def test_an_unexpected_content_type_does_not_masquerade_as_data(tmp_path: Path) -> None:
    handler = responder(200, b"<html><body>maintenance</body></html>", "text/html")
    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    observation = probe_remote(ProbeSpec("s", "rest_json", url="https://x"), fetcher)
    assert observation.status == "degraded"


def test_an_empty_successful_response_is_degraded_not_confirmed(tmp_path: Path) -> None:
    handler = responder(200, b"col_a,col_b\n", "text/csv")
    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    observation = probe_remote(ProbeSpec("s", "remote_csv", url="https://x"), fetcher)
    assert observation.status == "degraded"
    assert "no records" in observation.note


def test_a_missing_required_field_surfaces_as_full_missingness(tmp_path: Path) -> None:
    handler = responder(200, b'{"r":[{"a":1},{"a":2}]}')
    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    observation = probe_remote(
        ProbeSpec("s", "rest_json", url="https://x", record_path=("r",)), fetcher)
    assert observation.measurement is not None
    assert "b" not in observation.measurement["fields"], (
        "an absent field is absent, not silently defaulted"
    )


def test_a_partial_download_is_flagged_rather_than_treated_as_complete(
    tmp_path: Path,
) -> None:
    handler = responder(200, b"a,b\n" + b"1,2\n" * 5000, "text/csv")
    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    observation = probe_remote(
        ProbeSpec("s", "remote_csv", url="https://x", max_bytes=200), fetcher)
    assert "bounded sample: transfer capped" in observation.note


# --- secret hygiene under failure ------------------------------------------------------------

def test_a_secret_never_reaches_the_cache_on_any_status(tmp_path: Path) -> None:
    for status in (200, 401, 403, 429, 500):
        fetcher = LiveFetcher(
            tmp_path, client_factory=make_client_factory(responder(status, b"{}")))
        with contextlib.suppress(ConnectionError):
            fetcher.get("s", "https://x", {"api_key": SECRET},
                        {"Authorization": f"Bearer {SECRET}"})
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="replace"), path


def test_a_secret_never_reaches_an_exception_message(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler),
                          sleep=lambda _: None)
    with pytest.raises(ConnectionError) as excinfo:
        fetcher.get("s", "https://x", {"api_key": SECRET})
    assert SECRET not in str(excinfo.value)


def test_a_secret_never_reaches_an_observation_note(tmp_path: Path) -> None:
    fetcher = LiveFetcher(tmp_path,
                          client_factory=make_client_factory(responder(403, b"{}")))
    observation = probe_remote(
        ProbeSpec("s", "rest_json", url="https://x", needs_api_key="nrel"), fetcher)
    serialised = str(observation.to_dict())
    assert SECRET not in serialised


def test_the_cache_key_is_stable_when_only_the_credential_changes(
    tmp_path: Path,
) -> None:
    """A fixture recorded under one key must replay under another."""
    fetcher = LiveFetcher(tmp_path,
                          client_factory=make_client_factory(responder(200, b"a\n1\n")))
    fetcher.get("s", "https://x", {"api_key": "key-one"})
    replayed = ReplayFetcher(tmp_path).get("s", "https://x", {"api_key": "key-two"})
    assert replayed.content == b"a\n1\n"


def test_local_and_remote_adapters_both_refuse_to_invent_data(tmp_path: Path) -> None:
    from pipeline.discovery.cache import CacheMissError

    with pytest.raises(CacheMissError):
        DelimitedSource("s", endpoint="https://x").load(ReplayFetcher(tmp_path))
    with pytest.raises(CacheMissError):
        JsonRecordsSource("s", "https://x").load(ReplayFetcher(tmp_path))
