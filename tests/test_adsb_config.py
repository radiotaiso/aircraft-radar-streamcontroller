import unittest

import requests

from radar import adsb
from radar.config import DEFAULT_LAT, DEFAULT_LON, RADIUS_CHOICES, Config


class ParseTests(unittest.TestCase):
    def test_complete_record(self):
        planes = adsb.parse(
            {
                "ac": [
                    {
                        "hex": "0d0e29",
                        "flight": "AMX363  ",
                        "t": "B38M",
                        "lat": 19.42,
                        "lon": -99.23,
                        "alt_baro": 10425,
                        "gs": 242.0,
                        "track": 179.05,
                    }
                ]
            }
        )
        self.assertEqual(len(planes), 1)
        plane = planes[0]
        self.assertEqual(plane.callsign, "AMX363")
        self.assertEqual(plane.type, "B38M")
        self.assertEqual(plane.alt_ft, 10425)
        self.assertFalse(plane.on_ground)
        self.assertEqual(plane.track, 179.05)

    def test_ground_aircraft_without_track(self):
        plane = adsb.parse(
            {"ac": [{"hex": "0d0ab9", "flight": "XAVTR   ", "lat": 19.39, "lon": -99.24, "alt_baro": "ground", "gs": 0.0}]}
        )[0]
        self.assertTrue(plane.on_ground)
        self.assertEqual(plane.alt_ft, 0)
        self.assertIsNone(plane.track)

    def test_missing_callsign_and_type(self):
        plane = adsb.parse({"ac": [{"hex": "0d06f6", "lat": 20.46, "lon": -103.07, "alt_baro": 32000}]})[0]
        self.assertIsNone(plane.callsign)
        self.assertIsNone(plane.type)

    def test_records_without_position_are_dropped(self):
        planes = adsb.parse(
            {
                "ac": [
                    {"hex": "a", "lat": 1.0},
                    {"hex": "b", "lon": 1.0},
                    {"hex": "c", "lat": None, "lon": None},
                    {"hex": "d", "lat": True, "lon": 1.0},
                    {"hex": "e", "lat": 95.0, "lon": 1.0},
                    {"hex": "f", "lat": 1.0, "lon": 2.0},
                ]
            }
        )
        self.assertEqual([plane.hex for plane in planes], ["f"])

    def test_adsb_fi_payload_uses_the_aircraft_key(self):
        planes = adsb.parse(
            {
                "aircraft": [{"hex": "x", "lat": 1.0, "lon": 2.0, "alt_baro": "ground", "flight": "ABC1"}],
                "now": 1.0,
                "resultCount": 1,
            }
        )
        self.assertEqual([plane.hex for plane in planes], ["x"])
        self.assertTrue(planes[0].on_ground)

    def test_garbage_payloads(self):
        for payload in (None, [], {}, {"ac": None}, {"ac": "x"}, {"ac": [1, "a", None]}, {"aircraft": "x"}):
            self.assertEqual(adsb.parse(payload), [])

    def test_unknown_altitude_is_none(self):
        plane = adsb.parse({"ac": [{"hex": "a", "lat": 1.0, "lon": 2.0}]})[0]
        self.assertIsNone(plane.alt_ft)
        self.assertFalse(plane.on_ground)


class _Response:
    def __init__(self, status=200, payload=None, invalid=False):
        self.status_code = status
        self._payload = payload
        self._invalid = invalid

    def json(self):
        if self._invalid:
            raise ValueError("not json")
        return self._payload


class _Session:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, timeout))
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ClientTests(unittest.TestCase):
    FIXTURE = {"aircraft": [{"hex": "a", "lat": 1.0, "lon": 2.0}]}

    def test_uses_adsb_fi_first_with_the_nautical_radius(self):
        session = _Session(_Response(payload=self.FIXTURE))
        planes = adsb.Client(session=session).fetch(20.6558, -103.3982, 100)
        self.assertEqual([plane.hex for plane in planes], ["a"])
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(
            session.calls[0][0],
            "https://opendata.adsb.fi/api/v2/lat/20.6558/lon/-103.3982/dist/54",
        )

    def test_falls_back_to_adsb_lol(self):
        session = _Session(requests.Timeout("slow"), _Response(payload={"ac": [{"hex": "b", "lat": 1.0, "lon": 2.0}]}))
        planes = adsb.Client(session=session).fetch(1.0, 2.0, 100)
        self.assertEqual([plane.hex for plane in planes], ["b"])
        self.assertEqual(len(session.calls), 2)
        self.assertIn("api.adsb.lol/v2/point/1.0000/2.0000/54", session.calls[1][0])

    def test_falls_back_on_a_rate_limited_primary(self):
        session = _Session(_Response(status=429), _Response(payload={"ac": []}))
        self.assertEqual(adsb.Client(session=session).fetch(1.0, 2.0, 50), [])
        self.assertEqual(len(session.calls), 2)

    def test_falls_back_on_bad_json(self):
        session = _Session(_Response(invalid=True), _Response(payload={"aircraft": []}))
        self.assertEqual(adsb.Client(session=session).fetch(1.0, 2.0, 50), [])

    def test_raises_when_both_endpoints_fail(self):
        session = _Session(_Response(status=500), requests.ConnectionError("down"))
        with self.assertRaises(adsb.AdsbError) as caught:
            adsb.Client(session=session).fetch(1.0, 2.0, 50)
        self.assertIn("ConnectionError", str(caught.exception))
        self.assertEqual(len(session.calls), 2)

    def test_timeout_is_passed_to_requests(self):
        session = _Session(_Response(payload={"aircraft": []}))
        adsb.Client(timeout=15.0, session=session).fetch(1.0, 2.0, 50)
        self.assertEqual(session.calls[0][1], 15.0)


