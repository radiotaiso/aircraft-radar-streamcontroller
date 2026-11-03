#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from radar import adsb, config, render  # noqa: E402

DEMO = (
    (12.0, 40.0, 270.0),
    (35.0, 120.0, 45.0),
    (58.0, 200.0, 10.0),
    (74.0, 310.0, 90.0),
    (88.0, 20.0, None),
    (93.0, 255.0, 140.0),
)


def demo_aircraft(lat: float, lon: float, radius_km: float) -> list[adsb.Aircraft]:
    planes = []
    for index, (fraction_km, bearing, track) in enumerate(DEMO):
        distance = fraction_km / 100.0 * radius_km
        north = distance * math.cos(math.radians(bearing))
        east = distance * math.sin(math.radians(bearing))
        planes.append(
            adsb.Aircraft(
                hex=f"demo{index:02d}",
                lat=lat + north / render.KM_PER_DEG_LAT,
                lon=lon + east / (render.KM_PER_DEG_LON * math.cos(math.radians(lat))),
                track=track,
            )
        )
    return planes


def compose_deck(frame: Image.Image, gap: int) -> Image.Image:
    key = render.KEY
    side = 2 * key + gap
    deck = Image.new("RGB", (side, side), (40, 40, 40))
    for row in range(2):
        for col in range(2):
            deck.paste(render.crop_tile(frame, col, row, key), (col * (key + gap), row * (key + gap)))
    return deck


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a sc-adskey radar frame to a PNG")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="synthetic aircraft (default)")
    source.add_argument("--fixture", type=Path, help="adsb.lol JSON payload file")
    source.add_argument("--live", action="store_true", help="fetch from api.adsb.lol")
    source.add_argument("--empty", action="store_true", help="fresh data, no aircraft in range")
    source.add_argument("--waiting", action="store_true", help="no data yet")
    source.add_argument("--warning", action="store_true", help="invalid block glyph")
    parser.add_argument("--list", action="store_true", help="render the list action instead of the radar")
    parser.add_argument("--white", action="store_true", help="white aircraft instead of colored")
    parser.add_argument("--lat", type=float, default=config.DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=config.DEFAULT_LON)
    parser.add_argument("--km", type=float, default=config.DEFAULT_RADIUS_KM)
    parser.add_argument("--size", type=int, choices=(72, 144), default=72)
    parser.add_argument("--stale", action="store_true")
    parser.add_argument("--keep-ground", action="store_true")
    parser.add_argument("--no-map", action="store_true", help="draw without the map outline")
    parser.add_argument("--full", action="store_true", help="fill the whole key (square) instead of the round radar")
    parser.add_argument("--count-corner", default=config.DEFAULT_COUNT_CORNER, choices=config.COUNT_CORNERS)
    parser.add_argument("--max-icons", type=int, default=None, help="plane icons before falling back to squares (0 = squares only)")
    parser.add_argument("--scale", type=int, default=1, help="nearest-neighbour upscale for viewing")
    parser.add_argument("--gap", type=int, default=0, help="simulate the bezel between the 4 keys (size 144)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.warning:
        frame = render.render_warning(args.size)
    else:
        if args.fixture:
            planes = adsb.parse(json.loads(args.fixture.read_text()))
        elif args.live:
            planes = adsb.Client().fetch(args.lat, args.lon, args.km * (config.FULL_REACH if args.full else 1))
        elif args.empty:
            planes = []
        elif args.waiting:
            planes = None
        else:
            planes = demo_aircraft(args.lat, args.lon, args.km)

        if planes is not None and not args.keep_ground:
            planes = [plane for plane in planes if not plane.on_ground]

        if args.list:
            frame = render.render_list(
                planes,
                (args.lat, args.lon),
                args.km,
                args.size,
                colored=not args.white,
                stale=args.stale,
                full=args.full,
            )
        else:
            frame = render.render_radar(
                planes,
                (args.lat, args.lon),
                args.km,
                args.size,
                stale=args.stale,
                show_map=not args.no_map,
                max_icons=args.max_icons,
                full=args.full,
                count_corner=args.count_corner,
                colored=not args.white,
            )
        if planes is not None:
            print(f"{len(planes)} aircraft fetched/selected")

    if args.gap and args.size == 144:
        frame = compose_deck(frame, args.gap)
    if args.scale > 1:
        frame = frame.resize((frame.width * args.scale, frame.height * args.scale), Image.NEAREST)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.save(args.out)
    print(f"wrote {args.out} ({frame.width}x{frame.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
