from __future__ import annotations

UNIT_CHOICES = ("nm", "km", "mi")
DEFAULT_UNIT = "nm"

KM_PER_NM = 1.852
KM_PER_MI = 1.609344

_FACTORS = {"nm": KM_PER_NM, "km": 1.0, "mi": KM_PER_MI}
_SUFFIXES = {"nm": "NM", "km": "km", "mi": "mi"}


def _factor(unit: str) -> float:
    return _FACTORS.get(unit, _FACTORS[DEFAULT_UNIT])


def to_unit(km: float, unit: str = DEFAULT_UNIT) -> float:
    return km / _factor(unit)


def format_distance(km: float, unit: str = DEFAULT_UNIT) -> str:
    return f"{to_unit(km, unit):.0f}"


def unit_label(km: float, unit: str = DEFAULT_UNIT) -> str:
    resolved = unit if unit in _FACTORS else DEFAULT_UNIT
    value = to_unit(km, resolved)
    whole = round(value)
    text = str(whole) if abs(value - whole) < 0.05 else f"{value:.1f}"
    return f"{text} {_SUFFIXES[resolved]}"
