import time
import unittest

from radar.adsb import Aircraft, AdsbError
from radar.config import Config
from radar.service import RadarService


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeFetch:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, lat, lon, radius_km):
        self.calls.append((lat, lon, radius_km))
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return list(result)


class Quiet:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


FLYING = Aircraft(hex="a", lat=0.05, lon=0.02, alt_ft=30000)
GROUND = Aircraft(hex="g", lat=0.0, lon=-0.01, alt_ft=0, on_ground=True)
CONFIG = Config(lat=0.0, lon=0.0, radius_km=100, interval_s=60)


def make(fetch, config=CONFIG):
    clock = FakeClock()
    log = Quiet()
    service = RadarService(config=config, fetch=fetch, clock=clock, logger=log)
    return service, clock, log


class PollingTests(unittest.TestCase):
    def test_first_process_polls_and_notifies(self):
        fetch = FakeFetch([FLYING])
        service, _, _ = make(fetch)
        received = []
        service.subscribe(received.append)

        service.process()

        self.assertEqual(fetch.calls, [(CONFIG.lat, CONFIG.lon, 100)])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].aircraft, (FLYING,))
        self.assertFalse(received[0].stale)

    def test_waits_for_the_interval(self):
        fetch = FakeFetch([FLYING])
        service, clock, _ = make(fetch)
        service.process()
        clock.advance(59)
        service.process()
        self.assertEqual(len(fetch.calls), 1)
        clock.advance(1)
        service.process()
        self.assertEqual(len(fetch.calls), 2)

    def test_snapshot_before_first_poll_has_no_data(self):
        service, _, _ = make(FakeFetch([FLYING]))
        snap = service.snapshot()
        self.assertIsNone(snap.aircraft)
        self.assertIsNone(snap.fetched_at)

    def test_version_changes_only_with_state(self):
        service, clock, _ = make(FakeFetch([FLYING]))
        service.process()
        first = service.snapshot().version
        service.process()
        self.assertEqual(service.snapshot().version, first)
        clock.advance(60)
        service.process()
        self.assertGreater(service.snapshot().version, first)

    def test_hide_ground_filters_by_default_and_toggles_without_refetch(self):
        fetch = FakeFetch([FLYING, GROUND])
        service, _, _ = make(fetch)
        service.process()
        self.assertEqual(service.snapshot().aircraft, (FLYING,))

        service.configure(Config(**{**CONFIG.to_dict(), "hide_ground": False}))
        service.process()
        self.assertEqual(len(service.snapshot().aircraft), 2)
        self.assertEqual(len(fetch.calls), 1)


class FailureTests(unittest.TestCase):
    def test_failure_keeps_previous_data(self):
        fetch = FakeFetch([FLYING], AdsbError("boom"))
        service, clock, log = make(fetch)
        service.process()
        clock.advance(60)
        service.process()

        snap = service.snapshot()
        self.assertEqual(snap.aircraft, (FLYING,))
        self.assertEqual(snap.failures, 1)
        self.assertIn("boom", snap.error)
        self.assertTrue(any(level == "warning" for level, _ in log.messages))

    def test_backoff_after_three_failures_then_recovery(self):
        fetch = FakeFetch(AdsbError("down"), AdsbError("down"), AdsbError("down"), [FLYING])
        service, clock, log = make(fetch)

        service.process()
        clock.advance(60)
        service.process()
        clock.advance(60)
        service.process()
        self.assertEqual(len(fetch.calls), 3)
        self.assertEqual(service.snapshot().failures, 3)

        clock.advance(299)
        service.process()
        self.assertEqual(len(fetch.calls), 3, "still inside the 300 s backoff")

        clock.advance(2)
        service.process()
        self.assertEqual(len(fetch.calls), 4)
        snap = service.snapshot()
        self.assertEqual(snap.failures, 0)
        self.assertIsNone(snap.error)
        self.assertEqual(snap.aircraft, (FLYING,))
        self.assertTrue(any("reachable again" in message for _, message in log.messages))

        clock.advance(60)
        service.process()
        self.assertEqual(len(fetch.calls), 5, "interval is back to normal after recovery")

    def test_failure_before_any_data_stays_without_data(self):
        service, _, _ = make(FakeFetch(AdsbError("down")))
        service.process()
        self.assertIsNone(service.snapshot().aircraft)


