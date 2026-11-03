#!/usr/bin/env python3
"""Compose store/Thumbnail.png (1000x360) from real plugin frames.

The StreamController store shows the thumbnail at 250x90 with ContentFit.COVER,
so 1000x360 is the 4x size official plugins use.

    python3 scripts/store_art.py                  # synthetic aircraft, offline
    python3 scripts/store_art.py --live            # real aircraft from adsb.lol
    python3 scripts/store_art.py --out /tmp/art.png
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from radar import adsb, config, render  # noqa: E402

WIDTH, HEIGHT = 1000, 360
BOLD = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
REGULAR = "/usr/share/fonts/TTF/DejaVuSans.ttf"

DEMO = (
    ("AMX2101", 25, 0.18, 250.0),
    ("VOI3100", 130, 0.30, 120.0),
    ("ASA1201", 300, 0.12, 300.0),
    ("QXE2296", 60, 0.42, 45.0),
    ("N525FC", 200, 0.55, 180.0),
    ("SHWK432", 340, 0.70, 10.0),
)


def font(path: str, px: int):
    try:
        return ImageFont.truetype(path, px)
    except OSError:
        return ImageFont.load_default(size=px)


def demo_aircraft(lat: float, lon: float, radius_km: float) -> list[adsb.Aircraft]:
    planes = []
    for callsign, bearing, fraction, track in DEMO:
        distance = fraction * radius_km
        north = distance * math.cos(math.radians(bearing))
        east = distance * math.sin(math.radians(bearing))
        planes.append(
            adsb.Aircraft(
                hex=f"demo{len(planes)}",
                lat=lat + north / render.KM_PER_DEG_LAT,
                lon=lon + east / (render.KM_PER_DEG_LON * math.cos(math.radians(lat))),
                callsign=callsign,
                track=track,
            )
        )
    return planes


def backdrop() -> Image.Image:
    top, bottom = (16, 16, 22), (28, 28, 38)
    image = Image.new("RGB", (WIDTH, HEIGHT), top)
    px = image.load()
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        colour = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(WIDTH):
            px[x, y] = colour
    return image


def paste_key(canvas: Image.Image, key: Image.Image, xy: tuple[int, int], scale: int = 2, radius: int = 8):
    big = key.resize((key.width * scale, key.height * scale), Image.NEAREST)
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big.width - 1, big.height - 1], radius=radius, fill=255)
    canvas.paste(big, xy, mask)
    outline = ImageDraw.Draw(canvas)
    outline.rounded_rectangle(
        [xy[0], xy[1], xy[0] + big.width - 1, xy[1] + big.height - 1],
        radius=radius,
        outline=(52, 52, 64),
        width=1,
    )


def build(center: tuple[float, float], radius_km: float, planes: list[adsb.Aircraft]) -> Image.Image:
    canvas = backdrop()
    draw = ImageDraw.Draw(canvas)

    plate = (520, 16, 968, 344)
    draw.rounded_rectangle(plate, radius=20, fill=(9, 9, 13), outline=(46, 46, 58), width=1)

    scope = render.render_radar(planes, center, radius_km, 72, show_map=True, colored=True, full=True)
    mosaic = render.render_radar(planes, center, radius_km, 144, show_map=True, colored=True, full=True)
    listing = render.render_list(planes, center, radius_km, 72, colored=True)

    content_x = 548
    paste_key(canvas, scope, (content_x, 30))
    paste_key(canvas, listing, (content_x, 186))
    paste_key(canvas, mosaic, (704, 36))

    title = font(BOLD, 52)
    subtitle = font(REGULAR, 24)
    detail = font(REGULAR, 17)
    credit = font(REGULAR, 15)

    draw.text((56, 96), "Aircraft Radar", font=title, fill=(245, 245, 250), anchor="lt")
    draw.rounded_rectangle([56, 168, 156, 173], radius=2, fill=render.PALETTE[4])
    draw.text((56, 190), "Live aircraft on your Stream Deck", font=subtitle, fill=(205, 205, 214), anchor="lt")
    draw.text((56, 234), "one key · 2x2 block · list", font=detail, fill=(150, 150, 162), anchor="lt")
    draw.text((56, 258), "world map · colored by distance", font=detail, fill=(150, 150, 162), anchor="lt")
    draw.text((56, 320), "Data: api.adsb.lol  ·  Map: Natural Earth", font=credit, fill=(118, 118, 130), anchor="lt")
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the store thumbnail")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "store" / "Thumbnail.png")
    parser.add_argument("--lat", type=float, default=config.DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=config.DEFAULT_LON)
    parser.add_argument("--km", type=float, default=100)
    parser.add_argument("--live", action="store_true", help="use real aircraft from adsb.lol")
    args = parser.parse_args()

    if args.live:
        planes = [plane for plane in adsb.Client().fetch(args.lat, args.lon, args.km) if not plane.on_ground]
        nearest = render.nearest_planes(planes, (args.lat, args.lon), args.km, limit=10)
        planes = [plane for _, plane in nearest]
        print(f"{len(planes)} aircraft kept (nearest 10 of the fetch)")
        if not planes:
            print("no aircraft in range; falling back to synthetic ones")
            planes = demo_aircraft(args.lat, args.lon, args.km)
    else:
        planes = demo_aircraft(args.lat, args.lon, args.km)

    image = build((args.lat, args.lon), args.km, planes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(f"wrote {args.out} ({image.width}x{image.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
