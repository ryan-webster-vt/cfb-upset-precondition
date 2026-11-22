"""Geocoding adapter (Open-Meteo geocoding) plus great-circle distance.

Venue latitude/longitude normally comes from CFBD. This adapter is the
fallback when a venue is missing coordinates or an article names a city.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from cfb_upset.adapters.transport import HttpTransport, Transport
from cfb_upset.ids import Clock, SystemClock

DEFAULT_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


@dataclass(frozen=True)
class GeoPoint:
    name: str
    latitude: float
    longitude: float
    country: str | None = None
    state: str | None = None
    timezone: str | None = None
    elevation_m: float | None = None


class GeocodeAdapter:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        base_url: str = DEFAULT_GEOCODE_URL,
        clock: Clock | None = None,
    ) -> None:
        self.base_url = base_url
        self.clock = clock or SystemClock()
        self._transport = transport
        self._owns_transport = transport is None

    def _transport_or_default(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(base_url=self.base_url, provider="geocode")
            self._owns_transport = True
        return self._transport

    async def geocode(
        self,
        name: str,
        *,
        count: int = 5,
        country_code: str | None = "US",
    ) -> list[GeoPoint]:
        params: dict[str, Any] = {"name": name, "count": count, "language": "en", "format": "json"}
        if country_code:
            params["countryCode"] = country_code
        response = await self._transport_or_default().get(self.base_url, params=params)
        response.raise_for_status()
        return self.parse(response.json())

    @staticmethod
    def parse(payload: dict[str, Any]) -> list[GeoPoint]:
        points: list[GeoPoint] = []
        for item in payload.get("results") or []:
            name = item.get("name")
            latitude = item.get("latitude")
            longitude = item.get("longitude")
            if not name or latitude is None or longitude is None:
                continue
            points.append(
                GeoPoint(
                    name=str(name),
                    latitude=float(latitude),
                    longitude=float(longitude),
                    country=item.get("country_code") or item.get("country"),
                    state=item.get("admin1"),
                    timezone=item.get("timezone"),
                    elevation_m=_optional_float(item.get("elevation")),
                )
            )
        return points


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Great-circle distance in kilometres."""

    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["GeoPoint", "GeocodeAdapter", "haversine_km"]
