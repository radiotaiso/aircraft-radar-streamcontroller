from __future__ import annotations

import math
from functools import lru_cache
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import mapdata
from .adsb import Aircraft
from .config import DEFAULT_COUNT_CORNER

KEY = 72
KM_PER_DEG_LAT = 110.57
KM_PER_DEG_LON = 111.32
RANGE_TOLERANCE = 1.01

MAP_LEVELS = (("urban", 55), ("states", 70), ("lakes", 100), ("coast", 130))

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREY = (150, 150, 150)

# Colours for the nearest aircraft, shared by the radar and the list so a row and
# a dot can be matched. Chosen for contrast on black at 8 px.
PALETTE = (
    (255, 59, 48),
    (255, 149, 0),
    (255, 214, 10),
    (48, 209, 88),
    (10, 132, 255),
    (191, 90, 242),
)
COLOR_SLOTS = len(PALETTE)
LIST_PITCH = 11

PLANE_SHAPE = (
    (0, -5.0), (0.9, -2.2), (5.0, 1.0), (5.0, 2.2), (0.9, 0.9), (0.9, 3.2),
    (2.4, 4.4), (2.4, 5.2), (0, 4.4), (-2.4, 5.2), (-2.4, 4.4), (-0.9, 3.2),
    (-0.9, 0.9), (-5.0, 2.2), (-5.0, 1.0), (-0.9, -2.2),
)
TRACK_STEP = 5
SUPERSAMPLE = 8

FONT_CANDIDATES = (
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)


@lru_cache(maxsize=None)
def _font(px: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)