class KmToNmTests(unittest.TestCase):
    def test_conversion(self):
        self.assertEqual(adsb.km_to_nm(100), 54)
        self.assertEqual(adsb.km_to_nm(200), 108)

    def test_clamp(self):
        self.assertEqual(adsb.km_to_nm(0), 1)
        self.assertEqual(adsb.km_to_nm(10000), 250)


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = Config.from_dict({})
        self.assertEqual((cfg.lat, cfg.lon), (DEFAULT_LAT, DEFAULT_LON))
        self.assertEqual(cfg.radius_km, 100)
        self.assertEqual(cfg.interval_s, 60)
        self.assertTrue(cfg.hide_ground)
        self.assertTrue(cfg.show_map)

    def test_ignores_foreign_keys(self):
        cfg = Config.from_dict({"first-setup": False, "radius_km": 150})
        self.assertEqual(cfg.radius_km, 150)

    def test_radius_snaps_to_nearest_choice(self):
        self.assertEqual(Config.from_dict({"radius_km": 80}).radius_km, 100)
        self.assertEqual(Config.from_dict({"radius_km": 10}).radius_km, 25)
        self.assertEqual(Config.from_dict({"radius_km": 999}).radius_km, 200)

    def test_bad_types_fall_back(self):
        cfg = Config.from_dict(
            {"lat": "x", "lon": None, "radius_km": "far", "interval_s": True, "hide_ground": "yes", "show_map": 1}
        )
        self.assertEqual(
            (cfg.lat, cfg.lon, cfg.radius_km, cfg.interval_s, cfg.hide_ground, cfg.show_map),
            (DEFAULT_LAT, DEFAULT_LON, 100, 60, True, True),
        )

    def test_view_defaults_to_radar(self):
        cfg = Config.from_dict({})
        self.assertEqual(cfg.view, "radar")
        self.assertFalse(cfg.full)

    def test_view_accepts_only_known_values(self):
        self.assertEqual(Config.from_dict({"view": "full"}).view, "full")
        self.assertTrue(Config.from_dict({"view": "full"}).full)
        for bad in ("square", "FULL", "", None, 1, True, ["full"]):
            self.assertEqual(Config.from_dict({"view": bad}).view, "radar", bad)

    def test_fetch_radius_is_the_radius_in_radar_view(self):
        self.assertEqual(Config(radius_km=100).fetch_radius_km, 100)

    def test_fetch_radius_reaches_the_corners_in_full_view(self):
        for radius in RADIUS_CHOICES:
            cfg = Config(radius_km=radius, view="full")
            self.assertAlmostEqual(cfg.fetch_radius_km, radius * 2 ** 0.5, places=9)
            self.assertLessEqual(adsb.km_to_nm(cfg.fetch_radius_km), 250)

    def test_full_view_fetch_radius_covers_the_square(self):
        cfg = Config(radius_km=200, view="full")
        corner = (200 ** 2 + 200 ** 2) ** 0.5
        self.assertGreaterEqual(cfg.fetch_radius_km, corner - 1e-9)

    def test_count_corner_defaults_to_bottom_right(self):
        self.assertEqual(Config.from_dict({}).count_corner, "bottom-right")

    def test_count_corner_accepts_only_the_four_outer_corners(self):
        for corner in ("bottom-right", "bottom-left", "top-right", "top-left"):
            self.assertEqual(Config.from_dict({"count_corner": corner}).count_corner, corner)
        for bad in ("bottom", "center", "BOTTOM-RIGHT", "", None, 3, True, ["top-left"]):
            self.assertEqual(Config.from_dict({"count_corner": bad}).count_corner, "bottom-right", bad)

    def test_colored_defaults_to_true_and_can_be_turned_off(self):
        self.assertTrue(Config.from_dict({}).colored)
        self.assertFalse(Config.from_dict({"colored": False}).colored)
        for bad in ("no", 0, 1, None, [], {}):
            self.assertTrue(Config.from_dict({"colored": bad}).colored, bad)

    def test_units_default_to_nautical_miles(self):
        self.assertEqual(Config.from_dict({}).units, "nm")

    def test_units_accept_only_known_values(self):
        for unit in ("nm", "km", "mi"):
            self.assertEqual(Config.from_dict({"units": unit}).units, unit)
        for bad in ("NM", "miles", "kilometers", "", None, 1, True, ["km"]):
            self.assertEqual(Config.from_dict({"units": bad}).units, "nm", bad)

    def test_show_map_can_be_turned_off(self):
        self.assertFalse(Config.from_dict({"show_map": False}).show_map)

    def test_ranges_are_clamped(self):
        cfg = Config.from_dict({"lat": 120, "lon": -400, "interval_s": 5})
        self.assertEqual((cfg.lat, cfg.lon, cfg.interval_s), (90.0, -180.0, 30))

    def test_non_dict_input(self):
        self.assertEqual(Config.from_dict(None), Config())

    def test_next_radius_cycles(self):
        radius = RADIUS_CHOICES[0]
        seen = []
        for _ in range(len(RADIUS_CHOICES) + 1):
            seen.append(radius)
            radius = Config(radius_km=radius).next_radius()
        self.assertEqual(seen, list(RADIUS_CHOICES) + [RADIUS_CHOICES[0]])

    def test_roundtrip(self):
        cfg = Config(
            lat=19.4326,
            lon=-99.1332,
            radius_km=50,
            interval_s=90,
            hide_ground=False,
            show_map=False,
            view="full",
            count_corner="top-left",
            colored=False,
            units="mi",
        )
        self.assertEqual(Config.from_dict(cfg.to_dict()), cfg)


if __name__ == "__main__":
    unittest.main()
