"""Application configuration.

Every tunable lives here; no other module reads ``os.environ`` directly. The
aliases below keep an existing OpenAI-style credential file working while the
rest of the code uses one canonical name.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cfb_upset.errors import ConfigError

# Measured widths from the 2026-11-22 live probes. The width is pinned per
# backend so a collection can never be queried with a different model's space.
_EMBED_DIMS = {"ollama": 4096, "arc": 2560, "hashing": 256}


class Settings(BaseSettings):
    """Typed, validated runtime settings loaded from ``.env`` and the process."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # --- VT ARC ---
    vt_arc_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("VT_ARC_API_KEY", "OPEN_AI_API_KEY"),
    )
    vt_arc_base_url: str = Field(
        default="https://llm-api.arc.vt.edu/api/v1",
        validation_alias=AliasChoices("VT_ARC_BASE_URL", "OPEN_AI_ENDPOINT"),
    )
    vt_arc_model: str = "GLM-5.3"
    vt_arc_extractor_model: str = "GLM-5.3"
    vt_arc_adjudicator_model: str = "gpt-oss-120b"
    vt_arc_decision_endpoint: str = "/systemone"
    vt_arc_decision_model: str = "decision.vllm-sr/d3-mini"

    # --- Scorer / decision model ---
    scorer_backend: str = "auto"
    systemone_max_concurrency: int = 4
    systemone_max_input_tokens: int = 8192
    systemone_max_request_bytes: int = 8_388_608
    systemone_queue_wait_s: int = 30
    systemone_score_timeout_s: int = 45
    systemone_max_questions_per_game: int = 2
    max_scored_games: int = 20
    confirm_threshold: float = 0.60
    drop_threshold: float = 0.40
    alert_threshold: float = 0.50

    # --- Research / web tools ---
    brave_api_key: SecretStr | None = None
    brave_base_url: str = "https://api.search.brave.com/res/v1"
    fetch_base_url: str = ""
    deep_research_base_url: str = ""
    research_provider: str = "auto"
    # Stored as CSV because pydantic-settings would otherwise require JSON for
    # list fields; the public properties below expose parsed lists.
    allowed_domains_csv: str = Field(
        default="espn.com,sports-reference.com,cbssports.com,si.com",
        validation_alias=AliasChoices("ALLOWED_DOMAINS"),
    )

    # --- Embeddings / vector store ---
    embed_backend: str = "ollama"
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "OLLAMA_ENDPOINT"),
    )
    ollama_embed_model: str = Field(
        default="qwen3-embedding:8b",
        validation_alias=AliasChoices("OLLAMA_EMBED_MODEL", "EMBED_MODEL"),
    )
    ollama_embed_dim: int = 4096
    embed_base_url: str = ""
    embed_api_key: SecretStr | None = None
    arc_embed_model: str = "Qwen3-Embedding-4B"
    arc_embed_dim: int = 2560
    embed_dim: int = 4096
    embed_max_input_tokens: int = 2048
    embed_batch_size: int = 8
    embed_max_concurrency: int = 2
    embed_instruction_template: str = ""
    chroma_path: str = "./data/chroma"

    # --- Data / storage ---
    sqlite_path: str = "./data/cfb.db"
    cache_path: str = "./data/cache"
    evidence_path: str = "./data/evidence"
    trace_path: str = "./data/traces"
    espn_api_base_url: str = (
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
    )
    espn_core_base_url: str = (
        "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
    )

    # --- Secondary structured data ---
    cfbd_api_key: SecretStr | None = None
    cfbd_base_url: str = "https://api.collegefootballdata.com"
    cfbd_line_providers_csv: str = Field(
        default="consensus,DraftKings,ESPN_BET",
        validation_alias=AliasChoices("CFBD_LINE_PROVIDERS"),
    )
    cfbd_max_concurrency: int = 2

    # --- Weather ---
    weather_backend: str = "open_meteo"
    weather_hist_base_url: str = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    weather_forecast_base_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_model: str = "gfs_seamless"
    weather_lead_hours_max: int = 6

    # --- Runtime ---
    worker_count: int = 2
    run_budget_seconds: int = 300
    max_games_per_run: int = 25
    max_fetches_per_game: int = 3
    max_pages_per_run: int = 75
    llm_mode: str = "required"
    require_approval: bool = True
    demo_mode: str = "live"
    log_level: str = "INFO"

    # --- Validators ---
    @field_validator("scorer_backend")
    @classmethod
    def _validate_scorer_backend(cls, value: str) -> str:
        allowed = {"auto", "d3_mini", "calibrated_rules"}
        if value not in allowed:
            raise ValueError(f"SCORER_BACKEND must be one of {sorted(allowed)}")
        return value

    @field_validator("embed_backend")
    @classmethod
    def _validate_embed_backend(cls, value: str) -> str:
        if value not in _EMBED_DIMS:
            raise ValueError(f"EMBED_BACKEND must be one of {sorted(_EMBED_DIMS)}")
        return value

    @field_validator("llm_mode")
    @classmethod
    def _validate_llm_mode(cls, value: str) -> str:
        if value not in {"required", "off"}:
            raise ValueError("LLM_MODE must be 'required' or 'off'")
        return value

    @field_validator("demo_mode")
    @classmethod
    def _validate_demo_mode(cls, value: str) -> str:
        if value not in {"live", "offline"}:
            raise ValueError("DEMO_MODE must be 'live' or 'offline'")
        return value

    @model_validator(mode="after")
    def _validate_operating_envelope(self) -> Settings:
        # The owner-provided systemone cap is a hard constant, not a tuning knob.
        if not 1 <= self.systemone_max_concurrency <= 4:
            raise ValueError(
                "SYSTEMONE_MAX_CONCURRENCY must be between 1 and 4 "
                "(the provider rejects a fifth concurrent request)"
            )
        if self.worker_count < 1:
            raise ValueError("WORKER_COUNT must be at least 1")
        for name in ("confirm_threshold", "drop_threshold", "alert_threshold"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name.upper()} must be in [0, 1]")

        expected_dim = _EMBED_DIMS[self.embed_backend]
        if self.embed_dim != expected_dim:
            raise ValueError(
                f"EMBED_DIM={self.embed_dim} does not match EMBED_BACKEND="
                f"{self.embed_backend!r} (expected {expected_dim}). "
                "A collection must never be queried with a different vector space."
            )
        return self

    # --- Convenience accessors ---
    @property
    def allowed_domains(self) -> list[str]:
        return [part.strip() for part in self.allowed_domains_csv.split(",") if part.strip()]

    @property
    def cfbd_line_providers(self) -> list[str]:
        return [part.strip() for part in self.cfbd_line_providers_csv.split(",") if part.strip()]

    @property
    def arc_key(self) -> str | None:
        return self.vt_arc_api_key.get_secret_value() if self.vt_arc_api_key else None

    @property
    def cfbd_key(self) -> str | None:
        return self.cfbd_api_key.get_secret_value() if self.cfbd_api_key else None

    @property
    def brave_key(self) -> str | None:
        return self.brave_api_key.get_secret_value() if self.brave_api_key else None

    @property
    def arc_embed_key(self) -> str | None:
        if self.embed_api_key:
            return self.embed_api_key.get_secret_value()
        return self.arc_key

    @property
    def has_arc(self) -> bool:
        return bool(self.arc_key)

    @property
    def has_cfbd(self) -> bool:
        return bool(self.cfbd_key)

    @property
    def has_brave(self) -> bool:
        return bool(self.brave_key)

    @property
    def has_mcp_research(self) -> bool:
        return bool(self.fetch_base_url or self.deep_research_base_url)

    def redacted_summary(self) -> dict[str, object]:
        """Return a log-safe view: keys masked, secrets never included."""

        def mask(value: str | None) -> str:
            return "***" if value else ""

        return {
            "vt_arc_base_url": self.vt_arc_base_url,
            "vt_arc_api_key": mask(self.arc_key),
            "vt_arc_model": self.vt_arc_model,
            "vt_arc_decision_model": self.vt_arc_decision_model,
            "scorer_backend": self.scorer_backend,
            "systemone_max_concurrency": self.systemone_max_concurrency,
            "embed_backend": self.embed_backend,
            "ollama_base_url": self.ollama_base_url,
            "ollama_embed_model": self.ollama_embed_model,
            "embed_dim": self.embed_dim,
            "cfbd_configured": self.has_cfbd,
            "brave_configured": self.has_brave,
            "mcp_research_configured": self.has_mcp_research,
            "weather_backend": self.weather_backend,
            "weather_lead_hours_max": self.weather_lead_hours_max,
            "worker_count": self.worker_count,
            "llm_mode": self.llm_mode,
            "demo_mode": self.demo_mode,
            "log_level": self.log_level,
        }

    def ensure_runtime_dirs(self) -> None:
        """Create local artifact directories referenced by settings."""

        for raw in (self.chroma_path, self.cache_path, self.evidence_path, self.trace_path):
            Path(raw).expanduser().mkdir(parents=True, exist_ok=True)
        Path(self.sqlite_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process, translating validation errors."""

    try:
        return Settings()
    except Exception as exc:  # pydantic ValidationError -> typed startup error
        raise ConfigError(f"Invalid configuration: {exc}") from exc