class StaleTests(unittest.TestCase):
    def test_becomes_stale_after_three_intervals_and_notifies(self):
        fetch = FakeFetch([FLYING], AdsbError("down"))
        service, clock, _ = make(fetch)
        received = []
        service.subscribe(received.append)

        service.process()
        clock.advance(179)
        service.process()
        self.assertFalse(service.snapshot().stale)

        clock.advance(2)
        service.process()
        self.assertTrue(service.snapshot().stale)
        self.assertTrue(received[-1].stale)

    def test_fresh_data_clears_stale(self):
        fetch = FakeFetch([FLYING], AdsbError("a"), AdsbError("b"), AdsbError("c"), [FLYING])
        service, clock, _ = make(fetch)
        service.process()
        for _ in range(3):
            clock.advance(60)
            service.process()
        clock.advance(2)
        service.process()
        self.assertTrue(service.snapshot().stale)

        clock.advance(300)
        service.process()
        self.assertFalse(service.snapshot().stale)

    def test_wait_time_wakes_up_for_the_stale_deadline(self):
        fetch = FakeFetch([FLYING], AdsbError("down"))
        fast = Config(**{**CONFIG.to_dict(), "interval_s": 30})
        service, clock, _ = make(fetch, fast)
        service.process()
        for _ in range(3):
            clock.advance(30)
            wait = service.process()
        self.assertEqual(len(fetch.calls), 4)
        self.assertEqual(service.snapshot().failures, 3)
        self.assertLess(wait, 1.0, "must wake right after the stale deadline, not sleep through the backoff")


class ConfigureTests(unittest.TestCase):
    def test_area_change_discards_data_and_refetches_after_min_gap(self):
        fetch = FakeFetch([FLYING])
        service, clock, _ = make(fetch)
        service.process()

        service.configure(Config(**{**CONFIG.to_dict(), "lat": 19.4326, "lon": -99.1332}))
        self.assertIsNone(service.snapshot().aircraft)

        service.process()
        self.assertEqual(len(fetch.calls), 1, "min gap between requests not elapsed")

        clock.advance(5)
        service.process()
        self.assertEqual(fetch.calls[-1], (19.4326, -99.1332, 100))
        self.assertEqual(service.snapshot().aircraft, (FLYING,))

    def test_radius_change_refetches(self):
        fetch = FakeFetch([FLYING])
        service, clock, _ = make(fetch)
        service.process()
        service.configure(Config(**{**CONFIG.to_dict(), "radius_km": 200}))
        clock.advance(6)
        service.process()
        self.assertEqual(fetch.calls[-1][2], 200)

    def test_same_config_is_a_noop(self):
        service, _, _ = make(FakeFetch([FLYING]))
        service.process()
        version = service.snapshot().version
        service.configure(CONFIG)
        self.assertEqual(service.snapshot().version, version)

    def test_interval_change_reschedules(self):
        fetch = FakeFetch([FLYING])
        service, clock, _ = make(fetch)
        service.process()
        service.configure(Config(**{**CONFIG.to_dict(), "interval_s": 300}))
        clock.advance(120)
        service.process()
        self.assertEqual(len(fetch.calls), 1)
        clock.advance(181)
        service.process()
        self.assertEqual(len(fetch.calls), 2)

    def test_result_is_discarded_if_area_changes_during_the_fetch(self):
        service_box = {}

        def fetch(lat, lon, radius_km):
            service_box["service"].configure(Config(**{**CONFIG.to_dict(), "radius_km": 25}))
            return [FLYING]

        service, clock, _ = make(fetch)
        service_box["service"] = service
        service.process()
        self.assertIsNone(service.snapshot().aircraft)
        self.assertEqual(service.snapshot().config.radius_km, 25)


