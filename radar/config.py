from __future__ import annotations

import math
from dataclasses import asdict, dataclass

DEFAULT_LAT = 0.0
DEFAULT_LON = 0.0
RADIUS_CHOICES = (25, 50, 100, 150, 200)
DEFAULT_RADIUS_KM = 100
INTERVAL_MIN_S = 30
INTERVAL_MAX_S = 300
DEFAULT_INTERVAL_S = 60
VIEW_CHOICES = ("radar", "full")
COUNT_CORNERS = ("bottom-right", "bottom-left", "top-right", "top-left")
DEFAULT_COUNT_CORNER = "bottom-right"
DEFAULT_VIEW = "radar"
FULL_REACH = math.sqrt(2)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _clamped(value, low: float, high: float, default: float) -> float:
    number = _number(value)
    if number is None:
        return default
    return min(max(number, low), high)


def _flag(raw: dict, key: str, default: bool = True) -> bool:
    value = raw.get(key)
    return value if isinstance(value, bool) else default


@dataclass(frozen=True)
class Config:
    lat: float = DEFAULT_LAT
    lon: float = DEFAULT_LON
    radius_km: int = DEFAULT_RADIUS_KM
    interval_s: int = DEFAULT_INTERVAL_S
    hide_ground: bool = True
    show_map: bool = True
    view: str = DEFAULT_VIEW
    count_corner: str = DEFAULT_COUNT_CORNER
    colored: bool = True

    @property
    def full(self) -> bool:
        return self.view == "full"

    @property
    def fetch_radius_km(self) -> float:
        return self.radius_km * FULL_REACH if self.full else self.radius_km

    @classmethod
    def from_dict(cls, raw) -> "Config":
        raw = raw if isinstance(raw, dict) else {}

        radius = _number(raw.get("radius_km"))
        if radius is None:
            radius_km = DEFAULT_RADIUS_KM
        else:
            radius_km = min(RADIUS_CHOICES, key=lambda choice: abs(choice - radius))

        return cls(
            lat=round(_clamped(raw.get("lat"), -90.0, 90.0, DEFAULT_LAT), 4),
            lon=round(_clamped(raw.get("lon"), -180.0, 180.0, DEFAULT_LON), 4),
            radius_km=radius_km,
            interval_s=int(
                _clamped(raw.get("interval_s"), INTERVAL_MIN_S, INTERVAL_MAX_S, DEFAULT_INTERVAL_S)
            ),
            hide_ground=_flag(raw, "hide_ground"),
            show_map=_flag(raw, "show_map"),
            view=raw.get("view") if raw.get("view") in VIEW_CHOICES else DEFAULT_VIEW,
            count_corner=raw.get("count_corner") if raw.get("count_corner") in COUNT_CORNERS else DEFAULT_COUNT_CORNER,
            colored=_flag(raw, "colored"),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def next_radius(self) -> int:
        index = RADIUS_CHOICES.index(self.radius_km) if self.radius_km in RADIUS_CHOICES else -1
        return RADIUS_CHOICES[(index + 1) % len(RADIUS_CHOICES)]
