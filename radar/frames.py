from __future__ import annotations

import threading

from PIL import Image

from .render import render_list, render_radar
from .service import Snapshot


class FrameCache:
    def __init__(self, render=render_radar, list_mode: bool = False):
        self._render = render
        self._list_mode = list_mode
        self._lock = threading.Lock()
        self._entries: dict[int, tuple[int, Image.Image]] = {}

    def get(self, snapshot: Snapshot, size: int) -> Image.Image:
        with self._lock:
            hit = self._entries.get(size)
            if hit is not None and hit[0] == snapshot.version:
                return hit[1]

            config = snapshot.config
            if self._list_mode:
                image = render_list(
                    snapshot.aircraft,
                    (config.lat, config.lon),
                    config.radius_km,
                    size,
                    colored=config.colored,
                    stale=snapshot.stale,
                    full=config.full,
                )
            else:
                image = self._render(
                    snapshot.aircraft,
                    (config.lat, config.lon),
                    config.radius_km,
                    size,
                    stale=snapshot.stale,
                    show_map=config.show_map,
                    full=config.full,
                    count_corner=config.count_corner,
                    colored=config.colored,
                )
            if hit is None or snapshot.version >= hit[0]:
                self._entries[size] = (snapshot.version, image)
            return image
