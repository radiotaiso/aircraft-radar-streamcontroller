import math
import random
import unittest

from PIL import Image, ImageChops, ImageDraw, ImageStat

from radar import mapdata, render
from radar.adsb import Aircraft

CENTER = (0.0, 0.0)


def at_offset(north_km=0.0, east_km=0.0, **kwargs):
    return Aircraft(
        hex=kwargs.pop("hex", "t"),
        lat=CENTER[0] + north_km / render.KM_PER_DEG_LAT,
        lon=CENTER[1] + east_km / (render.KM_PER_DEG_LON * math.cos(math.radians(CENTER[0]))),
        **kwargs,
    )


def is_greyscale(image):
    px = image.convert("RGB").load()
    return all(px[x, y][0] == px[x, y][1] == px[x, y][2] for x in range(image.width) for y in range(image.height))


def lit_pixels(image):
    pixels = image.convert("L").load()
    return {(x, y) for x in range(image.width) for y in range(image.height) if pixels[x, y] > 0}


class ProjectionTests(unittest.TestCase):
    def test_center_maps_to_center(self):
        self.assertEqual(render.to_pixels(*CENTER, CENTER, 100, 72), (36, 36))

    def test_north_is_up_east_is_right(self):
        north = render.to_pixels(CENTER[0] + 0.3, CENTER[1], CENTER, 100, 72)
        east = render.to_pixels(CENTER[0], CENTER[1] + 0.3, CENTER, 100, 72)
        self.assertLess(north[1], 36)
        self.assertEqual(north[0], 36)
        self.assertGreater(east[0], 36)
        self.assertEqual(east[1], 36)

    def test_edge_scales_to_ring(self):
        x, y = render.to_pixels(CENTER[0], CENTER[1] + 0.8, CENTER, 100, 72)
        self.assertAlmostEqual(x - 36, render.radar_radius_px(72) * (0.8 * 111.32 * math.cos(math.radians(CENTER[0])) / 100), delta=1)

    def test_out_of_range_is_none(self):
        self.assertIsNone(render.to_pixels(CENTER[0] + 2.0, CENTER[1], CENTER, 100, 72))

    def test_mosaic_scales_with_size(self):
        small = render.to_pixels(CENTER[0] + 0.3, CENTER[1], CENTER, 100, 72)
        big = render.to_pixels(CENTER[0] + 0.3, CENTER[1], CENTER, 100, 144)
        self.assertEqual(big[1] - 72, round((small[1] - 36) * 70 / 34))


class RenderTests(unittest.TestCase):
    def test_sizes_and_mode(self):
        for size in (72, 144):
            image = render.render_radar([], CENTER, 100, size)
            self.assertEqual(image.size, (size, size))
            self.assertEqual(image.mode, "RGB")

    def test_states_are_distinguishable(self):
        planes = [at_offset(north_km=20, east_km=10, track=90.0)]
        frames = {
            "waiting": render.render_radar(None, CENTER, 100, 72),
            "empty": render.render_radar([], CENTER, 100, 72),
            "fresh": render.render_radar(planes, CENTER, 100, 72),
            "stale": render.render_radar(planes, CENTER, 100, 72, stale=True),
            "warning": render.render_warning(72),
        }
        blobs = {name: image.tobytes() for name, image in frames.items()}
        self.assertEqual(len(set(blobs.values())), len(blobs))

    def test_empty_is_not_blank(self):
        self.assertGreater(len(lit_pixels(render.render_radar([], CENTER, 100, 72))), 50)

    def test_nearest_gets_5x5_marker(self):
        near = at_offset(east_km=15)
        far = at_offset(north_km=60)
        image = render.render_radar([far, near], CENTER, 100, 72, show_count=False)
        lit = lit_pixels(image)
        nx, ny = render.to_pixels(near.lat, near.lon, CENTER, 100, 72)
        fx, fy = render.to_pixels(far.lat, far.lon, CENTER, 100, 72)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                self.assertIn((nx + dx, ny + dy), lit)
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                self.assertIn((fx + dx, fy + dy), lit)

    def test_nothing_drawn_outside_the_ring(self):
        rng = random.Random(7)
        planes = []
        for index in range(60):
            planes.append(
                at_offset(
                    north_km=rng.uniform(-150, 150),
                    east_km=rng.uniform(-150, 150),
                    track=rng.choice([None, rng.uniform(0, 360)]),
                    hex=f"p{index}",
                )
            )
        for size in (72, 144):
            image = render.render_radar(planes, CENTER, 100, size, show_count=False)
            limit = render.radar_radius_px(size) + 1.5
            half = size // 2
            for x, y in lit_pixels(image):
                self.assertLessEqual(math.hypot(x - half, y - half), limit, (x, y, size))

    def test_aircraft_at_the_edge_stay_inside(self):
        plane = at_offset(east_km=99, track=90.0)
        image = render.render_radar([plane], CENTER, 100, 72, show_count=False)
        for x, y in lit_pixels(image):
            self.assertLessEqual(math.hypot(x - 36, y - 36), render.radar_radius_px(72) + 1.5)

    def test_count_counts_only_what_is_in_range(self):
        inside = at_offset(east_km=10)
        outside = at_offset(east_km=500)
        with_outside = render.render_radar([inside, outside], CENTER, 100, 72)
        only_inside = render.render_radar([inside], CENTER, 100, 72)
        self.assertEqual(with_outside.tobytes(), only_inside.tobytes())

    def test_heading_tail_follows_track(self):
        base = at_offset(east_km=15)
        east = Aircraft(hex="e", lat=base.lat, lon=base.lon, track=90.0)
        north = Aircraft(hex="n", lat=base.lat, lon=base.lon, track=0.0)
        east_img = render.render_radar([east], CENTER, 100, 72, show_count=False, max_icons=0)
        north_img = render.render_radar([north], CENTER, 100, 72, show_count=False, max_icons=0)
        self.assertNotEqual(east_img.tobytes(), north_img.tobytes())
        px, py = render.to_pixels(base.lat, base.lon, CENTER, 100, 72)
        self.assertIn((px + 4, py), lit_pixels(east_img))
        self.assertIn((px, py - 4), lit_pixels(north_img))

    def test_mosaic_has_diamond_origin(self):
        lit = lit_pixels(render.render_radar([], CENTER, 100, 144, show_count=False))
        for offset in ((0, -3), (3, 0), (0, 3), (-3, 0), (0, 0)):
            self.assertIn((72 + offset[0], 72 + offset[1]), lit)

    def test_scope_has_small_cross_origin(self):
        lit = lit_pixels(render.render_radar([], CENTER, 100, 72, show_count=False))
        for offset in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            self.assertIn((36 + offset[0], 36 + offset[1]), lit)

    def test_count_text_only_when_requested(self):
        planes = [at_offset(east_km=10)]
        with_count = render.render_radar(planes, CENTER, 100, 72, show_count=True)
        without = render.render_radar(planes, CENTER, 100, 72, show_count=False)
        self.assertNotEqual(with_count.tobytes(), without.tobytes())


