import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.seats import (Criteria, Seat, col_number, extract_seats,
                             match_seats, row_ordinal)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class RowOrdinalTests(unittest.TestCase):
    def test_single_letters_order_front_to_back(self):
        self.assertEqual(row_ordinal("A"), 1)
        self.assertEqual(row_ordinal("E"), 5)
        self.assertLess(row_ordinal("D"), row_ordinal("E"))

    def test_double_letters_sort_after_singles(self):
        self.assertGreater(row_ordinal("AA"), row_ordinal("Z"))

    def test_case_and_padding_insensitive(self):
        self.assertEqual(row_ordinal(" e "), row_ordinal("E"))

    def test_numeric_rows_fall_back_to_int(self):
        self.assertEqual(row_ordinal("12"), 12)

    def test_col_number_strips_letters(self):
        self.assertEqual(col_number("E12"), 12)
        self.assertEqual(col_number("7"), 7)


class ExtractTests(unittest.TestCase):
    def test_nested_layout_inherits_row_names(self):
        seats = extract_seats(load("nested_layout.json"))
        self.assertEqual(len(seats), 10)
        self.assertEqual(len([s for s in seats if s.row == "E"]), 5)
        self.assertTrue(all(s.row and s.col for s in seats))

    def test_status_words_map_to_availability(self):
        by_label = {s.label: s for s in extract_seats(load("nested_layout.json"))}
        self.assertTrue(by_label["E1"].available)
        self.assertFalse(by_label["E5"].available)
        self.assertFalse(by_label["A2"].available)

    def test_flat_boolean_payload(self):
        seats = extract_seats(load("flat_availability.json"))
        self.assertEqual(len(seats), 9)
        by_label = {s.label: s for s in seats}
        self.assertTrue(by_label["E8"].available)
        self.assertFalse(by_label["G7"].available)

    def test_seats_come_back_sorted(self):
        seats = extract_seats(load("flat_availability.json"))
        self.assertEqual([s.label for s in seats][:4], ["D8", "E1", "E8", "E15"])

    def test_accessible_seats_flagged(self):
        by_label = {s.label: s for s in extract_seats(load("nested_layout.json"))}
        self.assertTrue(by_label["E11"].is_accessible)
        self.assertFalse(by_label["E1"].is_accessible)

    def test_empty_and_garbage_payloads_are_safe(self):
        self.assertEqual(extract_seats({}), [])
        self.assertEqual(extract_seats([]), [])
        self.assertEqual(extract_seats({"nope": [1, 2, "x", None]}), [])


class MatchTests(unittest.TestCase):
    def test_rows_before_min_row_are_excluded(self):
        seats = extract_seats(load("flat_availability.json"))
        matches = match_seats(seats, Criteria(min_row="E", max_centre_offset=1.0))
        self.assertNotIn("D8", [m.label for m in matches])

    def test_sold_seats_never_match(self):
        seats = extract_seats(load("flat_availability.json"))
        matches = match_seats(seats, Criteria(min_row="E", max_centre_offset=1.0))
        self.assertNotIn("G7", [m.label for m in matches])

    def test_centre_offset_filters_out_edges(self):
        seats = extract_seats(load("flat_availability.json"))
        # Row E spans columns 1-15, so centre is 8 and the edges are 1 and 15.
        labels = [m.label for m in
                  match_seats(seats, Criteria(min_row="E", max_centre_offset=0.5))]
        self.assertIn("E8", labels)
        self.assertNotIn("E1", labels)
        self.assertNotIn("E15", labels)

    def test_most_central_seat_ranks_first(self):
        seats = extract_seats(load("flat_availability.json"))
        matches = match_seats(seats, Criteria(min_row="E", max_centre_offset=1.0))
        self.assertEqual(matches[0].label, "E8")
        self.assertAlmostEqual(matches[0].centre_offset, 0.0)

    def test_accessible_seats_skipped_by_default(self):
        seats = extract_seats(load("nested_layout.json"))
        crit = Criteria(min_row="E", max_centre_offset=1.0)
        self.assertNotIn("E11", [m.label for m in match_seats(seats, crit)])
        opt_in = Criteria(min_row="E", max_centre_offset=1.0, include_accessible=True)
        self.assertIn("E11", [m.label for m in match_seats(seats, opt_in)])

    def test_max_row_caps_the_back(self):
        seats = extract_seats(load("flat_availability.json"))
        matches = match_seats(seats, Criteria(min_row="E", max_row="F",
                                             max_centre_offset=1.0))
        self.assertEqual({m.seat.row for m in matches}, {"E"})

    def test_min_adjacent_requires_a_run_of_free_seats(self):
        seats = extract_seats(load("flat_availability.json"))
        crit = Criteria(min_row="E", max_centre_offset=1.0, min_adjacent=2)
        labels = [m.label for m in match_seats(seats, crit)]
        # G8+G9 are adjacent; E8 sits alone between sold/absent neighbours.
        self.assertIn("G8", labels)
        self.assertIn("G9", labels)
        self.assertNotIn("E8", labels)

    def test_no_matches_returns_empty_not_error(self):
        self.assertEqual(match_seats([], Criteria()), [])

    def test_single_seat_row_does_not_divide_by_zero(self):
        matches = match_seats([Seat(row="E", col="1", available=True)],
                              Criteria(min_row="E"))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].centre_offset, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
