"""Weather fixtures: conservative lead times and no observed/reanalysis weather."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cfb_upset.adapters.transport import FixtureTransport
from cfb_upset.adapters.weather import WeatherAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / "weather" / name).read_text())


def test_historical_parse_picks_latest_hour_at_or_before_kickoff() -> None:
    adapter = WeatherAdapter(FixtureTransport(), lead_hours_max=6)
    kickoff = datetime(2025, 11, 15, 3, 45, tzinfo=UTC)
    weather = adapter.parse_historical(
        load("historical_2025-11-15.json"), kickoff=kickoff, lead_hours=6
    )
    assert weather.temperature_c == pytest.approx(11.5)
    assert weather.wind_kph == pytest.approx(12.8)
    assert weather.precipitation_mm == pytest.approx(0.0)
    assert weather.condition == "clear"
    assert weather.source == "open_meteo_historical"
    assert weather.known_at == kickoff - timedelta(hours=6)
    assert weather.known_at < kickoff


def test_historical_parse_uses_first_hour_when_kickoff_precedes_all() -> None:
    adapter = WeatherAdapter(FixtureTransport())
    kickoff = datetime(2025, 11, 14, 22, 0, tzinfo=UTC)
    weather = adapter.parse_historical(
        load("historical_2025-11-15.json"), kickoff=kickoff, lead_hours=6
    )
    assert weather.temperature_c == pytest.approx(13.9)


def test_historical_parse_handles_empty_hourly_payload() -> None:
    adapter = WeatherAdapter(FixtureTransport())
    kickoff = datetime(2025, 11, 15, tzinfo=UTC)
    weather = adapter.parse_historical({}, kickoff=kickoff, lead_hours=6)
    assert weather.unavailable_reason == "no hourly forecast"
    assert weather.temperature_c is None
    assert weather.known_at == kickoff - timedelta(hours=6)


def test_condition_thresholds() -> None:
    adapter = WeatherAdapter(FixtureTransport())
    payload = {
        "hourly": {
            "time": ["2025-11-15T00:00"],
            "temperature_2m": [10],
            "wind_speed_10m": [5],
            "precipitation": [0.4],
            "cloud_cover": [95],
        }
    }
    kickoff = datetime(2025, 11, 15, 1, 0, tzinfo=UTC)
    assert adapter.parse_historical(payload, kickoff=kickoff, lead_hours=1).condition == (
        "precipitation"
    )
    payload["hourly"]["precipitation"] = [0.0]
    assert adapter.parse_historical(payload, kickoff=kickoff, lead_hours=1).condition == "cloudy"
    payload["hourly"]["cloud_cover"] = [55]
    assert adapter.parse_historical(payload, kickoff=kickoff, lead_hours=1).condition == (
        "partly_cloudy"
    )


async def test_fetch_historical_clamps_lead_to_six_hours() -> None:
    transport = FixtureTransport().add_json_file(
        "/v1/forecast", FIXTURES / "weather" / "historical_2021-09-04.json"
    )
    adapter = WeatherAdapter(transport, historical_base_url="https://weather.example/v1/forecast")
    kickoff = datetime(2021, 9, 4, 4, 0, tzinfo=UTC)
    weather = await adapter.fetch_historical(lat=37.2, lon=-80.4, kickoff=kickoff, lead_hours=30)
    assert weather.lead_hours == pytest.approx(6.0)
    assert weather.known_at == kickoff - timedelta(hours=6)
    assert weather.temperature_c == pytest.approx(15.3)
    url = transport.calls[0].url
    assert "models=gfs_seamless" in url
    assert "start_date=2021-09-04" in url
    assert "end_date=2021-09-04" in url


async def test_indoor_venue_short_circuits_without_a_request() -> None:
    transport = FixtureTransport()
    adapter = WeatherAdapter(transport)
    kickoff = datetime(2025, 11, 15, 20, 0, tzinfo=UTC)
    weather = await adapter.fetch_historical(lat=40.0, lon=-75.0, kickoff=kickoff, indoor=True)
    assert weather.unavailable_reason.startswith("indoor venue")
    assert weather.known_at == kickoff - timedelta(hours=adapter.lead_hours_max)
    assert transport.calls == []


async def test_forecast_stamps_known_at_at_fetch_time() -> None:
    transport = FixtureTransport().add_json_file(
        "/v1/forecast", FIXTURES / "weather" / "historical_2025-11-15.json"
    )
    adapter = WeatherAdapter(transport, forecast_base_url="https://forecast.example/v1/forecast")
    fetched_at = datetime(2025, 11, 10, 12, 0, tzinfo=UTC)
    kickoff = datetime(2025, 11, 15, 20, 0, tzinfo=UTC)
    weather = await adapter.fetch_forecast(lat=37.2, lon=-80.4, kickoff=kickoff, now=fetched_at)
    assert weather.source == "open_meteo_forecast"
    assert weather.known_at == fetched_at
    assert weather.lead_hours == pytest.approx(128.0)
    assert "forecast_days=7" in transport.calls[0].url


async def test_forecast_refuses_a_past_kickoff_and_indoor_venue() -> None:
    transport = FixtureTransport()
    adapter = WeatherAdapter(transport)
    fetched_at = datetime(2025, 11, 15, 21, 0, tzinfo=UTC)
    kickoff = datetime(2025, 11, 15, 20, 0, tzinfo=UTC)
    past = await adapter.fetch_forecast(lat=1.0, lon=2.0, kickoff=kickoff, now=fetched_at)
    assert past.unavailable_reason == "kickoff is not in the future"
    assert past.lead_hours == 0.0
    indoor = await adapter.fetch_forecast(
        lat=1.0, lon=2.0, kickoff=fetched_at + timedelta(hours=5), now=fetched_at, indoor=True
    )
    assert indoor.unavailable_reason.startswith("indoor venue")
    assert transport.calls == []
