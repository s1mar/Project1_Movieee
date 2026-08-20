"""Regression tests against payloads captured from the live Cineplex API.

Fixtures are a trimmed slice of the real seat-layout and seat-availability
responses for theatre 9406 / showtime 403870 (The Odyssey, IMAX 70mm,
Cineplex Cinema Banque Scotia Montreal).
"""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.seats import Criteria, match_seats, parse_seatmap, row_ordinal

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LAYOUT = json.loads((FIXTURES / "real_layout.json").read_text())
AVAIL = json.loads((FIXTURES / "real_availability.json").read_text())


class RealSeatmapTests(unittest.TestCase):
    def setUp(self):
        self.seats = parse_seatmap(LAYOUT, AVAIL)

    def test_every_availability_entry_becomes_a_seat(self):
        self.assertEqual(len(self.seats),
                         len(AVAIL["seatAvailabilities"]))

    def test_rows_carry_letters_not_physical_numbers(self):
        # The availability ids encode physical rows that run backwards
        # (row A is physical 12). Letters must come from the layout.
        self.assertEqual({s.row for s in self.seats}, {"D", "E", "F"})

    def test_unlabelled_aisle_row_is_not_seating(self):
        # Row index 5 has label null and no seats - it's a walkway.
        aisle = [r for r in LAYOUT["standardSeats"]["rows"]
                 if r.get("label") is None]
        self.assertTrue(aisle, "fixture should contain the aisle row")
        self.assertEqual(aisle[0]["seats"], [])

    def test_row_letters_order_front_to_back(self):
        self.assertLess(row_ordinal("D"), row_ordinal("E"))
        self.assertLess(row_ordinal("E"), row_ordinal("F"))

    def test_seat_labels_come_from_the_payload(self):
        labels = {s.label for s in self.seats}
        self.assertTrue(any(l.startswith("E") for l in labels))
        # Real labels, not row+column concatenations.
        self.assertTrue(all(l and not l.endswith("None") for l in labels))

    def test_available_seats_are_the_wheelchair_spaces(self):
        free = [s for s in self.seats if s.available]
        self.assertTrue(free, "fixture should contain free seats")
        self.assertTrue(all(s.seat_type == "Wheelchair" for s in free))

    def test_wheelchair_seats_are_flagged_accessible(self):
        for seat in self.seats:
            if seat.seat_type in ("Wheelchair", "Companion"):
                self.assertTrue(seat.is_accessible, seat.label)

    def test_default_criteria_skip_the_wheelchair_spaces(self):
        # The whole point: don't page the user about seats reserved for
        # people who need them.
        matches = match_seats(self.seats, Criteria(min_row="E",
                                                   max_centre_offset=0.5))
        self.assertEqual(matches, [])

    def test_opting_in_surfaces_them(self):
        matches = match_seats(self.seats, Criteria(min_row="E",
                                                   max_centre_offset=1.0,
                                                   include_accessible=True))
        self.assertTrue(matches)
        self.assertTrue(all(m.seat.row == "E" for m in matches))

    def test_rows_before_min_row_excluded_on_real_data(self):
        matches = match_seats(self.seats, Criteria(min_row="E",
                                                   max_centre_offset=1.0,
                                                   include_accessible=True))
        self.assertNotIn("D", {m.seat.row for m in matches})

    def test_grid_column_drives_position_not_label_digits(self):
        seat = next(s for s in self.seats if s.column is not None)
        self.assertEqual(seat.position, seat.column)

    def test_missing_availability_entry_is_skipped(self):
        partial = {"seatAvailabilities": {}}
        self.assertEqual(parse_seatmap(LAYOUT, partial), [])

    def test_bare_availability_map_without_wrapper(self):
        bare = AVAIL["seatAvailabilities"]
        self.assertEqual(len(parse_seatmap(LAYOUT, bare)), len(bare))


if __name__ == "__main__":
    unittest.main(verbosity=2)