def offset_km(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    dlon = (lon - lon0 + 180.0) % 360.0 - 180.0
    dx = dlon * KM_PER_DEG_LON * math.cos(math.radians(lat0))
    dy = (lat - lat0) * KM_PER_DEG_LAT
    return dx, dy


def radar_radius_px(size: int) -> int:
    return size // 2 - 2


def icon_budget(size: int) -> int:
    return 5 if size < 2 * KEY else 12


def icon_px(size: int) -> int:
    return 8 if size < 2 * KEY else 10


def to_pixels(
    lat: float,
    lon: float,
    center: tuple[float, float],
    radius_km: float,
    size: int,
    full: bool = False,
) -> tuple[int, int] | None:
    dx, dy = offset_km(lat, lon, center[0], center[1])
    limit = radius_km * RANGE_TOLERANCE
    half = size // 2
    if full:
        if abs(dx) > limit or abs(dy) > limit:
            return None
        scale = half / radius_km
    else:
        if math.hypot(dx, dy) > limit:
            return None
        scale = radar_radius_px(size) / radius_km
    return round(half + dx * scale), round(half - dy * scale)


def _clamp_to_disc(x: float, y: float, cx: int, cy: int, limit: float) -> tuple[int, int]:
    dist = math.hypot(x - cx, y - cy)
    if dist > limit and dist > 0:
        scale = limit / dist
        x = cx + (x - cx) * scale
        y = cy + (y - cy) * scale
    return round(x), round(y)


def _clamp_to_square(x: float, y: float, size: int, margin: int) -> tuple[int, int]:
    low, high = margin, size - 1 - margin
    return round(min(max(x, low), high)), round(min(max(y, low), high))


def _dotted_circle(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, on: int = 4, off: int = 6):
    steps = max(8, int(2 * math.pi * radius))
    period = on + off
    for i in range(steps):
        if i % period < on:
            angle = 2 * math.pi * i / steps
            draw.point((round(cx + radius * math.cos(angle)), round(cy + radius * math.sin(angle))), fill=255)


def _dotted_border(draw: ImageDraw.ImageDraw, size: int, inset: int = 1, on: int = 2, off: int = 2, fill=255):
    low, high = inset, size - 1 - inset
    period = on + off
    for i, v in enumerate(range(low, high + 1)):
        if i % period < on:
            draw.point((v, low), fill=fill)
            draw.point((v, high), fill=fill)
            draw.point((low, v), fill=fill)
            draw.point((high, v), fill=fill)


def _draw_origin(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int):
    if size >= 2 * KEY:
        draw.polygon([(cx, cy - 3), (cx + 3, cy), (cx, cy + 3), (cx - 3, cy)], fill=255)
    else:
        draw.point([(cx, cy), (cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)], fill=255)


COUNT_ANCHORS = {
    DEFAULT_COUNT_CORNER: ("rs", 1, 1),
    "bottom-left": ("ls", 0, 1),
    "top-right": ("rt", 1, 0),
    "top-left": ("lt", 0, 0),
}


def _draw_count(draw: ImageDraw.ImageDraw, size: int, text: str, corner: str = DEFAULT_COUNT_CORNER, fill=255, paper=0):
    anchor, right_side, bottom_side = COUNT_ANCHORS.get(corner, COUNT_ANCHORS[DEFAULT_COUNT_CORNER])
    margin = 3
    x = size - 1 - margin if right_side else margin
    y = size - 1 - margin if bottom_side else margin
    font = _font(13)
    left, top, right, bottom = draw.textbbox((x, y), text, font=font, anchor=anchor)
    draw.rectangle([left - 1, top - 1, right + 1, bottom + 1], fill=paper)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


@lru_cache(maxsize=16)
def _map_layer(
    lat: float, lon: float, radius_km: float, size: int, data: mapdata.MapData, full: bool = False
) -> Image.Image:
    half = size // 2
    ring = radar_radius_px(size)
    scale = (half if full else ring) / radius_km
    reach_lat = radius_km * RANGE_TOLERANCE / KM_PER_DEG_LAT
    reach_lon = radius_km * RANGE_TOLERANCE / (KM_PER_DEG_LON * max(math.cos(math.radians(lat)), 0.05))

    layer = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(layer)
    for name, level in MAP_LEVELS:
        for points in data.lines(name, lon - reach_lon, lat - reach_lat, lon + reach_lon, lat + reach_lat):
            pixels = []
            for point_lon, point_lat in points:
                dx, dy = offset_km(point_lat, point_lon, lat, lon)
                pixels.append((half + dx * scale, half - dy * scale))
            draw.line(pixels, fill=level, width=1)

    if full:
        return layer

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([half - ring, half - ring, half + ring, half + ring], fill=255)
    clipped = Image.new("L", (size, size), 0)
    clipped.paste(layer, mask=mask)
    return clipped


@lru_cache(maxsize=512)
def _plane_icon(bucket: int, px: int) -> tuple[Image.Image, Image.Image]:
    box = px + 5 if px % 2 == 0 else px + 4
    big = Image.new("L", (box * SUPERSAMPLE, box * SUPERSAMPLE), 0)
    scale = px / 10.0 * SUPERSAMPLE
    center = box * SUPERSAMPLE / 2
    angle = math.radians(bucket)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    points = [((x * cos_a - y * sin_a) * scale + center, (x * sin_a + y * cos_a) * scale + center) for x, y in PLANE_SHAPE]
    ImageDraw.Draw(big).polygon(points, fill=255)
    stamp = big.resize((box, box), Image.BOX)
    halo = stamp.point(lambda value: 255 if value > 30 else 0).filter(ImageFilter.MaxFilter(3))
    return stamp, halo


def _icon_for(track: float, px: int) -> tuple[Image.Image, Image.Image]:
    return _plane_icon(int(round(track / TRACK_STEP)) * TRACK_STEP % 360, px)


def _paste_icon(canvas: Image.Image, stamp: Image.Image, halo: Image.Image, bx: int, by: int, fill=255, paper=0):
    origin = (bx - stamp.width // 2, by - stamp.height // 2)
    canvas.paste(paper, origin, halo)
    canvas.paste(fill, origin, stamp)


def _draw_marker(draw: ImageDraw.ImageDraw, plane: Aircraft, x: int, y: int, nearest: bool, fit, insets, fill=255):
    near_inset, far_inset = insets
    if nearest:
        bx, by = fit(x, y, near_inset)
        draw.rectangle([bx - 2, by - 2, bx + 2, by + 2], fill=fill)
        if plane.track is not None:
            heading = math.radians(plane.track)
            tip = fit(bx + 5 * math.sin(heading), by - 5 * math.cos(heading), 0)
            draw.line([(bx, by), tip], fill=fill)
    else:
        bx, by = fit(x, y, far_inset)
        draw.rectangle([bx - 1, by - 1, bx + 1, by + 1], fill=fill)


def _visible(aircraft: Sequence[Aircraft], center: tuple[float, float], radius_km: float, full: bool = False):
    limit = radius_km * RANGE_TOLERANCE
    for plane in aircraft:
        dx, dy = offset_km(plane.lat, plane.lon, center[0], center[1])
        inside = abs(dx) <= limit and abs(dy) <= limit if full else math.hypot(dx, dy) <= limit
        if inside:
            yield math.hypot(dx, dy), plane


def nearest_planes(
    aircraft: Sequence[Aircraft],
    center: tuple[float, float],
    radius_km: float,
    full: bool = False,
    limit: int | None = None,
) -> list[tuple[float, Aircraft]]:
    """Visible aircraft, nearest first, deterministic on ties (same order the radar paints)."""
    ranked = sorted(_visible(aircraft, center, radius_km, full), key=lambda item: (item[0], item[1].hex))
    return ranked[:limit] if limit is not None else ranked


def color_for_rank(rank: int):
    return PALETTE[rank] if rank < COLOR_SLOTS else None


def render_radar(
    aircraft: Sequence[Aircraft] | None,
    center: tuple[float, float],
    radius_km: float,
    size: int,
    *,
    stale: bool = False,
    show_count: bool = True,
    show_map: bool = False,
    map_data: mapdata.MapData | None = None,
    max_icons: int | None = None,
    full: bool = False,
    count_corner: str = DEFAULT_COUNT_CORNER,
    colored: bool = False,
) -> Image.Image:
    if show_map:
        data = map_data if map_data is not None else mapdata.default()
        canvas = _map_layer(center[0], center[1], radius_km, size, data, full).copy()
    else:
        canvas = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(canvas)
    cx = cy = size // 2
    ring = radar_radius_px(size)
    reach = cx if full else ring

    def fit(x, y, inset):
        if full:
            return _clamp_to_square(x, y, size, inset)
        return _clamp_to_disc(x, y, cx, cy, ring - inset)

    marker_insets = (2, 1) if full else (3, 2)

    ranked: list[tuple[float, Aircraft, tuple[int, int]]] = []
    if aircraft is not None:
        for distance, plane in nearest_planes(aircraft, center, radius_km, full):
            pixels = to_pixels(plane.lat, plane.lon, center, radius_km, size, full)
            if pixels is None:
                continue
            ranked.append((distance, plane, pixels))

    waiting = aircraft is None
    dotted_ring = waiting or stale or not ranked

    if not show_map:
        guides = (0.5,) if size < 2 * KEY else (0.33, 0.66)
        for fraction in guides:
            _dotted_circle(draw, cx, cy, round(reach * fraction), on=1, off=3)

    if full:
        last = size - 1
        for tick in ((cx, 0, cx, 2), (cx, last, cx, last - 2), (0, cy, 2, cy), (last, cy, last - 2, cy)):
            draw.line([(tick[0], tick[1]), (tick[2], tick[3])], fill=255)
    else:
        if dotted_ring:
            _dotted_circle(draw, cx, cy, ring)
        else:
            draw.ellipse([cx - ring, cy - ring, cx + ring, cy + ring], outline=255, width=1)
        for ux, uy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            draw.line([(cx + ux * ring, cy + uy * ring), (cx + ux * (ring - 3), cy + uy * (ring - 3))], fill=255)

    _draw_origin(draw, cx, cy, size)

    if colored:
        canvas = canvas.convert("RGB")
        draw = ImageDraw.Draw(canvas)
    ink = WHITE if colored else 255
    paper = BLACK if colored else 0

    budget = icon_budget(size) if max_icons is None else max_icons
    px = icon_px(size)
    for rank in range(len(ranked) - 1, -1, -1):
        _, plane, (x, y) = ranked[rank]
        colour = (color_for_rank(rank) or ink) if colored else ink
        if rank < budget and plane.track is not None:
            stamp, halo = _icon_for(plane.track, px + (2 if rank == 0 else 0))
            if full:
                bx, by = _clamp_to_square(x, y, size, stamp.width // 2)
            else:
                bx, by = _clamp_to_disc(x, y, cx, cy, ring - px * 11 // 20 - 2)
            _paste_icon(canvas, stamp, halo, bx, by, colour, paper)
        else:
            _draw_marker(draw, plane, x, y, rank == 0, fit, marker_insets, colour)

    if stale:
        _dotted_border(draw, size, fill=ink)

    if waiting:
        draw.text((cx, cy), "--", font=_font(16), fill=ink, anchor="mm")
    elif show_count:
        _draw_count(draw, size, str(len(ranked)), count_corner, ink, paper)

    return canvas.convert("RGB")


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    trimmed = text
    while trimmed and draw.textlength(trimmed, font=font) > max_width:
        trimmed = trimmed[:-1]
    return trimmed or text[:1]


def render_list(
    aircraft: Sequence[Aircraft] | None,
    center: tuple[float, float],
    radius_km: float,
    size: int = KEY,
    *,
    colored: bool = True,
    stale: bool = False,
    full: bool = False,
) -> Image.Image:
    """One key with the nearest aircraft as rows: colour swatch, callsign and distance."""
    canvas = Image.new("RGB", (size, size), BLACK)
    draw = ImageDraw.Draw(canvas)

    scale = size / KEY
    font = _font(max(8, round(10 * scale)))
    small = _font(max(7, round(8 * scale)))
    pitch = max(9, round(LIST_PITCH * scale))
    margin = max(1, round(2 * scale))

    waiting = aircraft is None
    ranked = nearest_planes(aircraft or (), center, radius_km, full)
    rows = min(len(ranked), max(1, (size - 2 * margin) // pitch))
    top = max(margin, (size - rows * pitch) // 2)

    swatch = max(2, round(3 * scale))
    text_x = margin + swatch + max(1, round(scale))
    full_width = size - margin - text_x

    for index, (distance, plane) in enumerate(ranked[:rows]):
        y = top + index * pitch
        colour = color_for_rank(index) if colored else None
        if colour is not None:
            draw.rectangle([margin, y + 1, margin + swatch - 1, y + pitch - 2], fill=colour)
        callsign = plane.callsign or plane.hex or "?"
        distance_text = f"{distance:.0f}"
        dist_w = draw.textlength(distance_text, font=small)
        if draw.textlength(callsign, font=font) <= full_width - dist_w - 2:
            label = callsign
            draw.text((size - margin, y), distance_text, font=small, fill=GREY, anchor="rt")
        else:
            label = _fit_text(draw, callsign, font, full_width)
        draw.text((text_x, y), label, font=font, fill=WHITE, anchor="lt")

    if waiting:
        draw.text((size // 2, size // 2), "--", font=_font(16), fill=WHITE, anchor="mm")
    elif not ranked:
        draw.text((size // 2, size // 2), "0", font=_font(16), fill=WHITE, anchor="mm")

    if stale:
        _dotted_border(draw, size, fill=WHITE)

    return canvas


def render_warning(size: int = KEY) -> Image.Image:
    canvas = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(canvas)
    _dotted_border(draw, size)
    draw.text((size // 2, size // 2), "!", font=_font(int(size * 0.7)), fill=255, anchor="mm")
    return canvas.convert("RGB")


def crop_tile(image: Image.Image, col: int, row: int, key: int = KEY) -> Image.Image:
    return image.crop((col * key, row * key, (col + 1) * key, (row + 1) * key))
