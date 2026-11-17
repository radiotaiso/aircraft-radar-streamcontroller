import unittest

from radar import adsb, units


class ConversionTests(unittest.TestCase):
    def test_choices_and_default(self):
        self.assertEqual(units.UNIT_CHOICES, ("nm", "km", "mi"))
        self.assertEqual(units.DEFAULT_UNIT, "nm")
        self.assertIn(units.DEFAULT_UNIT, units.UNIT_CHOICES)

    def test_to_unit(self):
        self.assertAlmostEqual(units.to_unit(100, "nm"), 53.9957, places=3)
        self.assertEqual(units.to_unit(100, "km"), 100.0)
        self.assertAlmostEqual(units.to_unit(100, "mi"), 62.137, places=3)
        self.assertEqual(units.to_unit(0, "nm"), 0.0)

    def test_round_trip(self):
        for unit in units.UNIT_CHOICES:
            self.assertAlmostEqual(units.to_unit(42.0, unit) * units._factor(unit), 42.0, places=9)

    def test_unknown_unit_falls_back_to_nautical_miles(self):
        self.assertEqual(units.to_unit(100, "furlongs"), units.to_unit(100, "nm"))
        self.assertEqual(units.format_distance(100, "furlongs"), units.format_distance(100, "nm"))
        self.assertEqual(units.unit_label(100, "furlongs"), "54 NM")

    def test_format_is_whole_numbers_without_a_suffix(self):
        self.assertEqual(units.format_distance(100, "nm"), "54")
        self.assertEqual(units.format_distance(100, "km"), "100")
        self.assertEqual(units.format_distance(100, "mi"), "62")
        self.assertEqual(units.format_distance(0, "km"), "0")

    def test_unit_label_keeps_one_decimal_only_when_needed(self):
        self.assertEqual(units.unit_label(100, "nm"), "54 NM")
        self.assertEqual(units.unit_label(25, "nm"), "13.5 NM")
        self.assertEqual(units.unit_label(100, "km"), "100 km")
        self.assertEqual(units.unit_label(25, "km"), "25 km")
        self.assertEqual(units.unit_label(150, "mi"), "93.2 mi")

    def test_every_radius_choice_has_a_label_in_every_unit(self):
        from radar.config import RADIUS_CHOICES

        for unit in units.UNIT_CHOICES:
            labels = [units.unit_label(km, unit) for km in RADIUS_CHOICES]
            self.assertEqual(len(set(labels)), len(labels), unit)
            self.assertTrue(all(label.endswith(units._SUFFIXES[unit]) for label in labels), unit)

    def test_the_api_and_the_list_share_one_nautical_mile(self):
        self.assertIs(adsb.KM_PER_NM, units.KM_PER_NM)


if __name__ == "__main__":
    unittest.main()
