from __future__ import annotations

import math
from dataclasses import dataclass

import requests

VERSION = "1.0.0"
KM_PER_NM = 1.852
MAX_NM = 250
USER_AGENT = f"aircraft-radar/{VERSION} (+https://github.com/radiotaiso/aircraft-radar-streamcontroller)"
ENDPOINT = "https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{nm}"


class AdsbError(Exception):
    pass


@dataclass(frozen=True)
class Aircraft:
    hex: str
    lat: float
    lon: float
    callsign: str | None = None
    type: str | None = None
    alt_ft: int | None = None
    on_ground: bool = False
    gs: float | None = None
    track: float | None = None


def km_to_nm(km: float) -> int:
    return max(1, min(MAX_NM, round(km / KM_PER_NM)))


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _text(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def parse(payload) -> list[Aircraft]:
    records = payload.get("ac") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []

    aircraft = []
    for record in records:
        if not isinstance(record, dict):
            continue
        lat = _number(record.get("lat"))
        lon = _number(record.get("lon"))
        if lat is None or lon is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        altitude = record.get("alt_baro")
        on_ground = altitude == "ground"
        altitude_ft = 0 if on_ground else _number(altitude)

        aircraft.append(
            Aircraft(
                hex=_text(record.get("hex")) or "",
                lat=lat,
                lon=lon,
                callsign=_text(record.get("flight")),
                type=_text(record.get("t")),
                alt_ft=None if altitude_ft is None else int(altitude_ft),
                on_ground=on_ground,
                gs=_number(record.get("gs")),
                track=_number(record.get("track")),
            )
        )
    return aircraft


class Client:
    def __init__(self, timeout: float = 8.0, session=None, user_agent: str = USER_AGENT):
        self._timeout = timeout
        self._session = session or requests.Session()
        self._headers = {"User-Agent": user_agent}

    def fetch(self, lat: float, lon: float, radius_km: float) -> list[Aircraft]:
        url = ENDPOINT.format(lat=lat, lon=lon, nm=km_to_nm(radius_km))
        try:
            response = self._session.get(url, headers=self._headers, timeout=self._timeout)
        except requests.RequestException as exc:
            raise AdsbError(f"request failed: {exc.__class__.__name__}") from exc

        if response.status_code == 429:
            raise AdsbError("rate limited (HTTP 429)")
        if response.status_code != 200:
            raise AdsbError(f"HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise AdsbError("invalid JSON") from exc
        return parse(payload)
