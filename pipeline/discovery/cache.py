"""HTTP fetching with a content-addressed cache and a deterministic replay mode.

Phase 0 must be re-runnable (CLAUDE.md 4.2: "probe.py is re-runnable and idempotent")
without depending on the live network, because the phase gate has to produce the same
answer on a machine with no internet and without hammering free-tier quotas (D4).

Two fetchers implement the same protocol:

* :class:`LiveFetcher` performs the request and writes the response body plus its
  metadata into the cache.
* :class:`ReplayFetcher` serves the same request from the cache and raises
  :class:`CacheMiss` if it was never recorded. It never opens a socket.

The cache key is derived from the request (method, url, sorted params) and never from
wall-clock time, so replaying is stable.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from pipeline.config.settings import PROBE

# Query-parameter names whose values are secrets and must never be written to disk.
REDACTED_PARAMS: frozenset[str] = frozenset({"api_key", "key", "token"})
REDACTION = "<redacted>"


class CacheMissError(LookupError):
    """Raised by ReplayFetcher when a request was never recorded."""


@dataclass(frozen=True)
class Response:
    """A fetched (or replayed) HTTP response."""

    url: str
    params: dict[str, str]
    request_headers: dict[str, str]
    status_code: int
    content: bytes
    headers: dict[str, str]
    retrieved_at: str
    elapsed_ms: float
    from_cache: bool
    truncated: bool = False

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def redact(params: Mapping[str, str]) -> dict[str, str]:
    """Replace secret parameter values so nothing sensitive reaches the cache or a report."""
    return {k: (REDACTION if k in REDACTED_PARAMS else v) for k, v in params.items()}


def cache_key(
    url: str, params: Mapping[str, str], headers: Mapping[str, str] | None = None
) -> str:
    """Stable 16-hex key over the request identity, with secrets redacted first.

    Redacting before hashing means the key does not change when a user swaps
    DEMO_KEY for a personal key, so a cache recorded with one still replays.
    Request headers are part of the key because ``Range`` changes the payload.
    """
    payload = json.dumps(
        {
            "url": url,
            "params": dict(sorted(redact(params).items())),
            "headers": dict(sorted((headers or {}).items())),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Fetcher(Protocol):
    """Everything a probe needs in order to obtain bytes."""

    def get(
        self,
        source_id: str,
        url: str,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> Response: ...  # pragma: no cover - Protocol declaration, never executed


def _paths(root: Path, source_id: str, key: str) -> tuple[Path, Path]:
    directory = root / source_id
    return directory / f"{key}.body", directory / f"{key}.meta.json"


class LiveFetcher:
    """Performs real requests, retries transient failures, and records to the cache.

    The response body is always streamed and cut off locally at ``max_bytes``. Several
    of the hosts this pipeline probes advertise ``accept-ranges: bytes`` and then ignore
    a ``Range`` request header, answering HTTP 200 with the whole file - the Atlas EV
    Hub New York export is 1.3 GB - so a Range header cannot be trusted to bound a
    transfer. Local truncation is robust whatever the server does.
    """

    def __init__(
        self,
        cache_root: Path,
        timeout_s: float = PROBE.http_timeout_s,
        max_retries: int = PROBE.max_retries,
        backoff_s: float = PROBE.retry_backoff_s,
        client_factory: Callable[[], httpx.Client] | None = None,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        self.cache_root = cache_root
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._client_factory = client_factory or self._default_client
        self._sleep = sleep

    def _default_client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_s, follow_redirects=True)

    def _fetch_once(
        self,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        max_bytes: int | None,
    ) -> tuple[int, dict[str, str], bytes, bool]:
        """Return (status, response headers, body, truncated)."""
        with (
            self._client_factory() as client,
            client.stream("GET", url, params=dict(params), headers=dict(headers)) as raw,
        ):
            chunks: list[bytes] = []
            size = 0
            truncated = False
            for chunk in raw.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if max_bytes is not None and size >= max_bytes:
                    truncated = True
                    break
            body = b"".join(chunks)
            if max_bytes is not None and len(body) > max_bytes:
                body = body[:max_bytes]
            return (
                raw.status_code,
                {k.lower(): v for k, v in raw.headers.items()},
                body,
                truncated,
            )

    def get(
        self,
        source_id: str,
        url: str,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> Response:
        params = dict(params or {})
        headers = dict(headers or {})
        started = time.monotonic()
        last_error: Exception | None = None
        raw: tuple[int, dict[str, str], bytes, bool] | None = None
        for attempt in range(self.max_retries):
            try:
                raw = self._fetch_once(url, params, headers, max_bytes)
                break
            except httpx.HTTPError as exc:  # network failure, DNS failure, timeout
                last_error = exc
                if attempt < self.max_retries - 1:
                    self._sleep(self.backoff_s * (attempt + 1))
        if raw is None:
            raise ConnectionError(
                f"{source_id}: {url} failed after {self.max_retries} attempts: {last_error}"
            )
        status_code, response_headers, body, truncated = raw
        elapsed_ms = (time.monotonic() - started) * 1000.0
        response = Response(
            url=url,
            params=redact(params),
            request_headers=dict(headers),
            status_code=status_code,
            content=body,
            headers=response_headers,
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
            elapsed_ms=elapsed_ms,
            from_cache=False,
            truncated=truncated,
        )
        self._record(source_id, response)
        return response

    def _record(self, source_id: str, response: Response) -> None:
        body_path, meta_path = _paths(
            self.cache_root,
            source_id,
            cache_key(response.url, response.params, response.request_headers),
        )
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(response.content)
        meta_path.write_text(
            json.dumps(
                {
                    "source_id": source_id,
                    "url": response.url,
                    "params": response.params,
                    "request_headers": response.request_headers,
                    "status_code": response.status_code,
                    "headers": response.headers,
                    "retrieved_at": response.retrieved_at,
                    "elapsed_ms": round(response.elapsed_ms, 1),
                    "content_sha256": response.content_sha256,
                    "content_bytes": len(response.content),
                    "truncated": response.truncated,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


class ReplayFetcher:
    """Serves recorded responses. Opens no sockets; the deterministic gate uses this."""

    def __init__(self, cache_root: Path) -> None:
        self.cache_root = cache_root

    def get(
        self,
        source_id: str,
        url: str,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> Response:
        params = dict(params or {})
        headers = dict(headers or {})
        body_path, meta_path = _paths(
            self.cache_root, source_id, cache_key(url, params, headers)
        )
        if not body_path.exists() or not meta_path.exists():
            raise CacheMissError(
                f"{source_id}: no recorded response for {url} in {self.cache_root}"
            )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return Response(
            url=meta["url"],
            params=meta["params"],
            request_headers=meta.get("request_headers", {}),
            status_code=meta["status_code"],
            content=body_path.read_bytes(),
            headers=meta["headers"],
            retrieved_at=meta["retrieved_at"],
            elapsed_ms=meta["elapsed_ms"],
            from_cache=True,
            truncated=meta.get("truncated", False),
        )
