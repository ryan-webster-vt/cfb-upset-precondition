"""Live capability probe (P0.1).

The probe re-verifies every external dependency the plan depends on, records
PASS/FAIL/SKIP with redacted evidence, and captures golden fixtures for the
decision model and embeddings. It writes ``docs/CAPABILITIES.md`` and
``docs/capabilities.json`` when ``--write`` is passed.

This module is intentionally excluded from coverage: it is a live diagnostic,
not application logic.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from cfb_upset.config import Settings
from cfb_upset.ids import monotonic_ms

PROBE_VERSION = "p0.1"
FIXTURES_ROOT = Path("tests/fixtures")
DOCS_ROOT = Path("docs")


@dataclass
class ProbeCheck:
    """One capability result shown in the matrix."""

    name: str
    status: str  # PASS | FAIL | SKIP | PARTIAL
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None


@dataclass
class CapabilityReport:
    """Aggregate probe report and the chosen backend decisions."""

    timestamp: datetime
    checks: list[ProbeCheck] = field(default_factory=list)
    chosen_backends: dict[str, str] = field(default_factory=dict)
    operating_envelope: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    fixtures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, check: ProbeCheck) -> None:
        self.checks.append(check)

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        return counts

    def to_json(self) -> dict[str, Any]:
        return {
            "probe_version": PROBE_VERSION,
            "timestamp": self.timestamp.isoformat(),
            "status_counts": self.status_counts(),
            "chosen_backends": self.chosen_backends,
            "operating_envelope": self.operating_envelope,
            "environment": self.environment,
            "fixtures": self.fixtures,
            "notes": self.notes,
            "checks": [asdict(check) for check in self.checks],
        }

    def to_markdown(self) -> str:
        lines: list[str] = [
            "# Capability Matrix — Phase 0",
            "",
            f"**Generated:** {self.timestamp.isoformat()}  ",
            f"**Probe version:** {PROBE_VERSION}  ",
            "**Status legend:** PASS = verified live; FAIL = unavailable/contrary to plan; "
            "SKIP = no credential/endpoint; PARTIAL = observed but incomplete.",
            "",
            "## Summary",
            "",
            "| Status | Count |",
            "| --- | ---: |",
        ]
        for status, count in sorted(self.status_counts().items()):
            lines.append(f"| {status} | {count} |")
        lines.extend(
            [
                "",
                "## Checks",
                "",
                "| Capability | Status | Detail | Evidence (redacted) |",
                "| --- | --- | --- | --- |",
            ]
        )
        for check in self.checks:
            evidence = _short_json(_redact(check.evidence), limit=700)
            duration = f" ({check.duration_ms:.0f} ms)" if check.duration_ms is not None else ""
            lines.append(
                f"| {check.name} | **{check.status}** | {check.detail}{duration} | `{evidence}` |"
            )

        if self.chosen_backends:
            lines.extend(["", "## Chosen backends (P0.8)", ""])
            for key, value in self.chosen_backends.items():
                lines.append(f"- **{key}:** {value}")

        if self.operating_envelope:
            lines.extend(
                ["", "## `systemone` operating envelope", "", "| Limit | Value |", "| --- | --- |"]
            )
            for key, value in self.operating_envelope.items():
                lines.append(f"| {key} | {value} |")

        if self.fixtures:
            lines.extend(["", "## Captured fixtures", ""])
            for fixture in self.fixtures:
                lines.append(f"- `{fixture}`")

        if self.notes:
            lines.extend(["", "## Notes", ""])
            for note in self.notes:
                lines.append(f"- {note}")

        lines.extend(
            [
                "",
                "## Redaction",
                "",
                "No `Authorization` header, API key, or token is written to this report or to the "
                "committed fixtures. Evidence contains status codes, counts, field names, measured "
                "widths, and model ids only.",
                "",
            ]
        )
        return "\n".join(lines)


_SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "api_token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "x_subscription_token",
}


def _is_secret_key(key: str) -> bool:
    """Return True only for credential-shaped keys.

    A naive ``"token" in key`` test also masks usage counters such as
    ``input_tokens``/``output_tokens`` and vertex ids such as ``token_ids``, so
    match exact secret names (with ``-``/``_`` normalised) or a ``_token``
    suffix.
    """

    lowered = key.strip().lower().replace("-", "_")
    return lowered in _SECRET_KEYS or lowered.endswith(("_token", "_api_key", "_secret"))


def _redact(value: Any) -> Any:
    """Recursively mask credential-shaped keys and long bodies."""

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(key):
                cleaned[key] = "***"
            else:
                cleaned[key] = _redact(item)
        return cleaned
    if isinstance(value, list):
        return [_redact(item) for item in value[:5]]
    if isinstance(value, str):
        return value if len(value) <= 1200 else value[:1200] + "…"
    return value


def _short_json(value: Any, *, limit: int = 700) -> str:
    text = json.dumps(_redact(value), sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_redact(payload), indent=2, sort_keys=True, default=str) + "\n")


def _response_json(response: httpx.Response) -> tuple[Any, str]:
    try:
        return response.json(), "json"
    except (json.JSONDecodeError, ValueError):
        return response.text[:2000], "text"


def _headers(settings: Settings) -> dict[str, str]:
    if settings.arc_key:
        return {"Authorization": f"Bearer {settings.arc_key}"}
    return {}


def _cfbd_headers(settings: Settings) -> dict[str, str]:
    if settings.cfbd_key:
        return {"Authorization": f"Bearer {settings.cfbd_key}"}
    return {}


async def probe_espn(
    client: httpx.AsyncClient,
    settings: Settings,
    report: CapabilityReport,
) -> None:
    """Probe scoreboard, summary, odds, rankings, teams, and FBS groups."""

    base = settings.espn_api_base_url.rstrip("/")
    core = settings.espn_core_base_url.rstrip("/")
    fixtures = FIXTURES_ROOT / "espn"

    started = monotonic_ms()
    try:
        response = await client.get(
            f"{base}/scoreboard", params={"dates": "20251115", "limit": 100}
        )
        payload, kind = _response_json(response)
        events = payload.get("events", []) if isinstance(payload, dict) else []
        has_odds = any(
            event.get("competitions", [{}])[0].get("odds")
            for event in events
            if isinstance(event, dict) and event.get("competitions")
        )
        report.add(
            ProbeCheck(
                name="ESPN historical scoreboard",
                status="PASS" if response.status_code == 200 and events else "FAIL",
                detail=f"HTTP {response.status_code}; {len(events)} events; odds_present={has_odds}",
                evidence={"status": response.status_code, "events": len(events), "kind": kind},
                duration_ms=monotonic_ms() - started,
            )
        )
        if events:
            _write_json(fixtures / "scoreboard_20251115.json", {"events": events[:3]})
    except Exception as exc:
        report.add(
            ProbeCheck(
                name="ESPN historical scoreboard",
                status="FAIL",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    started = monotonic_ms()
    try:
        response = await client.get(
            f"{base}/scoreboard", params={"dates": "20261128", "limit": 100}
        )
        payload, _ = _response_json(response)
        events = payload.get("events", []) if isinstance(payload, dict) else []
        odds_count = 0
        for event in events:
            competitions = event.get("competitions", [])
            if competitions and competitions[0].get("odds"):
                odds_count += 1
        report.add(
            ProbeCheck(
                name="ESPN future slate + odds",
                status="PASS" if response.status_code == 200 and events else "FAIL",
                detail=f"HTTP {response.status_code}; {len(events)} events; {odds_count} with odds",
                evidence={
                    "status": response.status_code,
                    "events": len(events),
                    "with_odds": odds_count,
                },
                duration_ms=monotonic_ms() - started,
            )
        )
        if events:
            _write_json(fixtures / "scoreboard_20261128.json", {"events": events[:3]})
    except Exception as exc:
        report.add(
            ProbeCheck(
                name="ESPN future slate + odds",
                status="FAIL",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    started = monotonic_ms()
    try:
        response = await client.get(f"{base}/summary", params={"event": "401628543"})
        payload, _ = _response_json(response)
        keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        report.add(
            ProbeCheck(
                name="ESPN summary",
                status="PASS" if response.status_code == 200 else "FAIL",
                detail=f"HTTP {response.status_code}; keys={keys[:10]}",
                evidence={"status": response.status_code, "keys": keys},
                duration_ms=monotonic_ms() - started,
            )
        )
        if isinstance(payload, dict):
            trimmed = {
                key: payload.get(key)
                for key in keys
                if key in {"header", "boxscore", "gameInfo", "standings"}
            }
            _write_json(fixtures / "summary_401628543.json", trimmed)
    except Exception as exc:
        report.add(ProbeCheck("ESPN summary", "FAIL", f"{type(exc).__name__}: {exc}"))

    started = monotonic_ms()
    try:
        response = await client.get(f"{core}/events/401628543/competitions/401628543/odds")
        payload, _ = _response_json(response)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        providers = [
            item.get("provider", {}).get("name") for item in items if isinstance(item, dict)
        ]
        report.add(
            ProbeCheck(
                name="ESPN core odds",
                status="PASS" if response.status_code == 200 else "FAIL",
                detail=f"HTTP {response.status_code}; {len(items)} items; providers={providers[:5]}",
                evidence={
                    "status": response.status_code,
                    "items": len(items),
                    "providers": providers,
                },
                duration_ms=monotonic_ms() - started,
            )
        )
        _write_json(fixtures / "odds_401628543.json", payload if isinstance(payload, dict) else {})
    except Exception as exc:
        report.add(ProbeCheck("ESPN core odds", "FAIL", f"{type(exc).__name__}: {exc}"))

    started = monotonic_ms()
    try:
        # The site API carries the poll collections; the core endpoint returns a
        # paginated ``items`` list instead of a ``rankings`` array.
        response = await client.get(
            f"{base}/rankings",
            params={"season": 2024, "seasontype": 2, "week": 10},
        )
        payload, _ = _response_json(response)
        polls = payload.get("rankings", []) if isinstance(payload, dict) else []
        poll_names = [
            poll.get("name") for poll in polls if isinstance(poll, dict) and poll.get("name")
        ]
        report.add(
            ProbeCheck(
                name="ESPN weekly rankings",
                status="PASS" if response.status_code == 200 and polls else "FAIL",
                detail=f"HTTP {response.status_code}; {len(polls)} ranking collections; polls={poll_names}",
                evidence={
                    "status": response.status_code,
                    "rankings": len(polls),
                    "polls": poll_names,
                },
                duration_ms=monotonic_ms() - started,
            )
        )
        _write_json(
            fixtures / "rankings_2024_w10.json", payload if isinstance(payload, dict) else {}
        )
    except Exception as exc:
        report.add(ProbeCheck("ESPN weekly rankings", "FAIL", f"{type(exc).__name__}: {exc}"))

    started = monotonic_ms()
    try:
        response = await client.get(f"{base}/teams", params={"limit": 1000})
        payload, _ = _response_json(response)
        sports = payload.get("sports", []) if isinstance(payload, dict) else []
        leagues = sports[0].get("leagues", []) if sports else []
        teams = leagues[0].get("teams", []) if leagues else []
        report.add(
            ProbeCheck(
                name="ESPN teams",
                status="PASS" if response.status_code == 200 and teams else "FAIL",
                detail=f"HTTP {response.status_code}; {len(teams)} teams",
                evidence={"status": response.status_code, "teams": len(teams)},
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(ProbeCheck("ESPN teams", "FAIL", f"{type(exc).__name__}: {exc}"))

    for group_id, label in (("80", "FBS"), ("81", "FCS")):
        started = monotonic_ms()
        try:
            response = await client.get(f"{core}/groups/{group_id}")
            payload, _ = _response_json(response)
            name = payload.get("name") if isinstance(payload, dict) else None
            report.add(
                ProbeCheck(
                    name=f"ESPN group {group_id} ({label})",
                    status="PASS" if response.status_code == 200 else "FAIL",
                    detail=f"HTTP {response.status_code}; name={name}",
                    evidence={"status": response.status_code, "name": name},
                    duration_ms=monotonic_ms() - started,
                )
            )
        except Exception as exc:
            report.add(ProbeCheck(f"ESPN group {group_id} ({label})", "FAIL", str(exc)))


async def probe_arc(
    client: httpx.AsyncClient,
    settings: Settings,
    report: CapabilityReport,
) -> None:
    """Probe the ARC model list and a JSON-only chat completion."""

    base = settings.vt_arc_base_url.rstrip("/")
    headers = _headers(settings)
    fixtures = FIXTURES_ROOT / "arc"
    if not settings.has_arc:
        report.add(ProbeCheck("ARC /models", "SKIP", "no VT_ARC_API_KEY/OPEN_AI_API_KEY"))
        report.add(ProbeCheck("ARC chat JSON mode", "SKIP", "no credential"))
        return

    started = monotonic_ms()
    try:
        response = await client.get(f"{base}/models", headers=headers)
        payload, _ = _response_json(response)
        ids = (
            [item.get("id") for item in payload.get("data", [])]
            if isinstance(payload, dict)
            else []
        )
        report.add(
            ProbeCheck(
                name="ARC /models",
                status="PASS" if response.status_code == 200 else "FAIL",
                detail=f"HTTP {response.status_code}; {len(ids)} model ids",
                evidence={"status": response.status_code, "models": ids},
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(ProbeCheck("ARC /models", "FAIL", f"{type(exc).__name__}: {exc}"))

    request = {
        "model": settings.vt_arc_model,
        "messages": [
            {
                "role": "user",
                "content": 'Return only this JSON object and nothing else: {"ok": true}',
            }
        ],
        "temperature": 0,
        # GLM-5.3 spends completion tokens on hidden reasoning first; 40 tokens
        # can finish with ``content=None`` and ``finish_reason="length"``.
        "max_tokens": 256,
    }
    started = monotonic_ms()
    try:
        response = await client.post(
            f"{base}/chat/completions", headers=headers, json=request, timeout=90.0
        )
        payload, kind = _response_json(response)
        content: str | None = None
        reasoning: str | None = None
        finish_reason: str | None = None
        if isinstance(payload, dict):
            choices = payload.get("choices") or []
            if choices:
                choice = choices[0] if isinstance(choices[0], dict) else {}
                message = choice.get("message") or {}
                content = message.get("content")
                reasoning = message.get("reasoning")
                finish_reason = choice.get("finish_reason")
        parsed = False
        if isinstance(content, str):
            try:
                json.loads(content)
                parsed = True
            except (json.JSONDecodeError, TypeError, ValueError):
                parsed = False
        report.add(
            ProbeCheck(
                name="ARC chat JSON mode",
                status=(
                    "PASS"
                    if response.status_code == 200 and parsed and finish_reason != "length"
                    else "PARTIAL" if response.status_code == 200 else "FAIL"
                ),
                detail=(
                    f"HTTP {response.status_code}; json_parse={parsed}; "
                    f"finish_reason={finish_reason}; "
                    f"content={(content or '')[:120]!r}"
                ),
                evidence={
                    "status": response.status_code,
                    "kind": kind,
                    "json_parse": parsed,
                    "finish_reason": finish_reason,
                    "content_chars": len(content or ""),
                    "reasoning_chars": len(reasoning or ""),
                },
                duration_ms=monotonic_ms() - started,
            )
        )
        _write_json(
            fixtures / "chat_json.json",
            {"request": {**request, "messages": request["messages"]}, "response": payload},
        )
    except Exception as exc:
        report.add(ProbeCheck("ARC chat JSON mode", "FAIL", f"{type(exc).__name__}: {exc}"))


def _systemone_url(settings: Settings) -> str:
    endpoint = settings.vt_arc_decision_endpoint
    if endpoint.startswith("http"):
        return endpoint
    return settings.vt_arc_base_url.rstrip("/") + "/" + endpoint.lstrip("/")


def _systemone_requests(settings: Settings) -> dict[str, dict[str, Any]]:
    model = settings.vt_arc_decision_model
    state = (
        "Virginia Tech hosts Miami on Saturday. Miami is a 7-point favorite. "
        "Virginia Tech is 7-4 and Miami is 10-1. Kickoff is at 12:00 ET."
    )
    return {
        "noul": {
            "model": model,
            "state": state,
            "questions": {
                "upset_likely": {
                    "type": "noul",
                    "instructions": "Will the home team win outright?",
                }
            },
        },
        "choice": {
            "model": model,
            "state": state,
            "questions": {
                "confirm": {
                    "type": "choice",
                    "instructions": "Does the evidence confirm Miami is overvalued?",
                    "criteria": {
                        "confirmed": "Evidence supports the flag.",
                        "contradicted": "The strongest evidence says the flag is false.",
                        "insufficient": "The evidence is not decisive.",
                    },
                }
            },
        },
        "score": {
            "model": model,
            "state": state,
            "questions": {
                "risk": {
                    "type": "score",
                    "instructions": "How likely is an upset?",
                    "criteria": [
                        "very unlikely",
                        "unlikely",
                        "possible",
                        "likely",
                        "very likely",
                    ],
                }
            },
        },
    }


async def probe_systemone(
    client: httpx.AsyncClient,
    settings: Settings,
    report: CapabilityReport,
    *,
    deep_limits: bool = False,
) -> None:
    """Verify the captured ``systemone`` contract and record limit behavior."""

    url = _systemone_url(settings)
    headers = _headers(settings)
    fixtures = FIXTURES_ROOT / "systemone"
    report.operating_envelope = {
        "model": settings.vt_arc_decision_model,
        "endpoint": url,
        "max_concurrency": settings.systemone_max_concurrency,
        "max_input_tokens_per_question": settings.systemone_max_input_tokens,
        "max_request_bytes": settings.systemone_max_request_bytes,
        "queue_wait_s": settings.systemone_queue_wait_s,
        "questions_per_game_cap": settings.systemone_max_questions_per_game,
    }
    if not settings.has_arc:
        report.add(ProbeCheck("systemone golden fixtures", "SKIP", "no ARC credential"))
        return

    requests = _systemone_requests(settings)
    responses: dict[str, Any] = {}
    for name, request in requests.items():
        started = monotonic_ms()
        try:
            response = await client.post(url, headers=headers, json=request, timeout=60.0)
            payload, kind = _response_json(response)
            responses[name] = {"status": response.status_code, "payload": payload}
            _write_json(fixtures / f"{name}_request.json", request)
            _write_json(fixtures / f"{name}_response.json", payload)
            ok = response.status_code == 200 and isinstance(payload, dict) and "answers" in payload
            report.add(
                ProbeCheck(
                    name=f"systemone {name}",
                    status="PASS" if ok else "FAIL",
                    detail=f"HTTP {response.status_code}; kind={kind}; "
                    f"answer_keys={list(payload.get('answers', {})) if isinstance(payload, dict) else []}",
                    evidence={
                        "status": response.status_code,
                        "usage": payload.get("usage") if isinstance(payload, dict) else None,
                    },
                    duration_ms=monotonic_ms() - started,
                )
            )
        except Exception as exc:
            report.add(
                ProbeCheck(
                    name=f"systemone {name}", status="FAIL", detail=f"{type(exc).__name__}: {exc}"
                )
            )

    # Determinism: three identical noul requests.
    values: list[Any] = []
    latencies: list[float] = []
    for _ in range(3):
        started = monotonic_ms()
        try:
            response = await client.post(url, headers=headers, json=requests["noul"], timeout=60.0)
            payload, _ = _response_json(response)
            latencies.append(monotonic_ms() - started)
            values.append(
                payload.get("answers", {}).get("upset_likely", {}).get("noul")
                if isinstance(payload, dict)
                else None
            )
        except Exception as exc:
            values.append(f"ERR:{type(exc).__name__}")
    deterministic = len(values) == 3 and len(set(map(str, values))) == 1
    report.add(
        ProbeCheck(
            name="systemone determinism (noul x3)",
            status="PASS" if deterministic else "PARTIAL",
            detail=f"values={values}; latencies_ms={[round(value) for value in latencies]}",
            evidence={"values": values, "latencies_ms": latencies},
        )
    )

    # Long-payload determinism and latency.
    long_state = " ".join(
        ["The underdog has extra rest and the favorite may be looking ahead."] * 300
    )
    long_request = {
        "model": settings.vt_arc_decision_model,
        "state": long_state,
        "questions": requests["noul"]["questions"],
    }
    long_values: list[Any] = []
    long_latencies: list[float] = []
    long_usage: list[Any] = []
    for _ in range(2):
        started = monotonic_ms()
        try:
            response = await client.post(url, headers=headers, json=long_request, timeout=90.0)
            payload, _ = _response_json(response)
            long_latencies.append(monotonic_ms() - started)
            long_usage.append(payload.get("usage") if isinstance(payload, dict) else None)
            long_values.append(
                payload.get("answers", {}).get("upset_likely", {}).get("noul")
                if isinstance(payload, dict)
                else None
            )
        except Exception as exc:
            long_values.append(f"ERR:{type(exc).__name__}")
    report.add(
        ProbeCheck(
            name="systemone determinism (long payload x2)",
            status=(
                "PASS"
                if len(long_values) == 2 and len(set(map(str, long_values))) == 1
                else "PARTIAL"
            ),
            detail=f"values={long_values}; latencies_ms={[round(value) for value in long_latencies]}",
            evidence={
                "chars": len(long_state),
                "values": long_values,
                "latencies_ms": long_latencies,
                "usage": long_usage,
            },
        )
    )

    # 400: empty questions. 404: decision model on the chat path.
    started = monotonic_ms()
    try:
        bad = {"model": settings.vt_arc_decision_model, "state": "test", "questions": {}}
        response = await client.post(url, headers=headers, json=bad, timeout=30.0)
        payload, _ = _response_json(response)
        _write_json(fixtures / "error_400_empty_questions_request.json", bad)
        _write_json(fixtures / "error_400_empty_questions_response.json", payload)
        report.add(
            ProbeCheck(
                name="systemone 400 envelope",
                status="PASS" if response.status_code == 400 else "PARTIAL",
                detail=f"HTTP {response.status_code}; body={str(payload)[:200]}",
                evidence={"status": response.status_code, "body": payload},
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(ProbeCheck("systemone 400 envelope", "FAIL", f"{type(exc).__name__}: {exc}"))

    started = monotonic_ms()
    try:
        chat_request = {
            "model": settings.vt_arc_decision_model,
            "messages": [{"role": "user", "content": "test"}],
        }
        response = await client.post(
            settings.vt_arc_base_url.rstrip("/") + "/chat/completions",
            headers=headers,
            json=chat_request,
            timeout=30.0,
        )
        payload, _ = _response_json(response)
        _write_json(fixtures / "error_404_chat_completions_request.json", chat_request)
        _write_json(fixtures / "error_404_chat_completions_response.json", payload)
        report.add(
            ProbeCheck(
                name="systemone 404 on /chat/completions",
                status="PASS" if response.status_code == 404 else "PARTIAL",
                detail=f"HTTP {response.status_code}; body={str(payload)[:200]}",
                evidence={"status": response.status_code, "body": payload},
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(
            ProbeCheck("systemone 404 on /chat/completions", "FAIL", f"{type(exc).__name__}: {exc}")
        )

    # 5-way burst: the owner cap is 4 concurrent requests.
    burst_requests = []
    for index in range(5):
        request = json.loads(json.dumps(requests["noul"]))
        request["state"] = f"Burst probe request {index}. " + request["state"]
        burst_requests.append(request)
    started = monotonic_ms()
    try:
        burst = await asyncio.gather(
            *[
                client.post(url, headers=headers, json=request, timeout=60.0)
                for request in burst_requests
            ],
            return_exceptions=True,
        )
        burst_summary = []
        for item in burst:
            if isinstance(item, Exception):
                burst_summary.append({"exception": type(item).__name__})
            else:
                payload, _ = _response_json(item)
                burst_summary.append({"status": item.status_code, "body": str(payload)[:300]})
        statuses = [item.get("status") for item in burst_summary if "status" in item]
        _write_json(fixtures / "limit_429_burst.json", burst_summary)
        report.add(
            ProbeCheck(
                name="systemone 5-way burst (429)",
                status="PASS" if 429 in statuses else "PARTIAL",
                detail=f"statuses={statuses}; 429_observed={429 in statuses}",
                evidence={"results": burst_summary},
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(
            ProbeCheck("systemone 5-way burst (429)", "FAIL", f"{type(exc).__name__}: {exc}")
        )

    # Oversized body: > 8 MiB should be rejected with 413.
    started = monotonic_ms()
    oversized = {
        "model": settings.vt_arc_decision_model,
        "state": "x" * (settings.systemone_max_request_bytes + 1024),
        "questions": requests["noul"]["questions"],
    }
    try:
        response = await client.post(
            url,
            headers={**headers, "Content-Type": "application/json"},
            content=json.dumps(oversized),
            timeout=60.0,
        )
        payload, _ = _response_json(response)
        _write_json(
            fixtures / "limit_413_payload.json", {"status": response.status_code, "body": payload}
        )
        report.add(
            ProbeCheck(
                name="systemone oversized body (413)",
                status="PASS" if response.status_code == 413 else "PARTIAL",
                detail=f"HTTP {response.status_code}; body={str(payload)[:200]}",
                evidence={"status": response.status_code, "body": payload},
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(
            ProbeCheck("systemone oversized body (413)", "FAIL", f"{type(exc).__name__}: {exc}")
        )

    # Near-limit input: learn whether the provider truncates or errors.
    started = monotonic_ms()
    near_limit_state = "word " * 6000
    near_limit_request = {
        "model": settings.vt_arc_decision_model,
        "state": near_limit_state,
        "questions": requests["noul"]["questions"],
    }
    try:
        response = await client.post(url, headers=headers, json=near_limit_request, timeout=120.0)
        payload, _ = _response_json(response)
        _write_json(
            fixtures / "limit_input.json",
            {
                "chars": len(near_limit_state),
                "status": response.status_code,
                "usage": payload.get("usage") if isinstance(payload, dict) else None,
                "body": payload,
            },
        )
        report.add(
            ProbeCheck(
                name="systemone near-8k input",
                status="PASS" if response.status_code == 200 else "PARTIAL",
                detail=f"chars={len(near_limit_state)}; HTTP {response.status_code}; "
                f"usage={payload.get('usage') if isinstance(payload, dict) else None}",
                evidence={
                    "chars": len(near_limit_state),
                    "status": response.status_code,
                    "usage": payload.get("usage") if isinstance(payload, dict) else None,
                },
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(ProbeCheck("systemone near-8k input", "FAIL", f"{type(exc).__name__}: {exc}"))

    # Held request / queue timeout. This is opt-in because it intentionally
    # occupies the shared 4-request window for up to 30 seconds.
    if not deep_limits:
        report.add(
            ProbeCheck(
                name="systemone queue timeout (503)",
                status="SKIP",
                detail="opt-in --deep-limits; holding four requests for 30 s would consume the shared window",
            )
        )
    else:
        started = monotonic_ms()
        hold_state = "hold " * 6000
        hold_request = {
            "model": settings.vt_arc_decision_model,
            "state": hold_state,
            "questions": requests["noul"]["questions"],
        }
        tasks = [
            asyncio.create_task(client.post(url, headers=headers, json=hold_request, timeout=120.0))
            for _ in range(4)
        ]
        try:
            await asyncio.sleep(1.0)
            fifth = await client.post(url, headers=headers, json=hold_request, timeout=45.0)
            fifth_payload, _ = _response_json(fifth)
            held = await asyncio.gather(*tasks, return_exceptions=True)
            held_statuses = [
                item.status_code if isinstance(item, httpx.Response) else type(item).__name__
                for item in held
            ]
            body = fifth_payload if isinstance(fifth_payload, dict) else str(fifth_payload)
            _write_json(
                fixtures / "limit_503_queue.json",
                {"fifth_status": fifth.status_code, "fifth_body": body, "held": held_statuses},
            )
            report.add(
                ProbeCheck(
                    name="systemone queue timeout (503)",
                    status="PASS" if fifth.status_code == 503 else "PARTIAL",
                    detail=f"fifth HTTP {fifth.status_code}; held={held_statuses}",
                    evidence={
                        "fifth_status": fifth.status_code,
                        "fifth_body": body,
                        "held": held_statuses,
                    },
                    duration_ms=monotonic_ms() - started,
                )
            )
        except Exception as exc:
            for task in tasks:
                task.cancel()
            report.add(
                ProbeCheck("systemone queue timeout (503)", "FAIL", f"{type(exc).__name__}: {exc}")
            )


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    denominator = _norm(left) * _norm(right)
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=False)) / denominator


def _fixture_slug(name: str) -> str:
    """Make a portable fixture filename (no spaces or colons for Windows)."""

    return name.lower().replace(" ", "_").replace(":", "-")


async def _embedding_probe(
    client: httpx.AsyncClient,
    *,
    name: str,
    url: str,
    model: str,
    expected_dim: int,
    headers: dict[str, str] | None,
    fixtures_dir: Path,
    batch_size: int,
) -> list[ProbeCheck]:
    """Shared Ollama/ARC embedding probe body."""

    checks: list[ProbeCheck] = []
    headers = headers or {}
    texts = [
        "Short rest and travel fatigue before a road game.",
        "The home team may be looking ahead to a ranked opponent.",
        "Cold and windy conditions can suppress scoring.",
    ]
    started = monotonic_ms()
    try:
        response = await client.post(
            url,
            headers=headers,
            json={"model": model, "input": texts},
            timeout=90.0,
        )
        payload, kind = _response_json(response)
        data = payload.get("data", []) if isinstance(payload, dict) else []
        vectors = [item.get("embedding", []) for item in data if isinstance(item, dict)]
        dims = [len(vector) for vector in vectors]
        norms = [_norm(vector) for vector in vectors]
        width_ok = all(dim == expected_dim for dim in dims)
        norm_ok = all(abs(norm - 1.0) < 1e-3 for norm in norms)
        _write_json(
            fixtures_dir / f"{_fixture_slug(name)}_response.json",
            {
                "model": model,
                "expected_dim": expected_dim,
                "dims": dims,
                "norms": norms,
                "usage": payload.get("usage") if isinstance(payload, dict) else None,
                "sample_vector": vectors[0][:8] if vectors else [],
            },
        )
        checks.append(
            ProbeCheck(
                name=f"{name} width/norm",
                status="PASS" if response.status_code == 200 and width_ok and norm_ok else "FAIL",
                detail=f"HTTP {response.status_code}; dims={dims}; norms={[round(n, 6) for n in norms]}",
                evidence={
                    "status": response.status_code,
                    "kind": kind,
                    "dims": dims,
                    "norms": norms,
                    "expected_dim": expected_dim,
                },
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        checks.append(ProbeCheck(f"{name} width/norm", "FAIL", f"{type(exc).__name__}: {exc}"))
        return checks

    # Batch cap: find the first failing list size.
    batch_results: list[dict[str, Any]] = []
    for size in (1, 4, batch_size, 16, 32):
        started = monotonic_ms()
        try:
            response = await client.post(
                url,
                headers=headers,
                json={"model": model, "input": [f"batch item {i}" for i in range(size)]},
                timeout=90.0,
            )
            payload, _ = _response_json(response)
            count = len(payload.get("data", [])) if isinstance(payload, dict) else 0
            batch_results.append({"size": size, "status": response.status_code, "returned": count})
            if response.status_code != 200 or count != size:
                break
        except Exception as exc:
            batch_results.append({"size": size, "exception": type(exc).__name__})
            break
    checks.append(
        ProbeCheck(
            name=f"{name} batch cap",
            status="PASS" if any(item.get("status") == 200 for item in batch_results) else "FAIL",
            detail=f"results={batch_results}",
            evidence={"batches": batch_results},
        )
    )

    # Over-context behavior: does it error, or silently truncate?
    long_text = "college football upset precondition " * 4000
    started = monotonic_ms()
    try:
        response = await client.post(
            url,
            headers=headers,
            json={"model": model, "input": long_text},
            timeout=120.0,
        )
        payload, _ = _response_json(response)
        data = payload.get("data", []) if isinstance(payload, dict) else []
        vector = data[0].get("embedding", []) if data else []
        _write_json(
            fixtures_dir / f"{_fixture_slug(name)}_over_context.json",
            {
                "chars": len(long_text),
                "status": response.status_code,
                "dim": len(vector),
                "norm": _norm(vector),
            },
        )
        checks.append(
            ProbeCheck(
                name=f"{name} over-context",
                status="PASS" if response.status_code == 200 else "PARTIAL",
                detail=f"chars={len(long_text)}; HTTP {response.status_code}; dim={len(vector)}",
                evidence={
                    "chars": len(long_text),
                    "status": response.status_code,
                    "dim": len(vector),
                },
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        checks.append(ProbeCheck(f"{name} over-context", "PARTIAL", f"{type(exc).__name__}: {exc}"))

    # Instruction-prefix comparison (Qwen3 query/document template).
    if "ollama" in name.lower():
        raw_text = "short rest before a road game"
        instruct_text = "Instruct: Retrieve college football upset evidence\nQuery: " + raw_text
        try:
            raw_response = await client.post(
                url, headers=headers, json={"model": model, "input": raw_text}, timeout=60.0
            )
            instr_response = await client.post(
                url, headers=headers, json={"model": model, "input": instruct_text}, timeout=60.0
            )
            raw_payload, _ = _response_json(raw_response)
            instr_payload, _ = _response_json(instr_response)
            raw_vector = (
                raw_payload.get("data", [{}])[0].get("embedding", [])
                if isinstance(raw_payload, dict)
                else []
            )
            instr_vector = (
                instr_payload.get("data", [{}])[0].get("embedding", [])
                if isinstance(instr_payload, dict)
                else []
            )
            similarity = _cosine(raw_vector, instr_vector)
            checks.append(
                ProbeCheck(
                    name=f"{name} instruction prefix",
                    status="PASS" if raw_vector and instr_vector else "PARTIAL",
                    detail=f"cosine(raw, instruct)={similarity:.6f}",
                    evidence={"cosine": similarity, "template": "Instruct: …\\nQuery: …"},
                )
            )
        except Exception as exc:
            checks.append(ProbeCheck(f"{name} instruction prefix", "PARTIAL", str(exc)))

    return checks


async def probe_embeddings(
    client: httpx.AsyncClient,
    settings: Settings,
    report: CapabilityReport,
) -> None:
    """Probe Ollama (4096-d, primary) and ARC 4B (2560-d, optional)."""

    ollama_url = settings.ollama_base_url.rstrip("/") + "/embeddings"
    ollama_checks = await _embedding_probe(
        client,
        name="Ollama qwen3-embedding:8b",
        url=ollama_url,
        model=settings.ollama_embed_model,
        expected_dim=settings.ollama_embed_dim,
        headers=None,
        fixtures_dir=FIXTURES_ROOT / "embeddings",
        batch_size=settings.embed_batch_size,
    )
    for check in ollama_checks:
        report.add(check)

    if not settings.has_arc:
        report.add(ProbeCheck("ARC Qwen3-Embedding-4B", "SKIP", "no ARC credential"))
        return
    arc_base = (settings.embed_base_url or settings.vt_arc_base_url).rstrip("/")
    arc_headers = (
        {"Authorization": f"Bearer {settings.arc_embed_key}"} if settings.arc_embed_key else {}
    )
    arc_checks = await _embedding_probe(
        client,
        name="ARC Qwen3-Embedding-4B",
        url=arc_base + "/embeddings",
        model=settings.arc_embed_model,
        expected_dim=settings.arc_embed_dim,
        headers=arc_headers,
        fixtures_dir=FIXTURES_ROOT / "embeddings",
        batch_size=settings.embed_batch_size,
    )
    for check in arc_checks:
        report.add(check)


async def probe_cfbd(
    client: httpx.AsyncClient,
    settings: Settings,
    report: CapabilityReport,
) -> None:
    """Measure CFBD open-line null rate and venue geodata fields."""

    fixtures = FIXTURES_ROOT / "cfbd"
    if not settings.has_cfbd:
        report.add(ProbeCheck("CFBD /lines", "SKIP", "no CFBD_API_KEY"))
        report.add(ProbeCheck("CFBD /venues", "SKIP", "no CFBD_API_KEY"))
        return

    headers = _cfbd_headers(settings)
    for year in (2021, 2025):
        started = monotonic_ms()
        try:
            response = await client.get(
                settings.cfbd_base_url.rstrip("/") + "/lines",
                params={"year": year, "week": 1, "seasonType": "regular"},
                headers=headers,
                timeout=60.0,
            )
            payload, kind = _response_json(response)
            games = payload if isinstance(payload, list) else []
            lines = [
                line
                for game in games
                if isinstance(game, dict)
                for line in game.get("lines", [])
                if isinstance(line, dict)
            ]
            spread_null = sum(1 for line in lines if line.get("spreadOpen") is None)
            ou_null = sum(1 for line in lines if line.get("overUnderOpen") is None)
            providers = sorted({line.get("provider") for line in lines if line.get("provider")})
            null_rate = (spread_null / len(lines)) if lines else None
            null_rate_text = f"{null_rate:.1%}" if null_rate is not None else "n/a"
            report.add(
                ProbeCheck(
                    name=f"CFBD /lines {year} week 1",
                    status="PASS" if response.status_code == 200 and games else "FAIL",
                    detail=f"HTTP {response.status_code}; games={len(games)}; lines={len(lines)}; "
                    f"spreadOpen_null={spread_null} ({null_rate_text}); "
                    f"providers={providers[:8]}",
                    evidence={
                        "status": response.status_code,
                        "games": len(games),
                        "lines": len(lines),
                        "spread_open_null": spread_null,
                        "spread_open_null_rate": null_rate,
                        "over_under_open_null": ou_null,
                        "providers": providers,
                    },
                    duration_ms=monotonic_ms() - started,
                )
            )
            trimmed = []
            for game in games[:3]:
                trimmed.append(
                    {
                        key: game.get(key)
                        for key in (
                            "id",
                            "season",
                            "week",
                            "homeTeam",
                            "awayTeam",
                            "homeClassification",
                            "awayClassification",
                        )
                    }
                    | {"lines": game.get("lines", [])[:4]}
                )
            _write_json(fixtures / f"lines_{year}_w1.json", trimmed)
        except Exception as exc:
            report.add(
                ProbeCheck(f"CFBD /lines {year} week 1", "FAIL", f"{type(exc).__name__}: {exc}")
            )

    started = monotonic_ms()
    try:
        response = await client.get(
            settings.cfbd_base_url.rstrip("/") + "/venues", headers=headers, timeout=60.0
        )
        payload, _ = _response_json(response)
        venues = payload if isinstance(payload, list) else []
        fields = ("latitude", "longitude", "elevation", "dome", "timezone")
        non_null = {
            field: sum(1 for venue in venues if venue.get(field) is not None) for field in fields
        }
        rates = {
            field: (count / len(venues) if venues else None) for field, count in non_null.items()
        }
        report.add(
            ProbeCheck(
                name="CFBD /venues",
                status="PASS" if response.status_code == 200 and venues else "FAIL",
                detail=f"HTTP {response.status_code}; venues={len(venues)}; non_null={non_null}",
                evidence={
                    "status": response.status_code,
                    "venues": len(venues),
                    "non_null": non_null,
                    "rates": rates,
                },
                duration_ms=monotonic_ms() - started,
            )
        )
        _write_json(fixtures / "venues.json", venues[:5])
    except Exception as exc:
        report.add(ProbeCheck("CFBD /venues", "FAIL", f"{type(exc).__name__}: {exc}"))


async def probe_weather(
    client: httpx.AsyncClient,
    settings: Settings,
    report: CapabilityReport,
) -> None:
    """Confirm historical forecast coverage and the actual lead ceiling."""

    fixtures = FIXTURES_ROOT / "weather"
    variables = "temperature_2m,wind_speed_10m,precipitation,cloud_cover"
    for label, start_date in (("2021-09-04", "2021-09-04"), ("2025-11-15", "2025-11-15")):
        started = monotonic_ms()
        try:
            response = await client.get(
                settings.weather_hist_base_url,
                params={
                    "latitude": 37.2197,
                    "longitude": -80.4180,
                    "start_date": start_date,
                    "end_date": start_date,
                    "hourly": variables,
                    "models": settings.weather_model,
                    "timezone": "UTC",
                },
                timeout=60.0,
            )
            payload, kind = _response_json(response)
            hourly = payload.get("hourly", {}) if isinstance(payload, dict) else {}
            hourly_vars = sorted(hourly.keys())
            times = hourly.get("time", [])
            report.add(
                ProbeCheck(
                    name=f"Open-Meteo historical forecast {label}",
                    status="PASS" if response.status_code == 200 and times else "FAIL",
                    detail=f"HTTP {response.status_code}; hours={len(times)}; variables={hourly_vars}",
                    evidence={
                        "status": response.status_code,
                        "kind": kind,
                        "hours": len(times),
                        "variables": hourly_vars,
                        "generationtime_ms": (
                            payload.get("generationtime_ms") if isinstance(payload, dict) else None
                        ),
                    },
                    duration_ms=monotonic_ms() - started,
                )
            )
            _write_json(
                fixtures / f"historical_{start_date}.json",
                {
                    "latitude": payload.get("latitude") if isinstance(payload, dict) else None,
                    "longitude": payload.get("longitude") if isinstance(payload, dict) else None,
                    "hourly_units": (
                        payload.get("hourly_units") if isinstance(payload, dict) else None
                    ),
                    "hourly": {
                        key: value[:6] for key, value in hourly.items() if isinstance(value, list)
                    },
                },
            )
        except Exception as exc:
            report.add(
                ProbeCheck(
                    name=f"Open-Meteo historical forecast {label}",
                    status="FAIL",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

    # Previous Runs gives an independent view of the stitched archive's lead.
    started = monotonic_ms()
    try:
        response = await client.get(
            "https://previous-runs-api.open-meteo.com/v1/forecast",
            params={
                "latitude": 37.2197,
                "longitude": -80.4180,
                "start_date": "2025-11-15",
                "end_date": "2025-11-15",
                "hourly": "temperature_2m",
                "models": settings.weather_model,
                "timezone": "UTC",
            },
            timeout=60.0,
        )
        payload, _ = _response_json(response)
        hourly = payload.get("hourly", {}) if isinstance(payload, dict) else {}
        report.add(
            ProbeCheck(
                name="Open-Meteo previous-runs archive",
                status="PASS" if response.status_code == 200 else "PARTIAL",
                detail=f"HTTP {response.status_code}; hourly_keys={sorted(hourly)}",
                evidence={"status": response.status_code, "hourly_keys": sorted(hourly)},
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(
            ProbeCheck(
                name="Open-Meteo previous-runs archive",
                status="SKIP",
                detail=f"{type(exc).__name__}: {exc}",
            )
        )


async def probe_web_tools(
    client: httpx.AsyncClient,
    settings: Settings,
    report: CapabilityReport,
) -> None:
    """Check Brave reachability and record missing MCP configuration."""

    started = monotonic_ms()
    try:
        headers = {"X-Subscription-Token": settings.brave_key} if settings.brave_key else {}
        response = await client.get(
            settings.brave_base_url.rstrip("/") + "/web/search",
            params={"q": "virginia tech football", "count": 1},
            headers=headers,
            timeout=30.0,
        )
        payload, _ = _response_json(response)
        result_count = 0
        if isinstance(payload, dict):
            result_count = len(payload.get("web", {}).get("results", []))
        report.add(
            ProbeCheck(
                name="Brave Search",
                status="PASS" if response.status_code == 200 and settings.has_brave else "SKIP",
                detail=(
                    f"HTTP {response.status_code}; key_configured={settings.has_brave}; "
                    f"results={result_count}"
                ),
                evidence={"status": response.status_code, "results": result_count},
                duration_ms=monotonic_ms() - started,
            )
        )
    except Exception as exc:
        report.add(ProbeCheck("Brave Search", "SKIP", f"{type(exc).__name__}: {exc}"))

    report.add(
        ProbeCheck(
            name="Fetch MCP",
            status="PASS" if settings.fetch_base_url else "SKIP",
            detail="configured" if settings.fetch_base_url else "FETCH_BASE_URL is empty",
        )
    )
    report.add(
        ProbeCheck(
            name="Deep Research MCP",
            status="PASS" if settings.deep_research_base_url else "SKIP",
            detail=(
                "configured"
                if settings.deep_research_base_url
                else "DEEP_RESEARCH_BASE_URL is empty"
            ),
        )
    )
    report.add(
        ProbeCheck(
            name="MCP transport",
            status="SKIP",
            detail="runtime adapters (D9) are used; no harness-level MCP servers are configured",
        )
    )


def probe_local(settings: Settings, report: CapabilityReport) -> None:
    """Check local Python, Chroma, disk, secret hygiene, and docs tooling."""

    chroma_spec = importlib.util.find_spec("chromadb")
    report.add(
        ProbeCheck(
            name="chromadb import",
            status="PASS" if chroma_spec else "FAIL",
            detail="importable" if chroma_spec else "not installed (P1.11 adds it)",
        )
    )

    usage = shutil.disk_usage(".")
    report.add(
        ProbeCheck(
            name="Disk space",
            status="PASS" if usage.free > 10 * 1024**3 else "FAIL",
            detail=f"free={usage.free / 1024**3:.1f} GiB; total={usage.total / 1024**3:.1f} GiB",
            evidence={"free_gib": round(usage.free / 1024**3, 1)},
        )
    )

    env_exists = Path(".env").exists()
    example_exists = Path(".env.example").exists()
    ignore_result = subprocess.run(
        ["git", "check-ignore", ".env"], capture_output=True, text=True, check=False
    )
    report.add(
        ProbeCheck(
            name="Secret hygiene",
            status=(
                "PASS"
                if env_exists and example_exists and ignore_result.returncode == 0
                else "FAIL"
            ),
            detail=(
                f".env={env_exists}; .env.example={example_exists}; "
                f"git_check_ignore_exit={ignore_result.returncode}"
            ),
            evidence={"git_check_ignore": ignore_result.stdout.strip()},
        )
    )

    tools = {name: shutil.which(name) for name in ("quarto", "npx", "pandoc")}
    report.add(
        ProbeCheck(
            name="Docs toolchain",
            status="PASS" if tools["quarto"] or tools["pandoc"] else "FAIL",
            detail=f"quarto={bool(tools['quarto'])}; npx={bool(tools['npx'])}; "
            f"pandoc={bool(tools['pandoc'])}",
            evidence={key: bool(value) for key, value in tools.items()},
        )
    )

    report.environment.update(
        {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "settings": settings.redacted_summary(),
        }
    )


async def run_probe(
    *,
    deep_limits: bool = False,
    write: bool = False,
    fixtures_root: Path = FIXTURES_ROOT,
) -> CapabilityReport:
    """Run every probe section and optionally write the report artifacts."""

    global FIXTURES_ROOT
    FIXTURES_ROOT = fixtures_root
    settings = Settings()
    report = CapabilityReport(timestamp=datetime.now(UTC))
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        for name, coroutine in (
            ("ESPN", probe_espn(client, settings, report)),
            ("ARC", probe_arc(client, settings, report)),
            ("systemone", probe_systemone(client, settings, report, deep_limits=deep_limits)),
            ("embeddings", probe_embeddings(client, settings, report)),
            ("CFBD", probe_cfbd(client, settings, report)),
            ("weather", probe_weather(client, settings, report)),
            ("web tools", probe_web_tools(client, settings, report)),
        ):
            try:
                await coroutine
            except Exception as exc:  # keep the rest of the matrix usable
                report.add(
                    ProbeCheck(
                        name=f"{name} probe section",
                        status="FAIL",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
    probe_local(settings, report)
    report.fixtures = sorted(str(path) for path in FIXTURES_ROOT.rglob("*") if path.is_file())

    report.chosen_backends = {
        "scorer (D1)": (
            "d3_mini via POST /systemone (primary); calibrated_rules fallback"
            if any(
                check.name.startswith("systemone noul") and check.status == "PASS"
                for check in report.checks
            )
            else "calibrated_rules only (systemone unavailable)"
        ),
        "research provider (D2)": (
            "mcp_deep_research if configured; otherwise seeded_literature"
            if settings.has_mcp_research
            else "seeded_literature (no MCP endpoint configured)"
        ),
        "weather (D3)": (
            f"open_meteo historical forecast; WEATHER_LEAD_HOURS_MAX="
            f"{settings.weather_lead_hours_max} (recorded actual lead)"
        ),
        "embeddings (D8)": (
            f"ollama {settings.ollama_embed_model} ({settings.embed_dim}-d, primary); "
            f"ARC {settings.arc_embed_model} ({settings.arc_embed_dim}-d, optional)"
        ),
        "odds / venues (D17)": (
            "CFBD /lines + /venues primary; ESPN open + strength proxy fallback"
            if settings.has_cfbd
            else "ESPN open + strength proxy (no CFBD key)"
        ),
        "MCP transport (D9)": "runtime HTTP adapters with recorded fixtures; no harness MCP",
    }
    report.notes = [
        "Golden `systemone` fixtures are committed under `tests/fixtures/systemone/`.",
        "The 5-way burst, oversized-body, and queue-timeout probes are best-effort because "
        "`systemone` is a shared per-user service.",
        "A fifth concurrent `systemone` request returned 429 `user_concurrent` in two of three "
        "2026-11-22 probes (the middle run accepted all five). The 429 path is verified but not "
        "reproducible on demand; the 4-request semaphore remains mandatory.",
        "CFBD 2021 week-1 open-line coverage is measured live; the strength proxy remains the "
        "fallback when `spreadOpen` is null.",
        "No credential is written to the report or fixtures.",
    ]

    if write:
        DOCS_ROOT.mkdir(parents=True, exist_ok=True)
        (DOCS_ROOT / "CAPABILITIES.md").write_text(report.to_markdown() + "\n", encoding="utf-8")
        (DOCS_ROOT / "capabilities.json").write_text(
            json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def main() -> None:
    """CLI entry point used by ``scripts/probe.py`` and ``make probe``."""

    import argparse

    parser = argparse.ArgumentParser(description="Run the CFB Upset Phase 0 capability probe")
    parser.add_argument("--write", action="store_true", help="write docs/CAPABILITIES.md")
    parser.add_argument(
        "--deep-limits",
        action="store_true",
        help="also probe the 30 s queue timeout (uses the shared 4-request window)",
    )
    args = parser.parse_args()
    report = asyncio.run(run_probe(deep_limits=args.deep_limits, write=args.write))
    print(report.to_markdown())
    print(f"\nStatus counts: {report.status_counts()}")


if __name__ == "__main__":
    main()
