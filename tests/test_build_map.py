import importlib.util
import math
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("build_map", Path(__file__).resolve().parent.parent / "scripts" / "build_map.py")
build_map = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_map)

BOX = (0.0, 0.0, 10.0, 10.0)


class SimplifyTests(unittest.TestCase):
    def test_collinear_points_collapse_to_the_endpoints(self):
        line = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
        self.assertEqual(build_map.simplify(line, 0.01), [(0.0, 0.0), (3.0, 0.0)])

    def test_features_larger_than_the_tolerance_survive(self):
        line = [(0.0, 0.0), (1.0, 0.5), (2.0, 0.0)]
        self.assertEqual(build_map.simplify(line, 0.1), line)
        self.assertEqual(build_map.simplify(line, 1.0), [(0.0, 0.0), (2.0, 0.0)])

    def test_endpoints_are_always_kept(self):
        line = [(0.0, 0.0), (1.0, 0.001), (2.0, 0.0), (3.0, 0.002), (4.0, 0.0)]
        result = build_map.simplify(line, 0.5)
        self.assertEqual((result[0], result[-1]), (line[0], line[-1]))

    def test_closed_rings_stay_closed_and_keep_their_shape(self):
        ring = [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]
        result = build_map.simplify([(float(x), float(y)) for x, y in ring], 0.1)
        self.assertEqual(result[0], result[-1])
        self.assertGreaterEqual(len(result), 4)
        self.assertEqual({p for p in result}, {(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)})

    def test_short_inputs_are_returned_as_is(self):
        self.assertEqual(build_map.simplify([(0.0, 0.0), (1.0, 1.0)], 0.5), [(0.0, 0.0), (1.0, 1.0)])
        self.assertEqual(build_map.simplify([], 0.5), [])

    def test_long_noisy_line_does_not_overflow_the_stack(self):
        line = [(i * 0.001, math.sin(i) * 0.0001) for i in range(20000)]
        self.assertLess(len(build_map.simplify(line, 0.01)), 50)

    def test_result_stays_within_tolerance_of_the_original(self):
        line = [(i * 0.1, math.sin(i * 0.1)) for i in range(200)]
        tolerance = 0.05
        result = build_map.simplify(line, tolerance)
        for point in line:
            nearest = min(
                build_map._distance_to_segment(point, a, b) for a, b in zip(result, result[1:])
            )
            self.assertLessEqual(nearest, tolerance + 1e-9)


class ClipTests(unittest.TestCase):
    def test_line_fully_outside_is_dropped(self):
        self.assertEqual(build_map.clip_line([(20.0, 20.0), (21.0, 21.0)], BOX), [])

    def test_line_fully_inside_is_kept_whole(self):
        line = [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]
        self.assertEqual(build_map.clip_line(line, BOX), [line])

    def test_crossing_line_keeps_one_outside_neighbour_on_each_side(self):
        line = [(-5.0, 5.0), (-1.0, 5.0), (3.0, 5.0), (12.0, 5.0), (30.0, 5.0)]
        self.assertEqual(build_map.clip_line(line, BOX), [[(-1.0, 5.0), (3.0, 5.0), (12.0, 5.0)]])

    def test_line_that_leaves_for_a_long_stretch_and_comes_back_is_split(self):
        line = [(1.0, 1.0), (2.0, 2.0), (30.0, 30.0), (45.0, 45.0), (60.0, 60.0), (4.0, 4.0), (5.0, 5.0)]
        runs = build_map.clip_line(line, BOX)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0], [(1.0, 1.0), (2.0, 2.0), (30.0, 30.0)])
        self.assertEqual(runs[1], [(60.0, 60.0), (4.0, 4.0), (5.0, 5.0)])

    def test_a_short_excursion_stays_in_one_run(self):
        line = [(1.0, 1.0), (2.0, 2.0), (30.0, 30.0), (60.0, 60.0), (4.0, 4.0), (5.0, 5.0)]
        self.assertEqual(build_map.clip_line(line, BOX), [line])

    def test_single_point_runs_are_dropped(self):
        self.assertEqual(build_map.clip_line([(5.0, 5.0)], BOX), [])


class QuantizeTests(unittest.TestCase):
    def test_rounds_and_removes_consecutive_duplicates(self):
        line = [(1.00001, 2.00001), (1.00002, 2.00003), (1.5, 2.5)]
        self.assertEqual(build_map.quantize(line, 3), [(1.0, 2.0), (1.5, 2.5)])


class ProcessTests(unittest.TestCase):
    def test_pipeline_clips_simplifies_and_drops_degenerate_lines(self):
        lines = [
            [[1, 1], [2, 1], [3, 1], [4, 1]],
            [[50, 50], [51, 51]],
            [[5, 5], [5.0001, 5.0001]],
        ]
        result = build_map.process(lines, BOX, 0.01)
        self.assertEqual(result, [[(1.0, 1.0), (4.0, 1.0)]])

    def test_extra_coordinate_dimensions_are_ignored(self):
        self.assertEqual(build_map.process([[[1, 1, 100], [2, 2, 200]]], BOX, 0.01), [[(1.0, 1.0), (2.0, 2.0)]])


class FlattenTests(unittest.TestCase):
    def test_two_numbers_per_point_and_a_count_per_line(self):
        packed = build_map.flatten([[(0.0, 0.0), (1.5, -2.5)], [(3.0, 4.0), (5.0, 6.0), (7.0, 8.0)]], 2)
        self.assertEqual(packed["counts"], [2, 3])
        self.assertEqual(len(packed["points"]), 2 * 5)
        self.assertEqual(packed["points"][:4], [0.0, 0.0, 1.5, -2.5])

    def test_flatten_roundtrips_through_mapdata(self):
        from radar import mapdata

        lines = [[(0.0, 0.0), (1.0, 1.0)], [(2.0, 2.0), (3.0, 3.0)]]
        listed = mapdata.MapData({"coast": lines}, bbox=[0, 0, 3, 3])
        packed = mapdata.MapData({"coast": build_map.flatten(lines, 2)}, bbox=[0, 0, 3, 3])
        self.assertEqual(listed.line_count, packed.line_count)
        self.assertEqual(list(listed.lines("coast", -1, -1, 4, 4)), list(packed.lines("coast", -1, -1, 4, 4)))


class GeometryTests(unittest.TestCase):
    def test_iter_lines_handles_every_geometry_type(self):
        line = [[0, 0], [1, 1]]
        self.assertEqual(list(build_map.iter_lines({"type": "LineString", "coordinates": line})), [line])
        self.assertEqual(list(build_map.iter_lines({"type": "MultiLineString", "coordinates": [line, line]})), [line, line])
        self.assertEqual(list(build_map.iter_lines({"type": "Polygon", "coordinates": [line]})), [line])
        self.assertEqual(list(build_map.iter_lines({"type": "MultiPolygon", "coordinates": [[line], [line, line]]})), [line] * 3)
        self.assertEqual(list(build_map.iter_lines({"type": "Point", "coordinates": [0, 0]})), [])
        self.assertEqual(list(build_map.iter_lines(None)), [])


if __name__ == "__main__":
    unittest.main()
