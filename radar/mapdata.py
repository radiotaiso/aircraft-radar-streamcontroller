from __future__ import annotations

import json
import logging
from array import array
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "map.json"
LAYERS = ("urban", "states", "lakes", "coast")

_log = logging.getLogger("sc-adskey")


def _valid_point(point) -> bool:
    return (
        isinstance(point, (list, tuple))
        and len(point) >= 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in point[:2])
    )


def _packed_points(payload) -> array:
    try:
        if isinstance(payload, (list, tuple)):
            values = array("f", payload)
        else:
            values = array("f", (float(value) for value in str(payload).replace(",", " ").split()))
    except (TypeError, ValueError):
        return array("f")
    if len(values) % 2:
        values = values[:-1]
    return values


class _Layer:
    """Lines stored flat: coordinates, per-line counts, offsets and bounding boxes."""

    __slots__ = ("coords", "counts", "offsets", "boxes")

    def __init__(self, coords: array, counts: array):
        self.coords = coords
        self.counts = array("i")
        self.offsets = array("i")
        self.boxes = array("f")
        start = 0
        total = len(coords)
        for count in counts:
            end = start + count * 2
            if count >= 2 and end <= total:
                self.counts.append(count)
                self.offsets.append(start)
                xs = coords[start:end:2]
                ys = coords[start + 1:end:2]
                self.boxes.extend((min(xs), min(ys), max(xs), max(ys)))
            start = end

    @property
    def count(self) -> int:
        return len(self.counts)

    @classmethod
    def from_payload(cls, payload) -> "_Layer":
        if isinstance(payload, dict) and "points" in payload and "counts" in payload:
            return cls(_packed_points(payload["points"]), array("i", payload["counts"]))
        if isinstance(payload, (list, tuple)):
            counts = array("i")
            coords = array("f")
            for line in payload:
                points = [(float(p[0]), float(p[1])) for p in line if _valid_point(p)]
                if len(points) < 2:
                    continue
                counts.append(len(points))
                for lon, lat in points:
                    coords.extend((lon, lat))
            return cls(coords, counts)
        return cls(array("f"), array("i"))


class MapData:
    def __init__(self, layers=None, bbox=None, source: str = ""):
        self.source = source
        self.bbox = tuple(bbox) if bbox else None
        self._layers: dict[str, _Layer] = {}
        for name, payload in (layers or {}).items():
            layer = _Layer.from_payload(payload)
            if layer.count:
                self._layers[name] = layer

    @property
    def line_count(self) -> int:
        return sum(layer.count for layer in self._layers.values())

    @property
    def worldwide(self) -> bool:
        if self.bbox is None:
            return False
        west, south, east, north = self.bbox
        return west <= -179.9 and east >= 179.9 and south <= -89.9 and north >= 89.9

    def lines(self, layer: str, west: float, south: float, east: float, north: float):
        data = self._layers.get(layer)
        if data is None:
            return
        boxes, coords, counts, offsets = data.boxes, data.coords, data.counts, data.offsets
        for index in range(len(counts)):
            box = index * 4
            if boxes[box + 2] < west or boxes[box] > east or boxes[box + 3] < south or boxes[box + 1] > north:
                continue
            start = offsets[index]
            end = start + counts[index] * 2
            yield tuple((coords[i], coords[i + 1]) for i in range(start, end, 2))

    def covers(self, lat: float, lon: float) -> bool:
        if self.bbox is None:
            return False
        west, south, east, north = self.bbox
        return west <= lon <= east and south <= lat <= north


def load(path: Path = DATA_PATH) -> MapData:
    try:
        document = json.loads(Path(path).read_text())
        layers = document["layers"]
        bbox = document.get("bbox")
        if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4):
            bbox = None
        if not isinstance(layers, dict):
            raise TypeError("layers must be an object")
        return MapData(layers, bbox, str(document.get("source", "")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _log.warning(f"sc-adskey: map data unavailable ({exc.__class__.__name__}: {exc}); radar will draw without a map")
        return MapData()


@lru_cache(maxsize=1)
def default() -> MapData:
    return load(DATA_PATH)