def synthetic_map(*lines, layer="coast"):
    return mapdata.MapData({layer: [list(line) for line in lines]})


def horizontal_line(lat, span=2.0):
    return [(CENTER[1] - span, lat), (CENTER[1] + span, lat)]


class MapLayerTests(unittest.TestCase):
    def test_map_line_is_drawn_dim_and_inside_the_ring_only(self):
        data = synthetic_map(horizontal_line(CENTER[0]))
        image = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=True, map_data=data)
        pixels = image.convert("L").load()
        self.assertEqual(pixels[20, 36], 130)
        self.assertEqual(pixels[52, 36], 130)
        self.assertEqual(pixels[0, 36], 0)
        self.assertEqual(pixels[1, 36], 0)
        self.assertEqual(pixels[71, 36], 0)

    def test_without_map_nothing_is_drawn_there(self):
        image = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=False)
        self.assertEqual(image.convert("L").getpixel((20, 36)), 0)

    def test_layers_have_distinct_dim_levels_below_the_ring(self):
        levels = dict(render.MAP_LEVELS)
        self.assertEqual(len(set(levels.values())), 4)
        self.assertLess(max(levels.values()), 255)
        for layer, level in levels.items():
            data = synthetic_map(horizontal_line(CENTER[0]), layer=layer)
            image = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=True, map_data=data)
            self.assertEqual(image.convert("L").getpixel((20, 36)), level, layer)

    def test_coast_draws_over_urban(self):
        data = mapdata.MapData({"urban": [horizontal_line(CENTER[0])], "coast": [horizontal_line(CENTER[0])]})
        image = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=True, map_data=data)
        self.assertEqual(image.convert("L").getpixel((20, 36)), 130)

    def test_far_lines_are_skipped(self):
        data = synthetic_map(horizontal_line(CENTER[0] + 40))
        with_map = render.render_radar([], CENTER, 100, 72, show_map=True, map_data=data)
        empty_map = render.render_radar([], CENTER, 100, 72, show_map=True, map_data=synthetic_map())
        self.assertEqual(with_map.tobytes(), empty_map.tobytes())

    def test_long_segment_with_both_ends_outside_still_crosses_the_disc(self):
        data = synthetic_map([(CENTER[1] - 30, CENTER[0]), (CENTER[1] + 30, CENTER[0])])
        image = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=True, map_data=data)
        self.assertEqual(image.convert("L").getpixel((20, 36)), 130)

    def test_map_does_not_leak_between_renders(self):
        data = synthetic_map(horizontal_line(CENTER[0]))
        first = render.render_radar([], CENTER, 100, 72, show_map=True, map_data=data)
        render.render_radar([at_offset(east_km=10, track=45.0)], CENTER, 100, 72, show_map=True, map_data=data)
        again = render.render_radar([], CENTER, 100, 72, show_map=True, map_data=data)
        self.assertEqual(first.tobytes(), again.tobytes())

    def test_map_scales_with_radius(self):
        offset_deg = 0.2
        data = synthetic_map(horizontal_line(CENTER[0] + offset_deg))
        rows = {}
        for radius in (50, 100):
            image = render.render_radar([], CENTER, radius, 72, show_count=False, show_map=True, map_data=data).convert("L")
            lit_rows = [y for y in range(72) if image.getpixel((36, y)) == 130]
            self.assertEqual(len(lit_rows), 1, (radius, lit_rows))
            rows[radius] = lit_rows[0]
            expected = 36 - offset_deg * render.KM_PER_DEG_LAT / radius * render.radar_radius_px(72)
            self.assertAlmostEqual(rows[radius], expected, delta=1.0)
        self.assertLess(rows[50], rows[100])

    def test_map_in_the_mosaic_uses_the_larger_canvas(self):
        data = synthetic_map(horizontal_line(CENTER[0]))
        image = render.render_radar([], CENTER, 100, 144, show_count=False, show_map=True, map_data=data)
        self.assertEqual(image.size, (144, 144))
        self.assertEqual(image.convert("L").getpixel((30, 72)), 130)

    def test_guides_are_dropped_when_the_map_is_on(self):
        plain = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=False)
        mapped = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=True, map_data=synthetic_map())
        self.assertNotEqual(plain.tobytes(), mapped.tobytes())
        self.assertGreater(len(lit_pixels(plain)), len(lit_pixels(mapped)))

    def test_center_outside_the_map_coverage_still_renders(self):
        data = mapdata.MapData({"coast": [[(0.0, 0.0), (1.0, 1.0)]]}, bbox=[0, 0, 1, 1])
        image = render.render_radar([at_offset(east_km=10)], CENTER, 100, 72, show_map=True, map_data=data)
        self.assertEqual(image.size, (72, 72))

    def test_shipped_map_has_content_around_guadalajara_and_cdmx(self):
        data = mapdata.default()
        self.assertGreater(data.line_count, 500)
        for center in (
            (20.6736, -103.3446),
            (19.4326, -99.1332),
            (25.68, -100.31),
            (32.5, -117.0),
            (40.42, -3.70),
            (51.5, -0.12),
            (35.68, 139.69),
            (-33.87, 151.21),
            (40.71, -74.01),
        ):
            self.assertTrue(data.covers(*center), center)
            frame = render.render_radar([], center, 200, 144, show_count=False, show_map=True)
            plain = render.render_radar([], center, 200, 144, show_count=False, show_map=False)
            self.assertGreater(len(lit_pixels(frame)), len(lit_pixels(plain)) // 2, center)
            self.assertNotEqual(frame.tobytes(), plain.tobytes(), center)

    def test_shipped_map_stays_inside_the_ring(self):
        for size in (72, 144):
            image = render.render_radar([], CENTER, 200, size, show_count=False, show_map=True)
            half = size // 2
            for x, y in lit_pixels(image):
                self.assertLessEqual(math.hypot(x - half, y - half), render.radar_radius_px(size) + 1.5)


class IconTests(unittest.TestCase):
    def test_budget_and_size_by_canvas(self):
        self.assertEqual((render.icon_budget(72), render.icon_px(72)), (5, 8))
        self.assertEqual((render.icon_budget(144), render.icon_px(144)), (12, 10))

    def test_nose_faces_the_direction_of_travel(self):
        def extremes(track):
            stamp = render._plane_icon(track, 10)[0]
            lit = {(x, y) for x in range(stamp.width) for y in range(stamp.height) if stamp.getpixel((x, y)) > 100}
            xs = [x for x, _ in lit]
            ys = [y for _, y in lit]
            return {
                "top": sum(1 for _, y in lit if y == min(ys)),
                "bottom": sum(1 for _, y in lit if y == max(ys)),
                "left": sum(1 for x, _ in lit if x == min(xs)),
                "right": sum(1 for x, _ in lit if x == max(xs)),
            }

        north, south, east, west = extremes(0), extremes(180), extremes(90), extremes(270)
        self.assertLess(north["top"], north["bottom"])
        self.assertLess(south["bottom"], south["top"])
        self.assertLess(east["right"], east["left"])
        self.assertLess(west["left"], west["right"])

    def test_east_is_north_rotated_a_quarter_turn(self):
        north = render._plane_icon(0, 10)[0]
        east = render._plane_icon(90, 10)[0]
        diff = ImageChops.difference(east, north.rotate(-90))
        self.assertLess(ImageStat.Stat(diff).mean[0], 8)

    def test_icon_box_is_odd_so_it_centres_on_a_pixel(self):
        for px in (8, 9, 10, 11):
            self.assertEqual(render._plane_icon(0, px)[0].width % 2, 1, px)

    def test_track_is_bucketed_to_five_degrees(self):
        render._plane_icon.cache_clear()
        for track in (88.0, 89.0, 90.0, 91.0, 92.0):
            render.render_radar([at_offset(east_km=15, track=track)], CENTER, 100, 72)
        self.assertEqual(render._plane_icon.cache_info().misses, 1)
        render.render_radar([at_offset(east_km=15, track=95.0)], CENTER, 100, 72)
        self.assertEqual(render._plane_icon.cache_info().misses, 2)

    def test_track_wraps_around_north(self):
        render._plane_icon.cache_clear()
        render.render_radar([at_offset(east_km=15, track=359.0)], CENTER, 100, 72)
        render.render_radar([at_offset(east_km=15, track=1.0)], CENTER, 100, 72)
        self.assertEqual(render._plane_icon.cache_info().misses, 1)

    def test_icons_replace_squares_within_the_budget(self):
        plane = at_offset(east_km=15, track=0.0)
        icon = render.render_radar([plane], CENTER, 100, 72, show_count=False)
        square = render.render_radar([plane], CENTER, 100, 72, show_count=False, max_icons=0)
        self.assertNotEqual(icon.tobytes(), square.tobytes())
        x, y = render.to_pixels(plane.lat, plane.lon, CENTER, 100, 72)
        self.assertTrue(all((x + dx, y + dy) in lit_pixels(square) for dx in range(-2, 3) for dy in range(-2, 3)))
        self.assertLess(len({(x + dx, y + dy) for dx in range(-2, 3) for dy in range(-2, 3)} & lit_pixels(icon)), 25)

    def test_planes_past_the_budget_fall_back_to_3x3_squares(self):
        planes = []
        for index in range(7):
            bearing = math.radians(index * 51)
            distance = 50 + 8 * index
            planes.append(
                at_offset(north_km=distance * math.cos(bearing), east_km=distance * math.sin(bearing), track=90.0, hex=f"p{index}")
            )
        image = render.render_radar(planes, CENTER, 100, 72, show_count=False)
        lit = lit_pixels(image)
        for plane in planes[5:]:
            fx, fy = render.to_pixels(plane.lat, plane.lon, CENTER, 100, 72)
            fx, fy = render._clamp_to_disc(fx, fy, 36, 36, render.radar_radius_px(72) - 2)
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    self.assertIn((fx + dx, fy + dy), lit, plane.hex)
            surround = {(fx + dx, fy + dy) for dx in range(-2, 3) for dy in range(-2, 3)} - {
                (fx + dx, fy + dy) for dx in range(-1, 2) for dy in range(-1, 2)
            }
            self.assertLessEqual(len(surround & lit), 3, plane.hex)

    def test_aircraft_without_track_stay_squares_even_when_nearest(self):
        plane = at_offset(east_km=15)
        image = render.render_radar([plane], CENTER, 100, 72, show_count=False)
        square = render.render_radar([plane], CENTER, 100, 72, show_count=False, max_icons=0)
        self.assertEqual(image.tobytes(), square.tobytes())

    def test_nearest_is_drawn_on_top_of_farther_icons(self):
        near = at_offset(east_km=10, track=0.0, hex="near")
        far = at_offset(east_km=11, track=180.0, hex="far")
        together = render.render_radar([far, near], CENTER, 100, 72, show_count=False).convert("L")
        alone = render.render_radar([near], CENTER, 100, 72, show_count=False).convert("L")
        self.assertNotEqual(together.tobytes(), alone.tobytes())

        stamp, halo = render._plane_icon(0, render.icon_px(72) + 2)
        nx, ny = render.to_pixels(near.lat, near.lon, CENTER, 100, 72)
        left, top = nx - stamp.width // 2, ny - stamp.height // 2
        checked = 0
        for x in range(halo.width):
            for y in range(halo.height):
                if halo.getpixel((x, y)) > 0:
                    self.assertEqual(together.getpixel((left + x, top + y)), alone.getpixel((left + x, top + y)))
                    checked += 1
        self.assertGreater(checked, 40)

    def test_icons_never_poke_outside_the_ring(self):
        rng = random.Random(11)
        planes = [at_offset(north_km=rng.uniform(-150, 150), east_km=rng.uniform(-150, 150), track=rng.uniform(0, 360), hex=f"p{i}") for i in range(80)]
        for size in (72, 144):
            image = render.render_radar(planes, CENTER, 100, size, show_count=False, show_map=True)
            half = size // 2
            for x, y in lit_pixels(image):
                self.assertLessEqual(math.hypot(x - half, y - half), render.radar_radius_px(size) + 1.5, (x, y, size))


class EdgeIconTests(unittest.TestCase):
    def test_icons_at_the_edge_stay_inside_the_ring(self):
        for size in (72, 144):
            planes = [
                at_offset(
                    north_km=99 * math.cos(math.radians(bearing)),
                    east_km=99 * math.sin(math.radians(bearing)),
                    track=(bearing + 37) % 360,
                    hex=f"e{bearing}",
                )
                for bearing in range(0, 360, 45)
            ]
            image = render.render_radar(planes, CENTER, 100, size, show_count=False, max_icons=8)
            half = size // 2
            lit = lit_pixels(image)
            self.assertGreater(len(lit), 100)
            for x, y in lit:
                self.assertLessEqual(math.hypot(x - half, y - half), render.radar_radius_px(size) + 1.5, (x, y, size))

    def test_an_icon_at_the_edge_is_pulled_in_not_dropped(self):
        inner = at_offset(north_km=8, hex="inner")
        edge = at_offset(east_km=100, track=90.0, hex="edge")
        reference = render.render_radar([inner], CENTER, 100, 72, show_count=False)
        image = render.render_radar([inner, edge], CENTER, 100, 72, show_count=False)
        added = lit_pixels(image) - lit_pixels(reference)
        self.assertGreater(len(added), 15)
        distances = [math.hypot(x - 36, y - 36) for x, y in added]
        self.assertLessEqual(max(distances), render.radar_radius_px(72) + 1.5)
        self.assertGreater(max(distances), render.radar_radius_px(72) - 8)


def icon_pixel_count(track, px):
    stamp = render._icon_for(track, px)[0]
    return sum(1 for x in range(stamp.width) for y in range(stamp.height) if stamp.getpixel((x, y)) > 0)


class FullViewTests(unittest.TestCase):
    def render(self, planes=(), size=72, **kwargs):
        kwargs.setdefault("show_count", False)
        return render.render_radar(list(planes), CENTER, 100, size, full=True, **kwargs)

    def test_projection_uses_the_half_side_as_radius(self):
        east = render.to_pixels(CENTER[0], CENTER[1] + 0.45, CENTER, 100, 72, full=True)
        km = 0.45 * render.KM_PER_DEG_LON * math.cos(math.radians(CENTER[0]))
        self.assertEqual(east, (36 + round(km / 100 * 36), 36))
        self.assertEqual(render.to_pixels(*CENTER, CENTER, 100, 72, full=True), (36, 36))

    def test_full_view_projection_has_the_same_orientation(self):
        north = render.to_pixels(CENTER[0] + 0.3, CENTER[1], CENTER, 100, 72, full=True)
        east = render.to_pixels(CENTER[0], CENTER[1] + 0.3, CENTER, 100, 72, full=True)
        self.assertLess(north[1], 36)
        self.assertGreater(east[0], 36)

    def test_visible_area_is_the_square_not_the_circle(self):
        corner = (CENTER[0] + 90 / render.KM_PER_DEG_LAT, CENTER[1] + 90 / (render.KM_PER_DEG_LON * math.cos(math.radians(CENTER[0]))))
        self.assertIsNone(render.to_pixels(*corner, CENTER, 100, 72))
        self.assertIsNotNone(render.to_pixels(*corner, CENTER, 100, 72, full=True))

    def test_the_square_has_a_hard_edge_at_the_radius(self):
        inside = at_offset(east_km=100.5)
        outside = at_offset(east_km=102)
        self.assertIsNotNone(render.to_pixels(inside.lat, inside.lon, CENTER, 100, 72, full=True))
        self.assertIsNone(render.to_pixels(outside.lat, outside.lon, CENTER, 100, 72, full=True))
        tall = at_offset(north_km=102)
        self.assertIsNone(render.to_pixels(tall.lat, tall.lon, CENTER, 100, 72, full=True))

    def test_planes_in_the_corners_are_counted_and_drawn(self):
        corner = at_offset(north_km=90, east_km=90, track=45.0)
        full = self.render([corner], show_count=True)
        radar = render.render_radar([corner], CENTER, 100, 72, show_count=True)
        self.assertNotEqual(full.tobytes(), radar.tobytes())
        lit = lit_pixels(self.render([corner]))
        self.assertTrue(any(x > 52 and y < 20 for x, y in lit))

    def test_planes_outside_the_square_are_neither_drawn_nor_counted(self):
        far = at_offset(east_km=120, north_km=10)
        self.assertEqual(self.render([far], show_count=True).tobytes(), self.render([], show_count=True).tobytes())

    def test_map_fills_the_corners(self):
        line = synthetic_map(horizontal_line(CENTER[0] + 0.8))
        full = self.render(show_map=True, map_data=line).convert("L")
        radar = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=True, map_data=line).convert("L")
        for x in (6, 66):
            self.assertTrue(any(full.getpixel((x, y)) == 130 for y in range(72)), x)
            self.assertFalse(any(radar.getpixel((x, y)) == 130 for y in range(72)), x)

    def test_map_scale_matches_the_square(self):
        offset_deg = 0.85
        line = synthetic_map(horizontal_line(CENTER[0] + offset_deg))
        image = self.render(show_map=True, map_data=line).convert("L")
        rows = [y for y in range(72) if image.getpixel((20, y)) == 130]
        self.assertEqual(len(rows), 1)
        expected = 36 - offset_deg * render.KM_PER_DEG_LAT / 100 * 36
        self.assertAlmostEqual(rows[0], expected, delta=0.6)
        radar_expected = 36 - offset_deg * render.KM_PER_DEG_LAT / 100 * 34
        self.assertGreater(abs(rows[0] - radar_expected), 1.0)

    def test_there_is_no_ring(self):
        lit = lit_pixels(self.render([at_offset(east_km=10)], show_map=False))
        diagonal = [(x, y) for x, y in lit if abs(x - 36) > 8 and abs(y - 36) > 8]
        for x, y in diagonal:
            self.assertFalse(32 <= math.hypot(x - 36, y - 36) <= 35, (x, y))
        radar = lit_pixels(render.render_radar([at_offset(east_km=10)], CENTER, 100, 72, show_count=False))
        self.assertTrue([1 for x, y in radar if abs(x - 36) > 8 and abs(y - 36) > 8 and 32 <= math.hypot(x - 36, y - 36) <= 35])

    def test_cardinal_ticks_sit_on_the_key_edges(self):
        lit = lit_pixels(self.render())
        for point in ((36, 0), (36, 2), (36, 71), (36, 69), (0, 36), (2, 36), (71, 36), (69, 36)):
            self.assertIn(point, lit)

    def test_origin_is_still_drawn(self):
        for size, offsets in ((72, ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))), (144, ((0, -3), (3, 0), (0, 3), (-3, 0), (0, 0)))):
            lit = lit_pixels(self.render(size=size))
            for dx, dy in offsets:
                self.assertIn((size // 2 + dx, size // 2 + dy), lit)

    def test_guides_follow_the_square_when_there_is_no_map(self):
        lit = lit_pixels(self.render(show_map=False))
        ring_points = [(x, y) for x, y in lit if abs(math.hypot(x - 36, y - 36) - 18) < 0.8 and abs(x - 36) > 3 and abs(y - 36) > 3]
        self.assertGreater(len(ring_points), 8)

    def test_stale_border_is_still_drawn(self):
        fresh = lit_pixels(self.render())
        stale = lit_pixels(self.render(stale=True))
        added = stale - fresh
        self.assertGreater(len(added), 40)
        for x, y in added:
            self.assertTrue(x in (1, 70) or y in (1, 70), (x, y))

    def test_states_are_distinguishable_in_full_view(self):
        planes = [at_offset(north_km=20, east_km=10, track=90.0)]
        frames = {
            "waiting": render.render_radar(None, CENTER, 100, 72, full=True),
            "empty": render.render_radar([], CENTER, 100, 72, full=True),
            "fresh": render.render_radar(planes, CENTER, 100, 72, full=True),
            "stale": render.render_radar(planes, CENTER, 100, 72, full=True, stale=True),
        }
        self.assertEqual(len({image.tobytes() for image in frames.values()}), 4)

    def test_edge_icons_are_not_cut_off(self):
        px = render.icon_px(72) + 2
        expected = icon_pixel_count(0.0, px)
        for north_km, east_km in ((100, 50), (-100, 50), (50, 100), (50, -100), (100, 100), (-100, -100)):
            plane = at_offset(north_km=north_km, east_km=east_km, track=0.0)
            baseline = lit_pixels(self.render())
            added = lit_pixels(self.render([plane])) - baseline
            self.assertEqual(len(added), expected, (north_km, east_km))

    def test_marker_squares_at_the_edge_are_complete(self):
        planes = [at_offset(north_km=60 + 5 * i, east_km=100, hex=f"m{i}") for i in range(3)]
        image = self.render(planes, max_icons=0)
        lit = lit_pixels(image)
        for plane in planes:
            x, y = render.to_pixels(plane.lat, plane.lon, CENTER, 100, 72, full=True)
            x, y = render._clamp_to_square(x, y, 72, 1)
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    self.assertIn((x + dx, y + dy), lit)

    def test_nearest_marker_tail_stays_on_the_canvas(self):
        plane = at_offset(east_km=100, track=90.0)
        image = self.render([plane], max_icons=0)
        self.assertEqual(image.size, (72, 72))
        self.assertTrue(any(x >= 69 for x, _ in lit_pixels(image)))

    def test_icons_stay_on_the_canvas_for_random_traffic(self):
        rng = random.Random(3)
        planes = [at_offset(north_km=rng.uniform(-100, 100), east_km=rng.uniform(-100, 100), track=rng.uniform(0, 360), hex=f"r{i}") for i in range(40)]
        for size in (72, 144):
            image = self.render(planes, size=size, show_map=True)
            self.assertEqual(image.size, (size, size))

    def test_mosaic_full_view_reassembles_from_tiles(self):
        planes = [at_offset(north_km=70, east_km=-80, track=30.0), at_offset(north_km=-90, east_km=90, track=200.0)]
        frame = self.render(planes, size=144, show_map=True, show_count=True)
        rebuilt = Image.new("RGB", (144, 144))
        for row in range(2):
            for col in range(2):
                rebuilt.paste(render.crop_tile(frame, col, row), (col * 72, row * 72))
        self.assertEqual(rebuilt.tobytes(), frame.tobytes())

    def test_full_view_does_not_change_the_radar_view(self):
        planes = [at_offset(north_km=20, east_km=-30, track=120.0)]
        before = render.render_radar(planes, CENTER, 100, 72, show_map=True).tobytes()
        self.render(planes, show_map=True)
        self.assertEqual(render.render_radar(planes, CENTER, 100, 72, show_map=True).tobytes(), before)

    def test_map_layers_are_cached_separately_per_view(self):
        line = synthetic_map(horizontal_line(CENTER[0] + 0.8))
        full = self.render(show_map=True, map_data=line)
        radar = render.render_radar([], CENTER, 100, 72, show_count=False, show_map=True, map_data=line)
        full_again = self.render(show_map=True, map_data=line)
        self.assertNotEqual(full.tobytes(), radar.tobytes())
        self.assertEqual(full.tobytes(), full_again.tobytes())

    def test_shipped_map_lights_more_of_the_key_in_full_view(self):
        for center in ((40.4168, -3.7038), (51.5074, -0.1278)):
            full = render.render_radar([], center, 200, 72, show_count=False, show_map=True, full=True)
            radar = render.render_radar([], center, 200, 72, show_count=False, show_map=True)
            self.assertGreater(len(lit_pixels(full)), len(lit_pixels(radar)) - 80, center)
            corner = [(x, y) for x, y in lit_pixels(full) if math.hypot(x - 36, y - 36) > 36]
            self.assertGreater(len(corner), 5, center)


class CountCornerTests(unittest.TestCase):
    QUADRANT = {
        "top-left": (lambda x, y, h: x < h and y < h),
        "top-right": (lambda x, y, h: x >= h and y < h),
        "bottom-left": (lambda x, y, h: x < h and y >= h),
        "bottom-right": (lambda x, y, h: x >= h and y >= h),
    }

    def only_count(self, size, corner, full=False, count="0", planes=()):
        with_count = render.render_radar(list(planes), CENTER, 100, size, full=full, count_corner=corner)
        without = render.render_radar(list(planes), CENTER, 100, size, full=full, show_count=False)
        return lit_pixels(with_count) - lit_pixels(without)

    def test_each_corner_draws_in_its_own_quadrant(self):
        for size in (72, 144):
            half = size / 2
            for corner, inside in self.QUADRANT.items():
                for full in (False, True):
                    added = self.only_count(size, corner, full)
                    self.assertGreater(len(added), 8, (corner, size, full))
                    for x, y in added:
                        self.assertTrue(inside(x, y, half), (corner, size, full, x, y))

    def test_corners_never_use_the_middle_of_the_key(self):
        for corner in self.QUADRANT:
            for size in (72, 144):
                added = self.only_count(size, corner)
                for x, y in added:
                    self.assertGreater(max(abs(x - size // 2), abs(y - size // 2)), size // 8, (corner, size))

    def test_all_four_corners_differ(self):
        images = {corner: render.render_radar([], CENTER, 100, 144, count_corner=corner) for corner in self.QUADRANT}
        self.assertEqual(len({image.tobytes() for image in images.values()}), 4)

    def test_default_is_bottom_right(self):
        default = render.render_radar([], CENTER, 100, 72)
        explicit = render.render_radar([], CENTER, 100, 72, count_corner="bottom-right")
        self.assertEqual(default.tobytes(), explicit.tobytes())

    def test_the_mosaic_uses_an_outer_corner_of_the_whole_block(self):
        planes = [at_offset(north_km=40, east_km=-30, track=20.0)]
        for corner, (tile_x, tile_y) in (("top-left", (0, 0)), ("top-right", (1, 0)), ("bottom-left", (0, 1)), ("bottom-right", (1, 1))):
            added = self.only_count(144, corner, planes=planes, count="1")
            self.assertGreater(len(added), 8, corner)
            for x, y in added:
                self.assertEqual((x // render.KEY, y // render.KEY), (tile_x, tile_y), (corner, x, y))

    def test_unknown_corner_falls_back_to_bottom_right(self):
        fallback = render.render_radar([], CENTER, 100, 72, count_corner="nothing")
        expected = render.render_radar([], CENTER, 100, 72, count_corner="bottom-right")
        self.assertEqual(fallback.tobytes(), expected.tobytes())

    def test_count_keeps_its_black_backing_over_the_map(self):
        line = synthetic_map(horizontal_line(CENTER[0] + 0.85))
        added = self.only_count(72, "top-left")
        self.assertTrue(added)
        image = render.render_radar([], CENTER, 100, 72, show_map=True, map_data=line, count_corner="top-left").convert("L")
        left, top, right, bottom = ImageDraw.Draw(image).textbbox((3, 3), "0", font=render._font(13), anchor="lt")
        self.assertEqual(image.getpixel((left - 1, top - 1)), 0, "backing rectangle must cover the map")
        glyph = [image.getpixel((x, y)) for x in range(left, right + 1) for y in range(top, bottom + 1)]
        self.assertTrue(any(value > 200 for value in glyph), "the number must be drawn on top")


class ColorTests(unittest.TestCase):
    def test_palette_has_no_white_and_is_distinct(self):
        self.assertNotIn((255, 255, 255), render.PALETTE)
        self.assertEqual(len(set(render.PALETTE)), len(render.PALETTE))
        self.assertGreaterEqual(render.COLOR_SLOTS, 4)

    def test_colored_radar_is_not_greyscale_white_radar_is(self):
        planes = [at_offset(east_km=15, track=0.0), at_offset(north_km=30, track=90.0)]
        colored = render.render_radar(planes, CENTER, 100, 72, colored=True)
        white = render.render_radar(planes, CENTER, 100, 72, colored=False)
        self.assertFalse(is_greyscale(colored))
        self.assertTrue(is_greyscale(white))

    def test_nearest_square_takes_the_first_palette_colour(self):
        plane = at_offset(east_km=15)  # no track -> square marker
        image = render.render_radar([plane], CENTER, 100, 72, colored=True, show_count=False).convert("RGB")
        x, y = render.to_pixels(plane.lat, plane.lon, CENTER, 100, 72)
        self.assertEqual(image.getpixel((x, y)), render.PALETTE[0])

    def test_second_plane_gets_the_second_colour(self):
        near = at_offset(east_km=10, hex="a")
        far = at_offset(east_km=40, hex="b")
        image = render.render_radar([far, near], CENTER, 100, 72, colored=True, show_count=False).convert("RGB")
        for plane, colour in ((near, render.PALETTE[0]), (far, render.PALETTE[1])):
            x, y = render.to_pixels(plane.lat, plane.lon, CENTER, 100, 72)
            self.assertEqual(image.getpixel((x, y)), colour, plane.hex)

    def test_planes_past_the_palette_are_white(self):
        planes = [at_offset(east_km=6 + 10 * i, hex=f"p{i}") for i in range(render.COLOR_SLOTS + 2)]
        image = render.render_radar(planes, CENTER, 100, 72, colored=True, show_count=False, max_icons=0).convert("RGB")
        beyond = planes[render.COLOR_SLOTS + 1]
        x, y = render.to_pixels(beyond.lat, beyond.lon, CENTER, 100, 72)
        self.assertEqual(image.getpixel((x, y)), (255, 255, 255))

    def test_colored_icons_keep_the_same_shape_as_white_ones(self):
        plane = at_offset(east_km=15, track=45.0)
        colored = render.render_radar([plane], CENTER, 100, 72, colored=True, show_count=False)
        white = render.render_radar([plane], CENTER, 100, 72, colored=False, show_count=False)
        self.assertEqual(lit_pixels(colored), lit_pixels(white))
        self.assertNotEqual(colored.tobytes(), white.tobytes())

    def test_map_stays_grey_when_planes_are_colored(self):
        line = synthetic_map(horizontal_line(CENTER[0]))
        image = render.render_radar([], CENTER, 100, 72, show_map=True, map_data=line, colored=True).convert("RGB")
        self.assertEqual(image.getpixel((20, 36)), (130, 130, 130))

    def test_colored_full_view_and_mosaic_still_fit_the_frames(self):
        inner = [at_offset(north_km=40, east_km=30, track=45.0), at_offset(north_km=-30, east_km=-20, track=200.0)]
        corners = [at_offset(north_km=90, east_km=90, track=45.0), at_offset(north_km=-80, east_km=-70, track=200.0)]
        for size, full, planes in ((72, True, corners), (144, False, inner), (144, True, corners)):
            image = render.render_radar(planes, CENTER, 100, size, colored=True, full=full, show_map=True)
            self.assertEqual(image.size, (size, size))
            self.assertEqual(image.mode, "RGB")
            self.assertFalse(is_greyscale(image), (size, full))

    def test_count_and_stale_stay_white_in_colour_mode(self):
        image = render.render_radar([at_offset(east_km=10, hex="a")], CENTER, 100, 72, colored=True, stale=True).convert("RGB")
        edge = [(x, y) for x, y in lit_pixels(image) if x in (1, 70) or y in (1, 70)]
        self.assertTrue(edge)
        for x, y in edge:
            self.assertEqual(image.getpixel((x, y)), (255, 255, 255))


class ListRenderTests(unittest.TestCase):
    def planes(self, n=3):
        return [
            at_offset(east_km=5 + 9 * i, hex=f"h{i}", callsign=f"TEST{i + 1}", alt_ft=10000 + i)
            for i in range(n)
        ]

    def test_size_mode_and_empty_states(self):
        for size in (72, 144):
            image = render.render_list(self.planes(), CENTER, 100, size)
            self.assertEqual((image.size, image.mode), ((size, size), "RGB"))
        self.assertGreater(len(lit_pixels(render.render_list([], CENTER, 100, 72))), 5)
        self.assertNotEqual(render.render_list([], CENTER, 100, 72).tobytes(), render.render_list(None, CENTER, 100, 72).tobytes())

    def test_one_row_per_plane_in_distance_order(self):
        planes = self.planes(4)
        image = render.render_list(planes, CENTER, 100, 72)
        rows = render.nearest_planes(planes, CENTER, 100)
        self.assertEqual([p.hex for _, p in rows], ["h0", "h1", "h2", "h3"])
        self.assertNotEqual(image.tobytes(), render.render_list([], CENTER, 100, 72).tobytes())

    def test_swatch_colours_match_the_radar(self):
        planes = self.planes(3)
        listing = render.render_list(planes, CENTER, 100, 72).convert("RGB")
        radar = render.render_radar(planes, CENTER, 100, 72, colored=True, show_count=False, max_icons=0).convert("RGB")
        rows = render.nearest_planes(planes, CENTER, 100)
        pitch = max(9, round(render.LIST_PITCH * 1))
        top = max(0, (72 - len(rows) * pitch) // 2)
        for index, (_distance, plane) in enumerate(rows):
            y = top + index * pitch + pitch // 2
            self.assertEqual(listing.getpixel((3, y)), render.PALETTE[index], index)
            x, ry = render.to_pixels(plane.lat, plane.lon, CENTER, 100, 72)
            self.assertEqual(radar.getpixel((x, ry)), render.PALETTE[index], plane.hex)

    def test_white_mode_drops_the_swatches_and_matches_white_radar(self):
        planes = self.planes(3)
        colored = render.render_list(planes, CENTER, 100, 72, colored=True)
        white = render.render_list(planes, CENTER, 100, 72, colored=False)
        self.assertNotEqual(colored.tobytes(), white.tobytes())
        self.assertTrue(is_greyscale(white))

    def test_rows_are_capped_by_height(self):
        many = [at_offset(east_km=1 + 0.5 * i, hex=f"n{i:02d}", callsign=f"C{i:02d}") for i in range(30)]
        from radar.render import nearest_planes

        ranked = nearest_planes(many, CENTER, 100)
        rows = (72 - 2 * 2) // 11
        self.assertEqual(render.render_list(many, CENTER, 100, 72).tobytes(), render.render_list([p for _, p in ranked[:rows]], CENTER, 100, 72).tobytes())
        self.assertNotEqual(render.render_list(many, CENTER, 100, 72).tobytes(), render.render_list([p for _, p in ranked[:rows - 1]], CENTER, 100, 72).tobytes())

    def test_a_long_callsign_is_truncated_to_the_available_width(self):
        draw = ImageDraw.Draw(Image.new("RGB", (72, 72)))
        font = render._font(10)
        truncated = render._fit_text(draw, "ABCDEFGHIJKL", font, 72 - 2 - 6)
        self.assertLess(len(truncated), 12)
        long_plane = at_offset(east_km=50, hex="a", callsign="ABCDEFGHIJKL")
        short_plane = at_offset(east_km=50, hex="b", callsign=truncated)
        self.assertEqual(
            render.render_list([long_plane], CENTER, 100, 72).tobytes(),
            render.render_list([short_plane], CENTER, 100, 72).tobytes(),
        )

    def test_planes_outside_the_radius_are_not_listed(self):
        inside = at_offset(east_km=10, hex="in", callsign="IN")
        outside = at_offset(east_km=400, hex="out", callsign="OUT")
        self.assertEqual(
            render.render_list([inside, outside], CENTER, 100, 72).tobytes(),
            render.render_list([inside], CENTER, 100, 72).tobytes(),
        )

    def test_full_view_lists_corner_planes(self):
        corner = at_offset(north_km=90, east_km=90, hex="corner", callsign="CNR")
        radar = render.render_list([corner], CENTER, 100, 72, full=False)
        full = render.render_list([corner], CENTER, 100, 72, full=True)
        self.assertNotEqual(radar.tobytes(), full.tobytes())

    def test_missing_callsign_falls_back_to_hex(self):
        plane = at_offset(east_km=10, hex="0d0e29")
        image = render.render_list([plane], CENTER, 100, 72)
        self.assertNotEqual(image.tobytes(), render.render_list([], CENTER, 100, 72).tobytes())

    def test_long_callsigns_drop_the_distance_instead_of_truncating(self):
        long_plane = at_offset(east_km=50, hex="a", callsign="N3695W1")
        short_plane = at_offset(east_km=50, hex="b", callsign="VIV1")

        def grey_pixels(image):
            return [1 for x in range(72) for y in range(72) if image.getpixel((x, y)) == render.GREY]

        self.assertEqual(grey_pixels(render.render_list([long_plane], CENTER, 100, 72)), [])
        self.assertGreater(len(grey_pixels(render.render_list([short_plane], CENTER, 100, 72))), 3)

    def test_fit_text_never_exceeds_the_width(self):
        image = Image.new("RGB", (72, 72))
        draw = ImageDraw.Draw(image)
        font = render._font(10)
        for text in ("N3695W1", "AMX385", "0d10fe", "X"):
            fitted = render._fit_text(draw, text, font, 20)
            self.assertLessEqual(draw.textlength(fitted, font=font), 20, text)
            self.assertTrue(fitted)
        self.assertEqual(render._fit_text(draw, "AMX", font, 100), "AMX")

    def test_stale_border_is_drawn(self):
        planes = self.planes(2)
        self.assertNotEqual(
            render.render_list(planes, CENTER, 100, 72, stale=True).tobytes(),
            render.render_list(planes, CENTER, 100, 72).tobytes(),
        )

    def test_list_does_not_draw_a_map(self):
        # A map would put grey pixels far from the rows; the list is only text and swatches.
        image = render.render_list(self.planes(2), CENTER, 100, 72).convert("RGB")
        greys = {(x, y) for x in range(72) for y in range(72) if image.getpixel((x, y)) == render.GREY}
        self.assertTrue(all(x > 40 for x, _ in greys))


class NearestPlanesTests(unittest.TestCase):
    def test_sorted_and_filtered(self):
        near = at_offset(east_km=10, hex="b")
        far = at_offset(east_km=50, hex="a")
        out = at_offset(east_km=400, hex="c")
        rows = render.nearest_planes([far, out, near], CENTER, 100)
        self.assertEqual([p.hex for _, p in rows], ["b", "a"])

    def test_limit(self):
        planes = [at_offset(east_km=10 + 5 * i, hex=f"p{i}") for i in range(10)]
        self.assertEqual(len(render.nearest_planes(planes, CENTER, 100, limit=3)), 3)

    def test_ties_are_broken_by_hex_for_stability(self):
        a = at_offset(east_km=10, hex="aa")
        b = at_offset(east_km=10, hex="bb")
        first = [p.hex for _, p in render.nearest_planes([b, a], CENTER, 100)]
        second = [p.hex for _, p in render.nearest_planes([a, b], CENTER, 100)]
        self.assertEqual(first, second)
        self.assertEqual(first, ["aa", "bb"])

    def test_full_view_includes_corners(self):
        corner = at_offset(north_km=90, east_km=90, hex="c")
        self.assertEqual(render.nearest_planes([corner], CENTER, 100), [])
        self.assertEqual(len(render.nearest_planes([corner], CENTER, 100, full=True)), 1)


class TileTests(unittest.TestCase):
    def test_crops_reassemble_the_frame(self):
        planes = [at_offset(north_km=30, east_km=-20), at_offset(north_km=-50, east_km=40)]
        frame = render.render_radar(planes, CENTER, 100, 144)
        rebuilt = Image.new("RGB", (144, 144))
        for row in range(2):
            for col in range(2):
                tile = render.crop_tile(frame, col, row)
                self.assertEqual(tile.size, (72, 72))
                rebuilt.paste(tile, (col * 72, row * 72))
        self.assertEqual(rebuilt.tobytes(), frame.tobytes())

    def test_warning_size(self):
        self.assertEqual(render.render_warning(72).size, (72, 72))


class FontTests(unittest.TestCase):
    def test_font_is_cached_and_usable(self):
        first = render._font(13)
        self.assertIs(first, render._font(13))
        self.assertGreater(first.getbbox("19")[2], 0)


if __name__ == "__main__":
    unittest.main()
