"""Phase 0 source probe.

Fetches a bounded sample of every source declared in the registry, dumps the live
schema verbatim, counts rows, computes per-field missingness, records the vintage and
the observed rate-limit headers, assigns a status, compares the result against the
stable contract in ``SOURCES.yml``, and writes ``SOURCES.observed.json``.

Idempotency (CLAUDE.md 4.2): running twice against the same recorded responses
produces a byte-identical ``SOURCES.observed.json``, because every timestamp,
elapsed time, and payload in the output comes from the cached response record rather
than from the clock. Run with ``--offline`` to replay; that mode opens no sockets and
is what the phase gate uses.

    python -m pipeline.discovery.probe --offline --cache-root tests/fixtures/replay
    python -m pipeline.discovery.probe --live            # refreshes the cache
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pipeline.config.settings import PATHS, api_keys
from pipeline.discovery import measure
from pipeline.discovery.cache import (
    CacheMissError,
    Fetcher,
    LiveFetcher,
    ReplayFetcher,
    Response,
)
from pipeline.discovery.contract import (
    Drift,
    Observation,
    evaluate_drift,
    load_contract,
    load_observations,
    merge_observations,
    observations_document,
    validate_contract,
    write_observations,
)
from pipeline.discovery.registry import ProbeSpec, all_specs

GENERATOR = "pipeline/discovery/probe.py"

# Response headers that carry rate-limit information, lower-cased. Recorded verbatim
# so the contract's declared rate limit can be checked against observed behaviour.
RATE_LIMIT_HEADERS: tuple[str, ...] = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "ratelimit-limit",
    "ratelimit-remaining",
    "retry-after",
)

# Substrings that identify a key-gated response body regardless of HTTP status.
GATED_MARKERS: tuple[bytes, ...] = (b"API_KEY_MISSING", b"<title>Missing Key</title>")


class ProbeError(RuntimeError):
    """A probe could not be executed at all (as opposed to a source being unavailable)."""


def rate_limit_headers(response: Response) -> dict[str, str]:
    """Extract whichever rate-limit headers the source actually returned."""
    return {name: response.headers[name] for name in RATE_LIMIT_HEADERS
            if name in response.headers}


def looks_gated(response: Response) -> bool:
    """True when the body says a credential is required, whatever the status code."""
    head = response.content[:4096]
    return any(marker in head for marker in GATED_MARKERS)


def _json_pointer(payload: bytes, pointer: tuple[str, ...]) -> str | None:
    """Read a vintage value out of a JSON body. Returns None if it is not there."""
    if not pointer:
        return None
    try:
        document: Any = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    for step in pointer:
        if not isinstance(document, dict) or step not in document:
            return None
        document = document[step]
    return str(document)


def _measure_remote(spec: ProbeSpec, response: Response) -> measure.Measurement | None:
    """Apply the measurement appropriate to the spec's kind. None when not measurable."""
    if spec.kind == "rest_json":
        try:
            return measure.measure_json_records(
                response.content, spec.record_path, max_rows=spec.max_rows
            )
        except (json.JSONDecodeError, KeyError, AttributeError, TypeError):
            return None
    if spec.kind == "remote_csv":
        payload = response.content
        if response.truncated:
            # A byte-capped stream almost always cuts mid-record. Discarding the
            # trailing partial line keeps the last row from being counted as a
            # record full of missing fields, which would bias missingness upward.
            payload = payload[: payload.rfind(b"\n") + 1]
        return measure.measure_delimited(
            payload, delimiter=spec.delimiter, max_rows=spec.max_rows
        )
    if spec.kind == "remote_html_table":
        return measure.measure_html_table(response.content)
    if spec.kind == "nested_json_units":
        # The AFDC primary representation nests charging units inside stations, so it
        # is reshaped to one row per unit before measurement. Reshaping a fixed layout
        # into rows is mechanical and lossless (amendment A15).
        from pipeline.sources.base import NestedUnitsSource

        try:
            staged = NestedUnitsSource(spec.source_id, spec.url).load(
                _StaticFetcher(response))
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return None
        return measure.measure_records(
            list(staged.rows), staged.columns,  # type: ignore[arg-type]
        )
    return None