class FullViewTests(unittest.TestCase):
    def test_full_view_asks_the_api_for_the_corner_radius(self):
        fetch = FakeFetch([FLYING])
        service, _, _ = make(fetch, Config(**{**CONFIG.to_dict(), "view": "full"}))
        service.process()
        self.assertEqual(len(fetch.calls), 1)
        lat, lon, radius = fetch.calls[0]
        self.assertEqual((lat, lon), (CONFIG.lat, CONFIG.lon))
        self.assertAlmostEqual(radius, 100 * 2 ** 0.5)

    def test_switching_view_discards_data_and_refetches_with_the_new_radius(self):
        fetch = FakeFetch([FLYING])
        service, clock, _ = make(fetch)
        service.process()
        self.assertEqual(fetch.calls[-1][2], 100)

        service.configure(Config(**{**CONFIG.to_dict(), "view": "full"}))
        self.assertIsNone(service.snapshot().aircraft)
        clock.advance(6)
        service.process()
        self.assertAlmostEqual(fetch.calls[-1][2], 100 * 2 ** 0.5)
        self.assertEqual(service.snapshot().aircraft, (FLYING,))

        service.configure(Config(**{**CONFIG.to_dict(), "view": "radar"}))
        clock.advance(6)
        service.process()
        self.assertEqual(fetch.calls[-1][2], 100)

    def test_view_change_notifies_subscribers(self):
        service, _, _ = make(FakeFetch([FLYING]))
        received = []
        service.subscribe(received.append)
        service.process()
        service.configure(Config(**{**CONFIG.to_dict(), "view": "full"}))
        service.process()
        self.assertEqual(received[-1].config.view, "full")
        self.assertIsNone(received[-1].aircraft)

    def test_a_result_fetched_for_the_old_view_is_discarded(self):
        box = {}

        def fetch(lat, lon, radius_km):
            box["service"].configure(Config(**{**CONFIG.to_dict(), "view": "full"}))
            return [FLYING]

        service, _, _ = make(fetch)
        box["service"] = service
        service.process()
        self.assertIsNone(service.snapshot().aircraft)
        self.assertEqual(service.snapshot().config.view, "full")


class SubscriberTests(unittest.TestCase):
    def test_failing_subscriber_does_not_break_the_others(self):
        service, _, log = make(FakeFetch([FLYING]))
        received = []

        def broken(snapshot):
            raise RuntimeError("nope")

        service.subscribe(broken)
        service.subscribe(received.append)
        service.process()

        self.assertEqual(len(received), 1)
        self.assertTrue(any("subscriber failed" in message for _, message in log.messages))

    def test_subscribe_is_idempotent_and_unsubscribe_works(self):
        service, clock, _ = make(FakeFetch([FLYING]))
        received = []
        service.subscribe(received.append)
        service.subscribe(received.append)
        service.process()
        self.assertEqual(len(received), 1)

        service.unsubscribe(received.append)
        clock.advance(60)
        service.process()
        self.assertEqual(len(received), 1)

    def test_request_redraw_redelivers_without_a_new_version(self):
        service, _, _ = make(FakeFetch([FLYING]))
        received = []
        service.subscribe(received.append)
        service.process()
        service.request_redraw()
        service.process()
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].version, received[1].version)


class ThreadTests(unittest.TestCase):
    def test_thread_polls_and_stops(self):
        fetch = FakeFetch([FLYING])
        service = RadarService(config=CONFIG, fetch=fetch, logger=Quiet())
        received = []
        service.subscribe(received.append)
        service.start()
        service.start()
        try:
            for _ in range(100):
                if received:
                    break
                time.sleep(0.02)
            self.assertTrue(received)
            self.assertEqual(len(fetch.calls), 1)
        finally:
            service.stop()
        self.assertFalse(service._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
