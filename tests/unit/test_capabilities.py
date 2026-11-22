"""Probe helpers: redaction, URL building, and fixture naming."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from cfb_upset.config import Settings
from cfb_upset.pipelines.capabilities import (
    CapabilityReport,
    ProbeCheck,
    _fixture_slug,
    _is_secret_key,
    _redact,
    _response_json,
    _short_json,
    _systemone_requests,
    _systemone_url,
)


def test_secret_key_predicate_does_not_mask_usage_counters() -> None:
    assert _is_secret_key("input_tokens") is False
    assert _is_secret_key("output_tokens") is False
    assert _is_secret_key("prompt_tokens") is False
    assert _is_secret_key("completion_tokens") is False
    assert _is_secret_key("token_ids") is False
    assert _is_secret_key("api_key") is True
    assert _is_secret_key("apiKey") is True
    assert _is_secret_key("Authorization") is True
    assert _is_secret_key("access-token") is True
    assert _is_secret_key("x-subscription-token") is True
    assert _is_secret_key("client_secret") is True
    assert _is_secret_key("cfbd_api_key") is True


def test_redact_masks_secrets_and_keeps_usage_numbers() -> None:
    payload = {
        "input_tokens": 134,
        "output_tokens": 0,
        "token_ids": [1, 2],
        "api_key": "should-hide",
        "Authorization": "Bearer should-hide",
        "nested": {"cfbd_api_key": "should-hide", "retry_after_s": 2},
        "items": list(range(10)),
    }

    cleaned = _redact(payload)

    assert cleaned["input_tokens"] == 134
    assert cleaned["output_tokens"] == 0
    assert cleaned["token_ids"] == [1, 2]
    assert cleaned["api_key"] == "***"
    assert cleaned["Authorization"] == "***"
    assert cleaned["nested"]["cfbd_api_key"] == "***"
    assert cleaned["nested"]["retry_after_s"] == 2
    assert cleaned["items"] == [0, 1, 2, 3, 4]


def test_short_json_truncates_long_payloads() -> None:
    text = _short_json({"value": "x" * 1000}, limit=40)
    assert len(text) <= 41
    assert text.endswith("…")


def test_response_json_handles_json_and_text() -> None:
    payload, kind = _response_json(httpx.Response(200, json={"ok": True}))
    assert payload == {"ok": True}
    assert kind == "json"

    payload, kind = _response_json(httpx.Response(502, text="bad gateway"))
    assert payload == "bad gateway"
    assert kind == "text"


def test_systemone_url_handles_relative_and_absolute_endpoints() -> None:
    relative = Settings(_env_file=None, vt_arc_base_url="https://arc.example/api/v1")
    assert _systemone_url(relative) == "https://arc.example/api/v1/systemone"

    absolute = Settings(
        _env_file=None,
        vt_arc_base_url="https://arc.example/api/v1",
        vt_arc_decision_endpoint="https://other.example/systemone",
    )
    assert _systemone_url(absolute) == "https://other.example/systemone"


def test_systemone_requests_cover_all_three_question_types() -> None:
    requests = _systemone_requests(Settings(_env_file=None))

    assert set(requests) == {"noul", "choice", "score"}
    assert requests["noul"]["questions"]["upset_likely"]["type"] == "noul"
    assert requests["choice"]["questions"]["confirm"]["criteria"]
    assert requests["score"]["questions"]["risk"]["criteria"]


def test_fixture_slug_is_portable() -> None:
    assert _fixture_slug("Ollama qwen3-embedding:8b") == "ollama_qwen3-embedding-8b"


def test_report_markdown_lists_checks_and_backends() -> None:
    report = CapabilityReport(timestamp=datetime(2026, 11, 22, tzinfo=UTC))
    report.add(ProbeCheck("thing", "PASS", "worked", {"input_tokens": 1}))
    report.chosen_backends = {"scorer": "d3_mini"}
    report.fixtures = ["tests/fixtures/x.json"]
    report.notes = ["note"]

    text = report.to_markdown()

    assert "| PASS | 1 |" in text
    assert "| thing | **PASS** | worked |" in text
    assert "**scorer:** d3_mini" in text
    assert "`tests/fixtures/x.json`" in text
    assert "- note" in text
    assert report.status_counts() == {"PASS": 1}
