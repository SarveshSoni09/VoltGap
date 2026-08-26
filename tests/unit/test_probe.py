"""Unit tests for the probe orchestrator and its status classification."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from pipeline.discovery.cache import LiveFetcher, ReplayFetcher, Response
from pipeline.discovery.probe import (
    GENERATOR,
    _json_pointer,
    _measure_remote,
    build_fetcher,
    looks_gated,
    main,
    probe_local,
    probe_one,
    probe_remote,
    rate_limit_headers,
    run,
)
from pipeline.discovery.registry import ProbeSpec, all_specs
from tests.conftest import make_client_factory


def response(**overrides: object) -> Response:
    values: dict[str, object] = {
        "url": "https://x", "params": {}, "request_headers": {}, "status_code": 200,
        "content": b"", "headers": {}, "retrieved_at": "t", "elapsed_ms": 1.0,
        "from_cache": False,
    }
    values.update(overrides)
    return Response(**values)  # type: ignore[arg-type]


def test_rate_limit_headers_are_extracted_when_present() -> None:
    got = rate_limit_headers(response(headers={"x-ratelimit-limit": "10",
                                               "retry-after": "78590",
                                               "server": "nginx"}))
    assert got == {"x-ratelimit-limit": "10", "retry-after": "78590"}


def test_looks_gated_detects_both_credential_markers() -> None:
    assert looks_gated(response(content=b'{"error":{"code":"API_KEY_MISSING"}}')) is True
    assert looks_gated(response(content=b"<html><title>Missing Key</title>")) is True
    assert looks_gated(response(content=b"col\n1\n")) is False


def test_json_pointer_walks_a_key_path_and_fails_safely() -> None:
    assert _json_pointer(b'{"a":{"b":"v"}}', ("a", "b")) == "v"
    assert _json_pointer(b'{"a":1}', ()) is None
    assert _json_pointer(b'{"a":1}', ("missing",)) is None
    assert _json_pointer(b"not json", ("a",)) is None
    assert _json_pointer(b'{"a":1}', ("a", "b")) is None


def test_measure_remote_dispatches_by_kind() -> None:
    cases = [
        (ProbeSpec("s", "rest_json", record_path=("r",)), b'{"r":[{"a":1}]}'),
        (ProbeSpec("s", "remote_csv"), b"a\n1\n"),
        (ProbeSpec("s", "remote_html_table"),
         b"<table><tr><th>a</th></tr><tr><td>1</td></tr></table>"),
    ]
    for spec, content in cases:
        result = _measure_remote(spec, response(content=content))
        assert result is not None and result.row_count == 1, spec.kind
    assert _measure_remote(ProbeSpec("s", "availability"), response()) is None


def test_measure_remote_returns_none_for_unparseable_json() -> None:
    assert _measure_remote(ProbeSpec("s", "rest_json"), response(content=b"<html>")) is None
    assert _measure_remote(
        ProbeSpec("s", "rest_json", record_path=("missing",)), response(content=b"{}")
    ) is None


def test_measure_remote_drops_a_truncated_trailing_line() -> None:
    """A byte-capped stream cuts mid-record; the partial row must not skew missingness."""
    full = _measure_remote(
        ProbeSpec("s", "remote_csv"), response(content=b"a,b\n1,2\n3,4\n")
    )
    cut = _measure_remote(
        ProbeSpec("s", "remote_csv"), response(content=b"a,b\n1,2\n3,", truncated=True)
    )
    assert full is not None and cut is not None
    assert full.row_count == 2
    assert cut.row_count == 1


# --- classification ---------------------------------------------------------------

def build(status: int, content: bytes = b"a\n1\n", **kw: object) -> Response:
    return response(status_code=status, content=content, **kw)


def probe_with(spec: ProbeSpec, resp: Response) -> object:
    class Stub:
        def get(self, *args: object, **kwargs: object) -> Response:
            return resp

    return probe_remote(spec, Stub())


def test_confirmed_when_records_were_measured() -> None:
    obs = probe_with(ProbeSpec("s", "remote_csv"), build(200))
    assert obs.status == "confirmed"  # type: ignore[attr-defined]
    assert "1 records measured" in obs.note  # type: ignore[attr-defined]


def test_confirmed_for_an_availability_probe() -> None:
    obs = probe_with(ProbeSpec("s", "availability"), build(206, b"abc"))
    assert obs.status == "confirmed"  # type: ignore[attr-defined]
    assert "reachable, HTTP 206" in obs.note  # type: ignore[attr-defined]


def test_gated_on_a_credential_marker() -> None:
    obs = probe_with(
        ProbeSpec("s", "rest_json", needs_api_key="census"),
        build(200, b'{"error":{"code":"API_KEY_MISSING"}}'),
    )
    assert obs.status == "gated"  # type: ignore[attr-defined]
    assert "CENSUS_API_KEY" in obs.note  # type: ignore[attr-defined]


def test_gated_on_http_429_records_the_measured_limit() -> None:
    obs = probe_with(
        ProbeSpec("s", "rest_json"),
        build(429, b"{}", headers={"x-ratelimit-limit": "10", "retry-after": "78590"}),
    )
    assert obs.status == "gated"  # type: ignore[attr-defined]
    assert "x-ratelimit-limit=10" in obs.note  # type: ignore[attr-defined]
    assert "retry-after=78590s" in obs.note  # type: ignore[attr-defined]


def test_unavailable_on_http_404() -> None:
    obs = probe_with(ProbeSpec("s", "remote_csv"), build(404, b""))
    assert obs.status == "unavailable"  # type: ignore[attr-defined]
    assert obs.note.startswith("HTTP 404")  # type: ignore[attr-defined]


def test_degraded_when_the_payload_cannot_be_measured() -> None:
    obs = probe_with(ProbeSpec("s", "rest_json"), build(200, b"<html>not json</html>"))
    assert obs.status == "degraded"  # type: ignore[attr-defined]
    assert "could not be measured" in obs.note  # type: ignore[attr-defined]


def test_degraded_when_the_sample_is_empty() -> None:
    obs = probe_with(ProbeSpec("s", "remote_csv"), build(200, b"a,b\n"))
    assert obs.status == "degraded"  # type: ignore[attr-defined]
    assert "no records" in obs.note  # type: ignore[attr-defined]


def test_truncation_is_disclosed_in_the_note() -> None:
    obs = probe_with(ProbeSpec("s", "remote_csv"), build(200, b"a\n1\n", truncated=True))
    assert "bounded sample: transfer capped" in obs.note  # type: ignore[attr-defined]


def test_vintage_falls_back_to_last_modified() -> None:
    obs = probe_with(
        ProbeSpec("s", "remote_csv"), build(200, headers={"last-modified": "Mon, 18 Mar 2026"})
    )
    assert obs.vintage == "Mon, 18 Mar 2026"  # type: ignore[attr-defined]


def test_vintage_pointer_wins_over_last_modified() -> None:
    obs = probe_with(
        ProbeSpec("s", "rest_json", vintage_pointer=("last_updated",)),
        build(200, b'{"last_updated":"2026-08-19"}', headers={"last-modified": "Mon"}),
    )
    assert obs.vintage == "2026-08-19"  # type: ignore[attr-defined]


def test_a_connection_failure_is_recorded_as_unavailable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    fetcher = LiveFetcher(
        tmp_path, client_factory=make_client_factory(handler), sleep=lambda _: None
    )
    obs = probe_remote(ProbeSpec("s", "remote_csv", url="https://x"), fetcher)
    assert obs.status == "unavailable"
    assert "ConnectionError" in obs.note


def test_a_cache_miss_is_recorded_as_unavailable(tmp_path: Path) -> None:
    obs = probe_remote(ProbeSpec("s", "remote_csv", url="https://x"), ReplayFetcher(tmp_path))
    assert obs.status == "unavailable"
    assert "CacheMissError" in obs.note


def test_the_api_key_is_attached_when_the_spec_needs_one(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    monkeypatch.setenv("NREL_API_KEY", "personal-key")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, content=b"a\n1\n")

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    probe_remote(
        ProbeSpec("s", "remote_csv", url="https://x", needs_api_key="nrel"), fetcher
    )
    assert seen["api_key"] == "personal-key"


def test_no_api_key_parameter_is_sent_when_none_is_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CENSUS_API_KEY", "")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, content=b"a\n1\n")

    fetcher = LiveFetcher(tmp_path, client_factory=make_client_factory(handler))
    probe_remote(
        ProbeSpec("s", "remote_csv", url="https://x", needs_api_key="census"), fetcher
    )
    assert "api_key" not in seen


# --- local probes -----------------------------------------------------------------

def test_probe_local_measures_a_csv(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    obs = probe_local(ProbeSpec("s", "local_csv", local_path=path))
    assert obs.status == "confirmed"
    assert obs.measurement is not None
    assert obs.measurement["row_count"] == 1
    assert obs.content_bytes == path.stat().st_size


def test_probe_local_streams_geojson(tmp_path: Path) -> None:
    path = tmp_path / "x.geojson"
    path.write_text('{"features":[{ "properties": { "VOLTAGE": 345 } }]}', encoding="utf-8")
    obs = probe_local(ProbeSpec("s", "local_geojson", local_path=path, max_rows=5))
    assert obs.measurement is not None
    assert obs.measurement["fields"] == ["VOLTAGE"]


def test_probe_local_reports_an_absent_file_without_substituting_anything(
    tmp_path: Path,
) -> None:
    """Directive D8: degrade explicitly, never fill a gap with a plausible default."""
    obs = probe_local(ProbeSpec("s", "local_csv", local_path=tmp_path / "missing.csv"))
    assert obs.status == "unavailable"
    assert obs.measurement is None
    assert "SEED_INVENTORY.md" in obs.note


def test_probe_one_dispatches_local_and_remote(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    assert probe_one(ProbeSpec("s", "local_csv", local_path=path),
                     ReplayFetcher(tmp_path)).status == "confirmed"
    assert probe_one(ProbeSpec("s", "remote_csv", url="https://x"),
                     ReplayFetcher(tmp_path)).status == "unavailable"


# --- run and CLI -------------------------------------------------------------------

def test_run_evaluates_drift_only_for_sources_that_have_a_contract_entry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    specs = (ProbeSpec("known", "local_csv", local_path=path),
             ProbeSpec("unknown", "local_csv", local_path=path))
    contract = {"sources": [{"id": "known",
                             "quality": {"expected_row_count": [1, 1], "drift_tolerance": 0.0},
                             "schema": {"schema_version": "x"}}]}
    observations, drifts = run(specs, ReplayFetcher(tmp_path), contract)
    assert len(observations) == 2
    assert [d.source_id for d in drifts] == ["known"]


def test_run_without_a_contract_evaluates_no_drift(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    _, drifts = run((ProbeSpec("s", "local_csv", local_path=path),), ReplayFetcher(tmp_path))
    assert drifts == []


def test_build_fetcher_selects_the_mode() -> None:
    assert isinstance(build_fetcher(True, Path(".")), ReplayFetcher)
    assert isinstance(build_fetcher(False, Path(".")), LiveFetcher)


def test_main_replays_the_committed_fixtures_and_writes_the_sidecar(
    tmp_path: Path, replay_root: Path
) -> None:
    out = tmp_path / "observed.json"
    code = main([
        "--offline", "--cache-root", str(replay_root), "--out", str(out),
        "--only", "seed_state_ev_registrations,afdc_state_ev_registrations_2023",
    ])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["generated_by"] == GENERATOR
    assert [o["source_id"] for o in payload["observations"]] == [
        "afdc_state_ev_registrations_2023", "seed_state_ev_registrations"
    ]


def test_main_honours_no_write(tmp_path: Path, replay_root: Path) -> None:
    out = tmp_path / "observed.json"
    main(["--offline", "--cache-root", str(replay_root), "--out", str(out),
          "--only", "seed_state_ev_registrations", "--no-write"])
    assert not out.exists()


def test_main_exits_non_zero_when_a_source_drifts(
    tmp_path: Path, replay_root: Path
) -> None:
    contract = tmp_path / "SOURCES.yml"
    contract.write_text(
        "sources:\n"
        "  - id: seed_state_ev_registrations\n"
        "    name: n\n    tier: core\n"
        "    retrieval: {method: bulk_download, endpoint: x, auth: none, rate_limit: none}\n"
        "    coverage: {geographic: x, temporal: x, historical_vintages_available: false,"
        " vintage_field: null, vintage_semantics: x}\n"
        "    schema: {join_keys: [], stable_keys: true, schema_version: nope}\n"
        "    quality: {expected_row_count: [1, 1], drift_tolerance: 0.0,"
        " expected_range_derivation: x}\n"
        "    license: x\n    update_cadence: x\n    fallback_source: none\n"
        "    used_by: [x]\n    backtest_eligible: false\n    known_limitations: [x]\n"
        "findings:\n"
        "  - id: F-1\n    question: q\n    resolved_value: v\n    evidence_url: u\n"
        "    retrieved_at: t\n    evidence_quote: q\n    evidence_artifact: a\n"
        "    evidence_sha256: h\n",
        encoding="utf-8",
    )
    code = main(["--offline", "--cache-root", str(replay_root),
                 "--out", str(tmp_path / "o.json"), "--contract", str(contract),
                 "--only", "seed_state_ev_registrations"])
    assert code == 1, "52 observed rows against an expected [1, 1] must fail the run"


def test_main_skips_contract_validation_when_the_file_is_absent(
    tmp_path: Path, replay_root: Path
) -> None:
    code = main(["--offline", "--cache-root", str(replay_root),
                 "--out", str(tmp_path / "o.json"),
                 "--contract", str(tmp_path / "absent.yml"),
                 "--only", "seed_state_ev_registrations"])
    assert code == 0


def test_main_probes_every_spec_when_only_is_not_given(
    tmp_path: Path, replay_root: Path
) -> None:
    out = tmp_path / "observed.json"
    code = main(["--offline", "--cache-root", str(replay_root), "--out", str(out)])
    assert code == 0
    payload = json.loads(out.read_text())
    assert len(payload["observations"]) == len(all_specs())


def test_main_prints_every_source_that_is_not_confirmed(
    tmp_path: Path, replay_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--offline", "--cache-root", str(replay_root), "--out", str(tmp_path / "o.json"),
          "--only", "census_cenpop_block"])
    captured = capsys.readouterr().out
    assert "unavailable" in captured
    assert "census_cenpop_block" in captured


def test_nested_json_units_measurement_reshapes_stations_into_unit_rows() -> None:
    """The AFDC primary representation nests units inside stations (amendment A23)."""
    payload = json.dumps({"fuel_stations": [{
        "id": 7, "state": "MN",
        "ev_charging_units": [
            {"network": "N", "port_count": 1, "charging_level": "dc_fast",
             "connectors": {"J1772COMBO": {"power_kw": 150.0, "port_count": 1}}},
            {"network": "N", "port_count": 1, "charging_level": "2",
             "connectors": {"J1772": {"power_kw": 7.2, "port_count": 1}}},
        ],
    }]}).encode()
    result = _measure_remote(
        ProbeSpec("afdc_charging_units", "nested_json_units"), response(content=payload)
    )
    assert result is not None
    assert result.row_count == 2, "one row per charging unit, not per station"
    assert "connector_J1772COMBO_power_kw" in result.fields
    assert "unit_port_count" in result.fields


def test_nested_json_units_measurement_returns_none_on_an_unparseable_payload() -> None:
    assert _measure_remote(
        ProbeSpec("s", "nested_json_units"), response(content=b"<html>not json</html>")
    ) is None
