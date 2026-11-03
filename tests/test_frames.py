import threading
import unittest

from PIL import Image

from radar.adsb import Aircraft
from radar.config import Config
from radar.frames import FrameCache
from radar.service import Snapshot


def snapshot(version=1, config=None, aircraft=(), stale=False):
    return Snapshot(
        version=version,
        config=config or Config(),
        aircraft=aircraft,
        fetched_at=1.0,
        stale=stale,
        failures=0,
        error=None,
    )


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, aircraft, center, radius_km, size, **kwargs):
        self.calls.append((aircraft, center, radius_km, size, kwargs))
        return Image.new("RGB", (size, size), (len(self.calls) % 256, 0, 0))


CORNER = (90 / 110.57, 90 / 111.32)


class FrameCacheTests(unittest.TestCase):
    def test_same_version_and_size_is_rendered_once(self):
        render = Recorder()
        cache = FrameCache(render)
        first = cache.get(snapshot(), 144)
        second = cache.get(snapshot(), 144)
        self.assertIs(first, second)
        self.assertEqual(len(render.calls), 1)

    def test_sizes_are_cached_independently(self):
        render = Recorder()
        cache = FrameCache(render)
        scope = cache.get(snapshot(), 72)
        tile = cache.get(snapshot(), 144)
        self.assertEqual((scope.size, tile.size), ((72, 72), (144, 144)))
        cache.get(snapshot(), 72)
        cache.get(snapshot(), 144)
        self.assertEqual(len(render.calls), 2)

    def test_new_version_rerenders(self):
        render = Recorder()
        cache = FrameCache(render)
        cache.get(snapshot(version=1), 72)
        cache.get(snapshot(version=2), 72)
        self.assertEqual(len(render.calls), 2)

    def test_older_snapshot_does_not_replace_a_newer_frame(self):
        render = Recorder()
        cache = FrameCache(render)
        newer = cache.get(snapshot(version=5), 72)
        cache.get(snapshot(version=3), 72)
        self.assertIs(cache.get(snapshot(version=5), 72), newer)

    def test_passes_the_config_to_the_renderer(self):
        render = Recorder()
        cache = FrameCache(render)
        config = Config(lat=19.4326, lon=-99.1332, radius_km=150, show_map=False)
        plane = Aircraft(hex="a", lat=19.5, lon=-99.1)
        cache.get(snapshot(config=config, aircraft=(plane,), stale=True), 144)
        aircraft, center, radius, size, kwargs = render.calls[0]
        self.assertEqual((aircraft, center, radius, size), ((plane,), (19.4326, -99.1332), 150, 144))
        self.assertEqual(
            kwargs,
            {"stale": True, "show_map": False, "full": False, "count_corner": "bottom-right", "colored": True},
        )

    def test_colored_flag_reaches_the_renderer(self):
        render = Recorder()
        cache = FrameCache(render)
        cache.get(snapshot(config=Config(colored=False)), 72)
        self.assertFalse(render.calls[0][4]["colored"])


class ListFrameTests(unittest.TestCase):
    def test_list_mode_renders_72x72_from_the_same_snapshot(self):
        cache = FrameCache(list_mode=True)
        plane = Aircraft(hex="abc123", lat=0.05, lon=0.02, callsign="AMX363", alt_ft=30000)
        image = cache.get(snapshot(aircraft=(plane,)), 72)
        self.assertEqual(image.size, (72, 72))
        self.assertEqual(image.mode, "RGB")

    def test_list_mode_caches_by_version_and_size(self):
        cache = FrameCache(list_mode=True)
        first = cache.get(snapshot(), 72)
        self.assertIs(cache.get(snapshot(), 72), first)
        self.assertIsNot(cache.get(snapshot(version=2), 72), first)

    def test_list_mode_forwards_stale_colored_and_full(self):
        plane = Aircraft(hex="a", lat=0.05, lon=0.02, callsign="X", track=10.0)
        corner = Aircraft(hex="b", lat=CORNER[0], lon=CORNER[1], callsign="Y")

        def frame(version, **config):
            return FrameCache(list_mode=True).get(snapshot(version=version, config=Config(**config), aircraft=(plane,)), 72).tobytes()

        self.assertNotEqual(frame(1), FrameCache(list_mode=True).get(snapshot(version=2, aircraft=(plane,), stale=True), 72).tobytes())
        self.assertNotEqual(frame(3, colored=True), frame(4, colored=False))

        def corner_frame(version, full):
            cache = FrameCache(list_mode=True)
            return cache.get(snapshot(version=version, config=Config(view="full" if full else "radar"), aircraft=(corner,)), 72).tobytes()

        self.assertNotEqual(corner_frame(5, False), corner_frame(6, True))

    def test_list_and_radar_caches_are_independent(self):
        radar = FrameCache()
        listing = FrameCache(list_mode=True)
        snap = snapshot(aircraft=(Aircraft(hex="a", lat=0.05, lon=0.02, callsign="X"),))
        self.assertNotEqual(radar.get(snap, 72).tobytes(), listing.get(snap, 72).tobytes())

    def test_count_corner_is_passed_to_the_renderer(self):
        render = Recorder()
        cache = FrameCache(render)
        cache.get(snapshot(config=Config(count_corner="top-left")), 72)
        self.assertEqual(render.calls[0][4]["count_corner"], "top-left")

    def test_moving_the_count_changes_the_frame(self):
        cache = FrameCache()
        bottom = cache.get(snapshot(version=1, config=Config(count_corner="bottom-right")), 144)
        top = cache.get(snapshot(version=2, config=Config(count_corner="top-left")), 144)
        self.assertNotEqual(bottom.tobytes(), top.tobytes())

    def test_full_view_is_passed_to_the_renderer(self):
        render = Recorder()
        cache = FrameCache(render)
        cache.get(snapshot(config=Config(view="full")), 144)
        self.assertTrue(render.calls[0][4]["full"])

    def test_switching_view_changes_the_frame_through_the_real_renderer(self):
        cache = FrameCache()
        radar = cache.get(snapshot(version=1, config=Config(view="radar")), 72)
        full = cache.get(snapshot(version=2, config=Config(view="full")), 72)
        self.assertNotEqual(radar.tobytes(), full.tobytes())

    def test_show_map_toggle_changes_the_frame_through_the_real_renderer(self):
        cache = FrameCache()
        with_map = cache.get(snapshot(version=1, config=Config(show_map=True)), 144)
        without = cache.get(snapshot(version=2, config=Config(show_map=False)), 144)
        self.assertNotEqual(with_map.tobytes(), without.tobytes())

    def test_waiting_snapshot_renders_without_aircraft(self):
        image = FrameCache().get(snapshot(aircraft=None), 72)
        self.assertEqual(image.size, (72, 72))

    def test_concurrent_gets_render_once(self):
        render = Recorder()
        cache = FrameCache(render)
        results = []

        def worker():
            results.append(cache.get(snapshot(), 144))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(render.calls), 1)
        self.assertTrue(all(result is results[0] for result in results))


if __name__ == "__main__":
    unittest.main()
