"""Web adapters: whitelisted search, safe fetch with snapshots, and geocoding."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfb_upset.adapters.fetch import FetchAdapter
from cfb_upset.adapters.geocode import GeocodeAdapter, haversine_km
from cfb_upset.adapters.search import SearchAdapter, domain_of, is_allowed
from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.errors import PermanentProviderError
from cfb_upset.ids import FrozenClock, sha256_hex
from cfb_upset.store.evidence import EvidenceStore

ALLOWED = ["espn.com", "sports-reference.com", "cbssports.com", "si.com"]
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)

SEARCH_PAYLOAD = {
    "web": {
        "results": [
            {
                "title": "Short rest and upset risk",
                "url": "https://www.espn.com/college-football/story/_/id/1",
                "description": "A study of short weeks.",
                "age": "2 days ago",
                "page_age": "2026-11-20T10:00:00Z",
            },
            {
                "title": "Unlisted source",
                "url": "https://example.com/blog/post",
                "description": "Not allowed.",
            },
            {
                "title": "Subdomain of an allowed domain",
                "url": "https://collegefootball.si.com/story",
                "age": "yesterday",
            },
            {"title": "No URL", "description": "dropped"},
        ]
    }
}

ARTICLE = """<!doctype html>
<html>
<head>
  <title>Why short rest matters</title>
  <meta property="article:published_time" content="2026-11-20T09:30:00Z">
  <script>window.secret = "do not index";</script>
  <style>.hidden { display: none; }</style>
</head>
<body>
  <article>
    <h1>Short rest</h1>
    <p>Teams on a short week allow more explosive plays.</p>
    <noscript>fallback text</noscript>
  </article>
</body>
</html>
"""


def test_search_drops_non_whitelisted_domains_and_parses_dates() -> None:
    adapter = SearchAdapter(FixtureTransport(), allowed_domains=ALLOWED)
    hits = adapter.parse(SEARCH_PAYLOAD)
    assert [hit.domain for hit in hits] == ["espn.com", "collegefootball.si.com"]
    assert hits[0].title == "Short rest and upset risk"
    assert hits[0].published_at == datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    assert hits[1].published_at is None


def test_search_allowed_domain_matching_requires_a_label_boundary() -> None:
    assert is_allowed("https://www.espn.com/x", ALLOWED)
    assert is_allowed("https://collegefootball.espn.com/x", ALLOWED)
    assert not is_allowed("https://notespn.com/x", ALLOWED)
    assert not is_allowed("https://espn.com.evil.example/x", ALLOWED)
    assert domain_of("https://www.espn.com/x") == "espn.com"


async def test_search_uses_fixture_transport_and_query_params() -> None:
    transport = FixtureTransport().add("/web/search", SEARCH_PAYLOAD)
    adapter = SearchAdapter(transport, base_url="https://search.example", allowed_domains=ALLOWED)
    hits = await adapter.search("short rest upset", count=3)
    assert len(hits) == 2
    url = transport.calls[0].url
    assert url.startswith("https://search.example/web/search?")
    assert "q=short+rest+upset" in url
    assert "count=3" in url


async def test_fetch_extracts_text_and_writes_verifiable_snapshot(tmp_path: Path) -> None:
    transport = FixtureTransport().add("espn.com", ARTICLE)
    evidence = EvidenceStore(tmp_path / "evidence")
    adapter = FetchAdapter(
        transport, allowed_domains=ALLOWED, evidence_store=evidence, clock=FrozenClock(NOW)
    )
    page = await adapter.fetch("https://www.espn.com/college-football/story/1")

    assert page.title == "Why short rest matters"
    assert page.domain == "espn.com"
    assert "short week allow more explosive plays" in page.text
    assert "do not index" not in page.text
    assert "fallback text" not in page.text
    assert page.published_at == datetime(2026, 11, 20, 9, 30, tzinfo=UTC)
    assert page.fetched_at == NOW
    assert page.content_hash == sha256_hex(ARTICLE.encode())
    assert page.evidence_id is not None
    assert page.snapshot_path is not None

    snapshot = evidence.write(ARTICLE, kind="article", fetched_at=NOW)
    assert snapshot.deduplicated is True
    assert evidence.verify(page.snapshot_path, page.content_hash)


async def test_fetch_truncates_text_but_hashes_full_bytes() -> None:
    long_article = "<html><body>" + ("word " * 100) + "</body></html>"
    adapter = FetchAdapter(
        FixtureTransport().add("espn.com", long_article),
        allowed_domains=ALLOWED,
        max_chars=20,
        clock=FrozenClock(NOW),
    )
    page = await adapter.fetch("https://www.espn.com/long")
    assert page.truncated is True
    assert len(page.text) <= 20
    assert page.content_hash == sha256_hex(long_article.encode())


@pytest.mark.parametrize(
    "url",
    [
        "ftp://espn.com/story",
        "https://user:pass@espn.com/story",
        "https://localhost/story",
        "https://127.0.0.1/story",
        "https://10.0.0.5/story",
        "https://example.com/story",
    ],
)
async def test_fetch_refuses_unsafe_or_non_whitelisted_urls(url: str) -> None:
    transport = FixtureTransport()
    adapter = FetchAdapter(transport, allowed_domains=ALLOWED)
    with pytest.raises(PermanentProviderError):
        await adapter.fetch(url)
    assert transport.calls == []


async def test_fetch_maps_non_200_to_a_permanent_error() -> None:
    transport = FixtureTransport().add("espn.com", "gone", status_code=410)
    adapter = FetchAdapter(transport, allowed_domains=ALLOWED)
    with pytest.raises(PermanentProviderError) as excinfo:
        await adapter.fetch("https://www.espn.com/gone")
    assert excinfo.value.status_code == 410
    assert excinfo.value.provider == "fetch"


def test_geocode_parse_skips_incomplete_results() -> None:
    payload = {
        "results": [
            {
                "name": "Blacksburg",
                "latitude": 37.2296,
                "longitude": -80.4139,
                "country_code": "US",
                "admin1": "Virginia",
                "timezone": "America/New_York",
                "elevation": 633,
            },
            {"name": "No coordinates", "latitude": None, "longitude": -1},
            {"latitude": 1.0, "longitude": 2.0},
        ]
    }
    points = GeocodeAdapter.parse(payload)
    assert len(points) == 1
    assert points[0].name == "Blacksburg"
    assert points[0].elevation_m == pytest.approx(633.0)
    assert points[0].state == "Virginia"


async def test_geocode_uses_fixture_transport() -> None:
    payload = {"results": [{"name": "Blacksburg", "latitude": 37.2296, "longitude": -80.4139}]}
    transport = FixtureTransport().add("/v1/search", payload)
    adapter = GeocodeAdapter(transport, base_url="https://geo.example/v1/search")
    points = await adapter.geocode("Blacksburg")
    assert points[0].latitude == pytest.approx(37.2296)
    assert "name=Blacksburg" in transport.calls[0].url
    assert "countryCode=US" in transport.calls[0].url


def test_haversine_distance() -> None:
    assert haversine_km(37.0, -80.0, 37.0, -80.0) == pytest.approx(0.0)
    distance = haversine_km(34.0522, -118.2437, 40.7128, -74.0060)
    assert distance == pytest.approx(3936.0, rel=0.01)
