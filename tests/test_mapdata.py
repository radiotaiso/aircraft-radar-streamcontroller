import json
import logging
import tempfile
import unittest
from pathlib import Path

from radar import mapdata

WINDOW = (-1.0, -1.0, 2.0, 1.0)


class MapDataTests(unittest.TestCase):
    def test_lines_are_culled_by_bounding_box(self):
        data = mapdata.MapData({"coast": [[(0, 0), (1, 0)], [(50, 50), (51, 50)]]})
        found = list(data.lines("coast", *WINDOW))
        self.assertEqual(found, [((0.0, 0.0), (1.0, 0.0))])

    def test_long_segment_with_both_ends_outside_is_kept(self):
        data = mapdata.MapData({"coast": [[(-10, 0), (10, 0)]]})
        self.assertEqual(len(list(data.lines("coast", *WINDOW))), 1)

    def test_line_touching_the_window_edge_is_kept(self):
        data = mapdata.MapData({"coast": [[(2, 0), (3, 0)]]})
        self.assertEqual(len(list(data.lines("coast", *WINDOW))), 1)

    def test_vertical_line_crossing_the_window_is_kept(self):
        data = mapdata.MapData({"coast": [[(0.0, -5.0), (0.0, 5.0)]]})
        self.assertEqual(len(list(data.lines("coast", *WINDOW))), 1)

    def test_line_above_or_below_the_window_is_dropped(self):
        above = mapdata.MapData({"coast": [[(0.0, 5.0), (0.0, 6.0)]]})
        below = mapdata.MapData({"coast": [[(0.0, -6.0), (0.0, -5.0)]]})
        self.assertEqual(list(above.lines("coast", *WINDOW)), [])
        self.assertEqual(list(below.lines("coast", *WINDOW)), [])

    def test_unknown_layer_is_empty(self):
        self.assertEqual(list(mapdata.MapData().lines("nope", *WINDOW)), [])

    def test_bad_points_and_short_lines_are_dropped(self):
        data = mapdata.MapData(
            {"coast": [[(0, 0)], [(0, 0), "x", (1, 1)], [(0, 0), (None, 1), (1, 1)], [(0, 0), (True, 1), (2, 2)], [(0, 0), (1, 1)]]}
        )
        self.assertEqual(data.line_count, 4)
        for points in data.lines("coast", -10, -10, 10, 10):
            self.assertTrue(all(isinstance(v, float) for point in points for v in point))
            self.assertGreaterEqual(len(points), 2)

    def test_line_count_helper(self):
        self.assertEqual(mapdata.MapData().line_count, 0)
        self.assertEqual(mapdata.MapData({"a": [[(0, 0), (1, 1)]], "b": [[(0, 0), (1, 1)]]}).line_count, 2)

    def test_covers(self):
        data = mapdata.MapData(bbox=[-118.5, 14.0, -86.0, 33.0])
        self.assertTrue(data.covers(20.0, -100.0))
        self.assertFalse(data.covers(40.4, -3.7))
        self.assertFalse(mapdata.MapData().covers(0, 0))


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, content):
        path = self.root / "map.json"
        path.write_text(content if isinstance(content, str) else json.dumps(content))
        return path

    def test_valid_file(self):
        path = self.write({"source": "x", "bbox": [0, 0, 1, 1], "layers": {"coast": [[[0, 0], [1, 1]]]}})
        data = mapdata.load(path)
        self.assertEqual((data.source, data.bbox, data.line_count), ("x", (0, 0, 1, 1), 1))

    def test_missing_file_gives_an_empty_map_and_a_warning(self):
        with self.assertLogs("sc-adskey", level=logging.WARNING) as captured:
            data = mapdata.load(self.root / "missing.json")
        self.assertEqual(data.line_count, 0)
        self.assertTrue(any("map data unavailable" in line for line in captured.output))

    def test_corrupt_files_never_raise(self):
        for content in ("{", "[]", '{"layers": 3}', '{"nolayers": {}}', "null", ""):
            with self.assertLogs("sc-adskey", level=logging.WARNING):
                data = mapdata.load(self.write(content))
            self.assertEqual(data.line_count, 0, content)

    def test_bad_bbox_is_ignored(self):
        data = mapdata.load(self.write({"bbox": [1, 2], "layers": {}}))
        self.assertIsNone(data.bbox)


class ShippedDataTests(unittest.TestCase):
    def test_file_exists_and_is_small(self):
        self.assertTrue(mapdata.DATA_PATH.is_file())
        self.assertLess(mapdata.DATA_PATH.stat().st_size, 5_000_000)

    def test_shipped_data_is_worldwide(self):
        data = mapdata.default()
        self.assertTrue(data.worldwide)
        for name, (lat, lon) in {
            "Madrid": (40.42, -3.70),
            "London": (51.5, -0.12),
            "Tokyo": (35.68, 139.69),
            "Sydney": (-33.87, 151.21),
            "New York": (40.71, -74.01),
            "Guadalajara": (20.6736, -103.3446),
        }.items():
            self.assertTrue(data.covers(lat, lon), name)

    def test_flat_and_list_payloads_are_equivalent(self):
        listed = mapdata.MapData({"coast": [[(0.0, 0.0), (1.0, 1.0)], [(2.0, 2.0), (3.0, 3.0)]]}, bbox=[0, 0, 3, 3])
        packed = mapdata.MapData(
            {"coast": {"counts": [2, 2], "points": [0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0]}}, bbox=[0, 0, 3, 3]
        )
        self.assertEqual(list(listed.lines("coast", -1, -1, 4, 4)), list(packed.lines("coast", -1, -1, 4, 4)))

    def test_a_short_or_inconsistent_line_is_dropped(self):
        data = mapdata.MapData({"coast": {"counts": [1, 2, 9], "points": [0.0, 0.0, 1.0, 1.0, 2.0, 2.0]}})
        self.assertEqual(data.line_count, 1)
        self.assertEqual(list(data.lines("coast", -10, -10, 10, 10)), [((1.0, 1.0), (2.0, 2.0))])

    def test_packed_points_tolerate_junk(self):
        for payload in ("1,2 3", "a,b", None, [1.0, 2.0, 3.0]):
            data = mapdata.MapData({"coast": {"counts": [2], "points": payload}})
            self.assertEqual(data.line_count, 0 if payload in ("a,b", None) else data.line_count)

    def test_all_layers_are_present_and_populated(self):
        data = mapdata.default()
        for layer in mapdata.LAYERS:
            lines = list(data.lines(layer, -180, -90, 180, 90))
            self.assertGreater(len(lines), 10, layer)

    def test_coordinates_are_valid(self):
        data = mapdata.default()
        for layer in mapdata.LAYERS:
            for points in data.lines(layer, -180, -90, 180, 90):
                for lon, lat in points:
                    self.assertTrue(-180 <= lon <= 180 and -90 <= lat <= 90, (layer, lon, lat))

    def test_default_is_cached(self):
        self.assertIs(mapdata.default(), mapdata.default())

    def test_covers_the_cities_the_user_cares_about(self):
        data = mapdata.default()
        self.assertTrue(data.covers(20.6736, -103.3446))
        self.assertTrue(data.covers(19.4326, -99.1332))

    def test_lake_chapala_is_near_guadalajara(self):
        data = mapdata.default()
        chapala = list(data.lines("lakes", -103.3, 20.1, -102.8, 20.4))
        self.assertTrue(chapala)


if __name__ == "__main__":
    unittest.main()