class _StaticFetcher:
    """Serves one already-fetched response, so an adapter can measure it in place."""

    def __init__(self, response: Response) -> None:
        self._response = response

    def get(self, source_id: str, url: str,
            params: Mapping[str, str] | None = None,
            headers: Mapping[str, str] | None = None,
            max_bytes: int | None = None) -> Response:
        return self._response


def _classify(spec: ProbeSpec, response: Response,
              measurement: measure.Measurement | None) -> tuple[str, str]:
    """Assign one of confirmed / degraded / gated / unavailable, with a reason."""
    if looks_gated(response) or response.status_code == 401:
        required = (f"{spec.needs_api_key.upper()}_API_KEY" if spec.needs_api_key
                    else f"{spec.needs_bearer.upper()}_USER_TOKEN" if spec.needs_bearer
                    else "a credential")
        return "gated", (
            f"credential required; set {required}. "
            "No credential is fabricated or persisted by this pipeline."
        )
    if response.status_code == 429:
        limit = response.headers.get("x-ratelimit-limit", "?")
        retry = response.headers.get("retry-after", "?")
        return "gated", (
            f"HTTP 429: rate limit exhausted (x-ratelimit-limit={limit}, "
            f"retry-after={retry}s). The shared DEMO_KEY credential is heavily "
            "throttled; supply a free key in the environment for full probing. "
            "No credential is fabricated or persisted by this pipeline."
        )
    if not response.ok:
        return "unavailable", f"HTTP {response.status_code}"
    if spec.kind == "availability":
        return "confirmed", f"reachable, HTTP {response.status_code}, " \
                            f"{len(response.content)} bytes sampled"
    if measurement is None:
        return "degraded", "reachable but the payload could not be measured"
    if measurement.row_count == 0:
        return "degraded", "reachable but the sample contained no records"
    return "confirmed", f"{measurement.row_count} records measured in the bounded sample"


def probe_local(spec: ProbeSpec) -> Observation:
    """Measure a seed file already on disk. Never touches the network."""
    path = spec.local_path
    if path is None:  # pragma: no cover - registry guarantees a path for local kinds
        raise ProbeError(f"{spec.source_id}: local spec has no local_path")
    if not path.exists():
        return Observation(
            source_id=spec.source_id, status="unavailable", url=str(path),
            http_status=None, retrieved_at="", elapsed_ms=None, content_bytes=None,
            content_sha256=None, measurement=None, rate_limit_headers={},
            vintage=None,
            note="file absent from data/seed/ (it may be excluded from version control; "
                 "see data/seed/SEED_INVENTORY.md for its recorded SHA-256)",
        )
    if spec.kind == "local_geojson":
        result = measure.measure_geojson_properties(path, spec.max_rows or 100)
    else:
        result = measure.measure_delimited_file(path, delimiter=spec.delimiter)
    return Observation(
        source_id=spec.source_id, status="confirmed", url=str(path),
        http_status=None, retrieved_at="", elapsed_ms=None,
        content_bytes=path.stat().st_size, content_sha256=None,
        measurement=result.to_dict(), rate_limit_headers={}, vintage=None,
        note=spec.note,
    )


def request_params(spec: ProbeSpec) -> dict[str, str]:
    """The exact query parameters a spec is fetched with, credential included.

    Exposed so that anything replaying the cache (the forward-viability smoke test,
    for instance) reconstructs the same cache key the probe wrote under. The
    credential's *value* does not affect the key - it is redacted before hashing -
    but its presence does.
    """
    params = dict(spec.params)
    if spec.needs_api_key:
        key = getattr(api_keys(), spec.needs_api_key)
        if key:
            params["api_key"] = key
    return params


