import unittest

from actions.block import Block, detect_block

ROWS, COLS = 3, 5
TILE_SHAPES = {(2, 2)}
SCOPE_SHAPES = {(1, 1)}


def membership(cells):
    cells = set(cells)

    def is_member(x, y):
        assert 0 <= x < COLS and 0 <= y < ROWS, f"queried out of bounds: {(x, y)}"
        return (x, y) in cells

    return is_member


TILES = [(3, 1), (4, 1), (3, 2), (4, 2)]


class DetectBlockTests(unittest.TestCase):
    def test_valid_2x2_from_every_corner(self):
        expected = {(3, 1): (0, 0), (4, 1): (1, 0), (3, 2): (0, 1), (4, 2): (1, 1)}
        for start, (col, row) in expected.items():
            block = detect_block(start, ROWS, COLS, membership(TILES), TILE_SHAPES)
            self.assertEqual(block, Block(x0=3, y0=1, w=2, h=2, col=col, row=row))

    def test_scope_is_1x1(self):
        block = detect_block((3, 0), ROWS, COLS, membership([(3, 0)]), SCOPE_SHAPES)
        self.assertEqual(block, Block(x0=3, y0=0, w=1, h=1, col=0, row=0))

    def test_scope_next_to_tiles_is_unaffected_because_membership_is_per_class(self):
        block = detect_block((3, 0), ROWS, COLS, membership([(3, 0)]), SCOPE_SHAPES)
        self.assertIsNotNone(block)
        tile = detect_block((3, 1), ROWS, COLS, membership(TILES), TILE_SHAPES)
        self.assertIsNotNone(tile)

    def test_l_shape_is_invalid(self):
        cells = [(3, 1), (4, 1), (3, 2)]
        self.assertIsNone(detect_block((3, 1), ROWS, COLS, membership(cells), TILE_SHAPES))

    def test_hole_is_invalid(self):
        cells = [(2, 1), (3, 1), (4, 1), (2, 2), (4, 2)]
        self.assertIsNone(detect_block((2, 1), ROWS, COLS, membership(cells), TILE_SHAPES))

    def test_3x2_is_invalid(self):
        cells = [(2, 1), (3, 1), (4, 1), (2, 2), (3, 2), (4, 2)]
        self.assertIsNone(detect_block((2, 1), ROWS, COLS, membership(cells), TILE_SHAPES))

    def test_2x1_is_invalid(self):
        self.assertIsNone(detect_block((3, 1), ROWS, COLS, membership([(3, 1), (4, 1)]), TILE_SHAPES))

    def test_lone_tile_is_invalid(self):
        self.assertIsNone(detect_block((3, 1), ROWS, COLS, membership([(3, 1)]), TILE_SHAPES))

    def test_lone_scope_is_invalid_if_a_neighbour_joins_it(self):
        self.assertIsNone(detect_block((3, 0), ROWS, COLS, membership([(3, 0), (3, 1)]), SCOPE_SHAPES))

    def test_disconnected_members_are_ignored(self):
        block = detect_block((3, 1), ROWS, COLS, membership(TILES + [(0, 0), (1, 2)]), TILE_SHAPES)
        self.assertEqual(block.w * block.h, 4)

    def test_diagonal_neighbours_do_not_join(self):
        cells = [(3, 1), (4, 2)]
        self.assertIsNone(detect_block((3, 1), ROWS, COLS, membership(cells), TILE_SHAPES))

    def test_never_queries_outside_the_deck(self):
        detect_block((4, 2), ROWS, COLS, membership(TILES), TILE_SHAPES)
        detect_block((0, 0), ROWS, COLS, membership([(0, 0)]), SCOPE_SHAPES)


if __name__ == "__main__":
    unittest.main()
