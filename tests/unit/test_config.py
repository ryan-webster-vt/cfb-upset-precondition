"""Settings: defaults, aliases, validation, redaction, and local directories."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from cfb_upset.config import Settings, get_settings
from cfb_upset.errors import ConfigError


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults() -> None:
    settings = make_settings()
    assert settings.vt_arc_base_url == "https://llm-api.arc.vt.edu/api/v1"
    assert settings.vt_arc_decision_endpoint == "/systemone"
    assert settings.vt_arc_decision_model == "decision.vllm-sr/d3-mini"
    assert settings.systemone_max_concurrency == 4
    assert settings.embed_backend == "ollama"
    assert settings.embed_dim == 4096
    assert settings.weather_lead_hours_max == 6
    assert settings.demo_mode == "live"


def test_openai_style_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_AI_API_KEY", "alias-key")
    monkeypatch.setenv("OPEN_AI_ENDPOINT", "https://arc.example/api/v1")
    settings = make_settings()

    assert settings.arc_key == "alias-key"
    assert settings.vt_arc_base_url == "https://arc.example/api/v1"
    assert settings.has_arc is True


def test_csv_list_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_DOMAINS", "espn.com, cbssports.com ,si.com")
    monkeypatch.setenv("CFBD_LINE_PROVIDERS", "consensus,DraftKings")
    settings = make_settings()

    assert settings.allowed_domains == ["espn.com", "cbssports.com", "si.com"]
    assert settings.cfbd_line_providers == ["consensus", "DraftKings"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scorer_backend", "magic"),
        ("embed_backend", "other"),
        ("llm_mode", "sometimes"),
        ("demo_mode", "staging"),
    ],
)
def test_enum_like_settings_are_validated(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_concurrency_cap_cannot_exceed_provider_limit() -> None:
    with pytest.raises(ValidationError, match="between 1 and 4"):
        make_settings(systemone_max_concurrency=5)
    with pytest.raises(ValidationError, match="between 1 and 4"):
        make_settings(systemone_max_concurrency=0)


def test_worker_count_and_thresholds_are_validated() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        make_settings(worker_count=0)
    with pytest.raises(ValidationError, match="ALERT_THRESHOLD"):
        make_settings(alert_threshold=1.5)


def test_embed_dim_must_match_backend() -> None:
    with pytest.raises(ValidationError, match="does not match EMBED_BACKEND"):
        make_settings(embed_backend="arc", embed_dim=4096)
    assert make_settings(embed_backend="arc", embed_dim=2560).embed_dim == 2560
    assert make_settings(embed_backend="hashing", embed_dim=256).embed_dim == 256


def test_redacted_summary_never_leaks_secrets() -> None:
    settings = make_settings(
        vt_arc_api_key="arc-secret-value",
        cfbd_api_key="cfbd-secret-value",
        brave_api_key="brave-secret-value",
    )
    summary = settings.redacted_summary()

    assert summary["vt_arc_api_key"] == "***"
    assert summary["cfbd_configured"] is True
    assert summary["brave_configured"] is True
    rendered = str(summary)
    assert "arc-secret-value" not in rendered
    assert "cfbd-secret-value" not in rendered
    assert "brave-secret-value" not in rendered


def test_secret_accessors_handle_absent_keys() -> None:
    settings = make_settings()
    assert settings.arc_key is None
    assert settings.cfbd_key is None
    assert settings.brave_key is None
    assert settings.has_arc is False
    assert settings.has_cfbd is False
    assert settings.has_brave is False
    assert settings.has_mcp_research is False


def test_arc_embed_key_falls_back_to_chat_credential() -> None:
    settings = make_settings(vt_arc_api_key="chat-key")
    assert settings.arc_embed_key == "chat-key"
    settings = make_settings(vt_arc_api_key="chat-key", embed_api_key="embed-key")
    assert settings.arc_embed_key == "embed-key"


def test_mcp_research_detection() -> None:
    assert make_settings(fetch_base_url="http://fetch").has_mcp_research is True
    assert make_settings(deep_research_base_url="http://research").has_mcp_research is True


def test_ensure_runtime_dirs(tmp_path: Path) -> None:
    settings = make_settings(
        chroma_path=str(tmp_path / "chroma"),
        cache_path=str(tmp_path / "cache"),
        evidence_path=str(tmp_path / "evidence"),
        trace_path=str(tmp_path / "traces"),
        sqlite_path=str(tmp_path / "db" / "cfb.db"),
    )
    settings.ensure_runtime_dirs()

    for name in ("chroma", "cache", "evidence", "traces", "db"):
        assert (tmp_path / name).is_dir()


def test_get_settings_translates_validation_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr(Settings, "__init__", lambda self, **kwargs: _raise_validation())
    with pytest.raises(ConfigError, match="Invalid configuration"):
        get_settings()
    get_settings.cache_clear()


def _raise_validation() -> None:
    raise ValueError("broken settings")
