#!/usr/bin/env python3
"""Build data/map.json from Natural Earth (public domain) for the radar map outline.

    python3 scripts/build_map.py                         # Mexico, default tolerance
    python3 scripts/build_map.py --bbox -10 35 5 45      # another region (W S E N)
    python3 scripts/build_map.py --cache /tmp/ne         # reuse downloaded GeoJSON

Downloads about 64 MB of GeoJSON once into the cache directory; the resulting
data file is a few hundred KB and is the only thing the plugin reads at runtime.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
SOURCES = {
    "coast": "ne_10m_coastline",
    "lakes": "ne_10m_lakes",
    "states": "ne_10m_admin_1_states_provinces_lines",
    "urban": "ne_10m_urban_areas",
}
DEFAULT_BBOX = (-118.5, 14.0, -86.0, 33.0)
DEFAULT_TOLERANCE = 0.004
DEFAULT_CACHE = Path.home() / ".cache" / "sc-adskey" / "natural-earth"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "map.json"
USER_AGENT = "aircraft-radar-build-map/1.0 (+https://github.com/radiotaiso/aircraft-radar-streamcontroller)"

Point = tuple[float, float]


def iter_lines(geometry):
    if not geometry:
        return
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "LineString":
        yield coordinates
    elif kind in ("MultiLineString", "Polygon"):
        yield from coordinates
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            yield from polygon


def clip_line(points: list[Point], bbox: tuple[float, float, float, float]) -> list[list[Point]]:
    west, south, east, north = bbox
    inside = [west <= x <= east and south <= y <= north for x, y in points]
    runs: list[list[Point]] = []
    current: list[Point] = []
    last = len(points) - 1
    for index, point in enumerate(points):
        keep = inside[index] or (index > 0 and inside[index - 1]) or (index < last and inside[index + 1])
        if keep:
            current.append(point)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return [run for run in runs if len(run) >= 2]


def _distance_to_segment(point: Point, start: Point, end: Point) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify(points: list[Point], tolerance: float) -> list[Point]:
    count = len(points)
    if count < 3:
        return list(points)
    keep = [False] * count
    keep[0] = keep[-1] = True
    stack = [(0, count - 1)]
    while stack:
        first, last = stack.pop()
        farthest, index = -1.0, -1
        for k in range(first + 1, last):
            distance = _distance_to_segment(points[k], points[first], points[last])
            if distance > farthest:
                farthest, index = distance, k
        if farthest > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [point for point, kept in zip(points, keep) if kept]


def quantize(points: list[Point], decimals: int = 3) -> list[Point]:
    out: list[Point] = []
    for x, y in points:
        rounded = (round(x, decimals), round(y, decimals))
        if not out or out[-1] != rounded:
            out.append(rounded)
    return out


def process(lines, bbox, tolerance, decimals: int = 3) -> list[list[Point]]:
    result = []
    for line in lines:
        points = [(float(x), float(y)) for x, y, *_ in line]
        for run in clip_line(points, bbox):
            simplified = quantize(simplify(run, tolerance), decimals)
            if len(simplified) >= 2:
                result.append(simplified)
    return result


def fetch(name: str, cache: Path) -> Path:
    path = cache / f"{name}.geojson"
    if path.exists():
        return path
    cache.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(BASE + path.name, headers={"User-Agent": USER_AGENT})
    print(f"downloading {path.name} ...", flush=True)
    with urllib.request.urlopen(request, timeout=180) as response:
        path.write_bytes(response.read())
    return path


def flatten(lines: list[list[Point]], decimals: int = 3) -> dict:
    """All points in one flat array plus one count per line: small on disk and in memory."""
    counts = []
    points = []
    for line in lines:
        counts.append(len(line))
        for x, y in line:
            points.append(round(x, decimals))
            points.append(round(y, decimals))
    return {"counts": counts, "points": points}


def build(cache: Path, bbox, tolerance, decimals: int = 3) -> dict:
    layers = {}
    for layer, name in SOURCES.items():
        data = json.loads(fetch(name, cache).read_text())
        lines = (line for feature in data["features"] for line in iter_lines(feature.get("geometry")))
        layers[layer] = flatten(process(lines, bbox, tolerance, decimals), decimals)
    return {
        "source": "Natural Earth 1:10m (public domain), https://www.naturalearthdata.com",
        "bbox": list(bbox),
        "tolerance_deg": tolerance,
        "format": "flat",
        "layers": layers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the radar map outline data file")
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), default=DEFAULT_BBOX)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="Douglas-Peucker tolerance in degrees")
    parser.add_argument("--decimals", type=int, default=3, help="coordinate decimals kept after simplification")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    west, south, east, north = args.bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        print("invalid bbox", file=sys.stderr)
        return 2

    document = build(args.cache, tuple(args.bbox), args.tolerance, args.decimals)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, separators=(",", ":")))

    for layer, packed in document["layers"].items():
        print(f"{layer:7s} {len(packed['counts']):5d} lines {len(packed['points']) // 2:7d} points")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
