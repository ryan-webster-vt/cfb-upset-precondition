"""Opt-in live smoke tests. Never run unless ``RUN_LIVE=1``."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from cfb_upset.adapters.cfbd import CfbdAdapter
from cfb_upset.adapters.deep_research import DeepResearchAdapter
from cfb_upset.adapters.embeddings import EmbeddingsClient
from cfb_upset.adapters.espn import EspnAdapter
from cfb_upset.adapters.fetch import FetchAdapter
from cfb_upset.adapters.geocode import GeocodeAdapter
from cfb_upset.adapters.llm import LlmClient
from cfb_upset.adapters.search import SearchAdapter
from cfb_upset.adapters.weather import WeatherAdapter
from cfb_upset.config import get_settings
from cfb_upset.contracts import ResearchBrief, StrictModel
from cfb_upset.store.evidence import EvidenceStore

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE") != "1",
        reason="set RUN_LIVE=1 to exercise live providers",
    ),
]


class OkModel(StrictModel):
    ok: bool


async def test_espn_scoreboard_live() -> None:
    adapter = EspnAdapter()
    try:
        records = await adapter.fetch_scoreboard(dates="20251115")
    finally:
        await adapter.aclose()
    assert records
    assert all(record.source == "espn" for record in records)


async def test_cfbd_venues_live() -> None:
    settings = get_settings()
    if not settings.has_cfbd:
        pytest.skip("CFBD_API_KEY is not configured")
    adapter = CfbdAdapter()
    venues = await adapter.fetch_venues()
    assert venues


async def test_weather_historical_live() -> None:
    adapter = WeatherAdapter()
    kickoff = datetime(2025, 11, 15, 20, 0, tzinfo=UTC)
    weather = await adapter.fetch_historical(lat=37.2296, lon=-80.4139, kickoff=kickoff)
    assert weather.source == "open_meteo_historical"
    assert weather.lead_hours is not None and weather.lead_hours <= 6


async def test_geocode_live() -> None:
    adapter = GeocodeAdapter()
    points = await adapter.geocode("Blacksburg")
    assert points


async def test_arc_chat_live() -> None:
    settings = get_settings()
    if not settings.has_arc:
        pytest.skip("VT ARC credentials are not configured")
    client = LlmClient()
    result = await client.chat_json(
        system=None,
        user='Return only this JSON object: {"ok": true}',
        response_model=OkModel,
        max_tokens=64,
    )
    assert result.ok is True
    assert client.ledger.total_tokens > 0


async def test_brave_search_live() -> None:
    settings = get_settings()
    if not settings.has_brave:
        pytest.skip("BRAVE_API_KEY is not configured")
    adapter = SearchAdapter()
    hits = await adapter.search("Virginia Tech football upset", count=3)
    assert hits


async def test_fetch_live(tmp_path) -> None:
    adapter = FetchAdapter(evidence_store=EvidenceStore(tmp_path / "evidence"))
    page = await adapter.fetch("https://www.espn.com/college-football/")
    assert page.status_code == 200
    assert page.text


async def test_deep_research_mcp_live() -> None:
    settings = get_settings()
    endpoint = settings.deep_research_base_url or settings.fetch_base_url
    if not endpoint:
        pytest.skip("no MCP Deep Research endpoint is configured")
    adapter = DeepResearchAdapter(provider="mcp", endpoint=endpoint)
    brief = ResearchBrief(
        candidate_key="live-smoke",
        title="Live smoke",
        definition="Adapter reachability only.",
        query="Return one research report object for candidate_key live-smoke.",
    )
    report = await adapter.research(brief)
    assert report.candidate_key == brief.candidate_key


async def test_embeddings_live() -> None:
    settings = get_settings()
    if os.environ.get("RUN_LIVE_EMBED") != "1":
        pytest.skip("set RUN_LIVE_EMBED=1 to embed against a live backend")
    client = EmbeddingsClient(backend=settings.embed_backend)
    result = await client.embed_query("short rest upset risk")
    assert result.count == 1
    assert result.vectors[0]
