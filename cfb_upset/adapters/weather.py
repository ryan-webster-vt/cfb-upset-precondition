"""Weather adapter over Open-Meteo forecast archives.

Historical runs use the archived forecast API (GFS, 2021+) and record the
effective lead as an explicit upper bound (the stitched archive does not expose
an issue time). Live runs use the forecast endpoint and stamp ``known_at`` at
fetch time. Observed/reanalysis weather is never admitted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.config import get_settings
from cfb_upset.contracts import WeatherInfo
from cfb_upset.ids import Clock, SystemClock


class WeatherAdapter:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        historical_base_url: str | None = None,
        forecast_base_url: str | None = None,
        clock: Clock | None = None,
        lead_hours_max: int | None = None,
    ) -> None:
        settings = get_settings()
        self.historical_base_url = (historical_base_url or settings.weather_hist_base_url).rstrip(
            "/"
        )
        self.forecast_base_url = (forecast_base_url or settings.weather_forecast_base_url).rstrip(
            "/"
        )
        self.clock = clock or SystemClock()
        self.lead_hours_max = lead_hours_max or settings.weather_lead_hours_max
        self._transport = transport
        self._owns_transport = transport is None

    def _transport_or_default(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(
                base_url=self.historical_base_url, provider="open_meteo"
            )
            self._owns_transport = True
        return self._transport

    async def fetch_historical(
        self,
        *,
        lat: float,
        lon: float,
        kickoff: datetime,
        lead_hours: float | None = None,
        indoor: bool = False,
    ) -> WeatherInfo:
        lead = min(float(lead_hours if lead_hours is not None else self.lead_hours_max), 6.0)
        known_at = kickoff - timedelta(hours=lead)
        if indoor:
            return WeatherInfo(
                source="open_meteo_historical",
                known_at=known_at,
                lead_hours=lead,
                unavailable_reason="indoor venue; weather is not modelled",
            )
        response = await self._transport_or_default().get(
            self.historical_base_url,
            params=_params(lat, lon, kickoff),
        )
        response.raise_for_status()
        return self.parse_historical(
            response.json(),
            kickoff=kickoff,
            lead_hours=lead,
            source="open_meteo_historical",
        )

    async def fetch_forecast(
        self,
        *,
        lat: float,
        lon: float,
        kickoff: datetime,
        indoor: bool = False,
        now: datetime | None = None,
    ) -> WeatherInfo:
        fetched_at = now or self.clock.now()
        lead = max(0.0, min(168.0, (kickoff - fetched_at).total_seconds() / 3600.0))
        if indoor:
            return WeatherInfo(
                source="open_meteo_forecast",
                known_at=fetched_at,
                lead_hours=lead,
                unavailable_reason="indoor venue; weather is not modelled",
            )
        if lead <= 0:
            return WeatherInfo(
                source="open_meteo_forecast",
                known_at=fetched_at,
                lead_hours=0.0,
                unavailable_reason="kickoff is not in the future",
            )
        response = await self._transport_or_default().get(
            self.forecast_base_url,
            params=_params(lat, lon, kickoff, forecast=True),
        )
        response.raise_for_status()
        parsed = self.parse_historical(
            response.json(),
            kickoff=kickoff,
            lead_hours=lead,
            source="open_meteo_forecast",
        )
        return parsed.model_copy(update={"known_at": fetched_at})

    def parse_historical(
        self,
        payload: dict[str, Any],
        *,
        kickoff: datetime,
        lead_hours: float,
        source: str = "open_meteo_historical",
    ) -> WeatherInfo:
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return WeatherInfo(
                source=source,
                known_at=kickoff - timedelta(hours=lead_hours),
                lead_hours=lead_hours,
                unavailable_reason="no hourly forecast",
            )
        index = _closest_index(times, kickoff)
        temperature = _at(hourly.get("temperature_2m"), index)
        wind = _at(hourly.get("wind_speed_10m"), index)
        precipitation = _at(hourly.get("precipitation"), index)
        cloud_cover = _at(hourly.get("cloud_cover"), index)
        return WeatherInfo(
            temperature_c=temperature,
            wind_kph=wind,
            precipitation_mm=precipitation,
            condition=_condition(precipitation, cloud_cover),
            source=source,
            known_at=kickoff - timedelta(hours=lead_hours),
            lead_hours=lead_hours,
        )


def _params(lat: float, lon: float, kickoff: datetime, *, forecast: bool = False) -> dict[str, Any]:
    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,precipitation,cloud_cover",
        "timezone": "UTC",
    }
    if forecast:
        params["forecast_days"] = 7
    else:
        day = kickoff.astimezone(UTC).date().isoformat()
        params["start_date"] = day
        params["end_date"] = day
        params["models"] = "gfs_seamless"
    return params


def _closest_index(times: list[str], kickoff: datetime) -> int:
    parsed: list[datetime] = []
    for value in times:
        try:
            item = datetime.fromisoformat(str(value))
        except ValueError:
            parsed.append(kickoff)
            continue
        parsed.append(item.replace(tzinfo=UTC) if item.tzinfo is None else item.astimezone(UTC))
    before = [index for index, item in enumerate(parsed) if item <= kickoff]
    if before:
        return max(before, key=lambda index: parsed[index])
    return min(range(len(parsed)), key=lambda index: abs((parsed[index] - kickoff).total_seconds()))


def _at(values: Any, index: int) -> float | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _condition(precipitation: float | None, cloud_cover: float | None) -> str | None:
    if precipitation is not None and precipitation > 0:
        return "precipitation"
    if cloud_cover is None:
        return None
    if cloud_cover >= 80:
        return "cloudy"
    if cloud_cover >= 40:
        return "partly_cloudy"
    return "clear"


__all__ = ["WeatherAdapter"]