def request_headers(spec: ProbeSpec) -> dict[str, str]:
    """Request headers for a spec, including a Bearer token where one is required.

    The token is attached here and redacted by the cache before anything is written to
    disk, so ``Authorization: Bearer <jwt>`` never persists.
    """
    headers = dict(spec.headers)
    if spec.needs_bearer:
        token = getattr(api_keys(), spec.needs_bearer)
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def probe_remote(spec: ProbeSpec, fetcher: Fetcher) -> Observation:
    """Fetch (or replay) one remote source and measure the response."""
    params = request_params(spec)
    try:
        response = fetcher.get(
            spec.source_id, spec.url, params, request_headers(spec), spec.max_bytes
        )
    except (ConnectionError, CacheMissError) as exc:
        return Observation(
            source_id=spec.source_id, status="unavailable", url=spec.url,
            http_status=None, retrieved_at="", elapsed_ms=None, content_bytes=None,
            content_sha256=None, measurement=None, rate_limit_headers={}, vintage=None,
            note=f"{type(exc).__name__}: {exc}",
        )
    # A failed or credential-gated response must not be measured. Measuring an error
    # body yields row_count = 0, which a downstream reader could mistake for "this
    # source is empty" rather than "this request failed" (directive D8).
    result = _measure_remote(spec, response) if (
        response.ok and not looks_gated(response)) else None
    status, reason = _classify(spec, response, result)
    return Observation(
        source_id=spec.source_id,
        status=status,
        url=spec.url,
        http_status=response.status_code,
        retrieved_at=response.retrieved_at,
        elapsed_ms=round(response.elapsed_ms, 1),
        content_bytes=len(response.content),
        content_sha256=response.content_sha256,
        measurement=result.to_dict() if result else None,
        rate_limit_headers=rate_limit_headers(response),
        vintage=_json_pointer(response.content, spec.vintage_pointer)
        or response.headers.get("last-modified"),
        note=f"{reason}{' [bounded sample: transfer capped]' if response.truncated else ''}. "
             f"{spec.note}".strip(),
    )


def probe_one(spec: ProbeSpec, fetcher: Fetcher) -> Observation:
    """Dispatch a single spec to the local or remote path."""
    if spec.kind.startswith("local_"):
        return probe_local(spec)
    return probe_remote(spec, fetcher)


def run(
    specs: tuple[ProbeSpec, ...],
    fetcher: Fetcher,
    contract: dict[str, Any] | None = None,
) -> tuple[list[Observation], list[Drift]]:
    """Probe every spec and, where a contract entry exists, evaluate drift against it."""
    entries = {e["id"]: e for e in (contract or {}).get("sources", [])}
    observations: list[Observation] = []
    drifts: list[Drift] = []
    for spec in specs:
        observation = probe_one(spec, fetcher)
        observations.append(observation)
        entry = entries.get(spec.source_id)
        if entry is not None:
            drifts.append(evaluate_drift(entry, observation))
    return observations, drifts


def build_fetcher(offline: bool, cache_root: Path) -> Fetcher:
    """Replay in offline mode; otherwise fetch live and record into the cache."""
    return ReplayFetcher(cache_root) if offline else LiveFetcher(cache_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VoltGap Phase 0 source probe")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true",
                      help="replay recorded responses; opens no sockets")
    mode.add_argument("--live", action="store_true",
                      help="fetch live and refresh the cache (default)")
    parser.add_argument("--cache-root", type=Path, default=PATHS.cache)
    parser.add_argument("--out", type=Path, default=PATHS.observations)
    parser.add_argument("--contract", type=Path, default=PATHS.contract)
    parser.add_argument("--only", default="",
                        help="comma-separated source ids to probe")
    parser.add_argument("--no-write", action="store_true",
                        help="probe and report without writing the observations file")
    args = parser.parse_args(argv)

    specs = all_specs()
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        specs = tuple(s for s in specs if s.source_id in wanted)

    contract: dict[str, Any] | None = None
    if args.contract.exists():
        contract = load_contract(args.contract)
        validate_contract(contract)

    fetcher = build_fetcher(args.offline, args.cache_root)
    observations, drifts = run(specs, fetcher, contract)
    document = observations_document(observations, drifts, GENERATOR)
    if args.only and args.out.exists():
        # A partial probe MERGES. Writing only the probed subset would silently delete
        # every other source's observation, which reads as a clean file and is not: the
        # sidecar is the evidence that each source was actually measured.
        document = merge_observations(load_observations(args.out), document)
    if not args.no_write:
        write_observations(args.out, document)

    tally: dict[str, int] = {}
    for observation in observations:
        tally[observation.status] = tally.get(observation.status, 0) + 1
    print(f"probed {len(observations)} sources "
          f"({'replay' if args.offline else 'live'}); "
          + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    for observation in observations:
        if observation.status != "confirmed":
            print(f"  {observation.status:12s} {observation.source_id}: {observation.note}")
    outside = [d for d in drifts if d.within_expected_row_count is False]
    for drift in outside:
        print(f"  DRIFT        {drift.source_id}: observed {drift.observed_row_count} "
              f"outside {drift.tolerance_band}")
    return 1 if outside else 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
