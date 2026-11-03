from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass

from .adsb import Aircraft, Client
from .config import Config


@dataclass(frozen=True)
class Snapshot:
    version: int
    config: Config
    aircraft: tuple[Aircraft, ...] | None
    fetched_at: float | None
    stale: bool
    failures: int
    error: str | None


class RadarService:
    STALE_FACTOR = 3
    BACKOFF_AFTER = 3
    BACKOFF_S = 300.0
    MIN_POLL_GAP_S = 5.0
    MAX_WAIT_S = 30.0
    MIN_WAIT_S = 0.05

    def __init__(self, config: Config | None = None, fetch=None, clock=time.monotonic, logger=None):
        self._config = config or Config()
        self._fetch = fetch or Client().fetch
        self._clock = clock
        self._log = logger or logging.getLogger("sc-adskey")

        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._subscribers: tuple = ()

        self._raw: tuple[Aircraft, ...] | None = None
        self._fetched_at: float | None = None
        self._failures = 0
        self._error: str | None = None
        self._stale = False
        self._version = 0
        self._notified = 0

        self._next_poll = 0.0
        self._last_poll = -math.inf
        self._force_poll = False
        self._redraw = False

    def configure(self, config: Config) -> None:
        with self._lock:
            old = self._config
            if config == old:
                return
            self._config = config
            if self._area(config) != self._area(old):
                self._raw = None
                self._fetched_at = None
                self._failures = 0
                self._error = None
                self._stale = False
                self._force_poll = True
            elif config.interval_s != old.interval_s and self._fetched_at is not None and self._failures < self.BACKOFF_AFTER:
                self._next_poll = self._last_poll + config.interval_s
            self._bump()
            self._redraw = True
        self._wake.set()

    def refresh(self) -> None:
        with self._lock:
            self._force_poll = True
        self._wake.set()

    def request_redraw(self) -> None:
        with self._lock:
            self._redraw = True
        self._wake.set()

    def subscribe(self, callback) -> None:
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers = self._subscribers + (callback,)

    def unsubscribe(self, callback) -> None:
        with self._lock:
            self._subscribers = tuple(item for item in self._subscribers if item != callback)

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot_locked()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="sc-adskey-service", daemon=True)
            thread = self._thread
        thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def process(self) -> float:
        now = self._clock()
        poll_config = None
        with self._lock:
            due = now >= self._next_poll
            forced = self._force_poll and now - self._last_poll >= self.MIN_POLL_GAP_S
            if due or forced:
                self._force_poll = False
                poll_config = self._config

        if poll_config is not None:
            self._poll(poll_config)

        self._refresh_stale()

        snapshot = None
        with self._lock:
            if self._redraw or self._version != self._notified:
                self._redraw = False
                self._notified = self._version
                snapshot = self._snapshot_locked()
        if snapshot is not None:
            self._deliver(snapshot)

        return self._wait_time()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.process()
            except Exception as exc:
                self._log.warning(f"sc-adskey service error: {exc.__class__.__name__}: {exc}")
                wait = 5.0
            self._wake.wait(wait)
            self._wake.clear()

    @staticmethod
    def _area(config: Config) -> tuple[float, float, float]:
        return (config.lat, config.lon, config.fetch_radius_km)

    def _bump(self) -> None:
        self._version += 1

    def _snapshot_locked(self) -> Snapshot:
        aircraft = self._raw
        if aircraft is not None and self._config.hide_ground:
            aircraft = tuple(plane for plane in aircraft if not plane.on_ground)
        return Snapshot(
            version=self._version,
            config=self._config,
            aircraft=aircraft,
            fetched_at=self._fetched_at,
            stale=self._stale,
            failures=self._failures,
            error=self._error,
        )

    def _poll(self, config: Config) -> None:
        with self._lock:
            self._last_poll = self._clock()
        try:
            aircraft = tuple(self._fetch(config.lat, config.lon, config.fetch_radius_km))
        except Exception as exc:
            self._on_failure(config, exc)
            return
        self._on_success(config, aircraft)

    def _on_success(self, config: Config, aircraft: tuple[Aircraft, ...]) -> None:
        with self._lock:
            if self._area(config) != self._area(self._config):
                self._force_poll = True
                return
            recovered = self._failures > 0
            self._raw = aircraft
            self._fetched_at = self._clock()
            self._failures = 0
            self._error = None
            self._stale = False
            self._next_poll = self._fetched_at + self._config.interval_s
            self._bump()
        if recovered:
            self._log.info("sc-adskey: adsb.lol reachable again")

    def _on_failure(self, config: Config, exc: Exception) -> None:
        with self._lock:
            if self._area(config) != self._area(self._config):
                self._force_poll = True
                return
            self._failures += 1
            self._error = f"{exc.__class__.__name__}: {exc}"[:160]
            delay = self.BACKOFF_S if self._failures >= self.BACKOFF_AFTER else float(self._config.interval_s)
            self._next_poll = self._clock() + delay
            failures, error = self._failures, self._error
            self._bump()
        self._log.warning(f"sc-adskey: poll failed ({failures}): {error}; retry in {delay:.0f}s")

    def _refresh_stale(self) -> None:
        now = self._clock()
        with self._lock:
            stale = (
                self._fetched_at is not None
                and now - self._fetched_at > self.STALE_FACTOR * self._config.interval_s
            )
            if stale != self._stale:
                self._stale = stale
                self._bump()

    def _wait_time(self) -> float:
        now = self._clock()
        with self._lock:
            wait = self._next_poll - now
            if self._force_poll:
                wait = min(wait, self._last_poll + self.MIN_POLL_GAP_S - now)
            if self._fetched_at is not None and not self._stale:
                wait = min(wait, self._fetched_at + self.STALE_FACTOR * self._config.interval_s + 0.01 - now)
            if self._redraw:
                wait = 0.0
        return min(max(wait, self.MIN_WAIT_S), self.MAX_WAIT_S)

    def _deliver(self, snapshot: Snapshot) -> None:
        for callback in self._subscribers:
            try:
                callback(snapshot)
            except Exception as exc:
                self._log.warning(f"sc-adskey: subscriber failed: {exc.__class__.__name__}: {exc}")
