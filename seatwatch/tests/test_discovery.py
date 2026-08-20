import datetime
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.discovery import dates_ahead, find_showtimes

# The showtimes feed is key-gated and its real shape has not been observed,
# so these cover the shapes the parser is written to tolerate rather than a
# captured payload. `seatwatch discover` dumps the real thing to adapt.
NESTED = {
    "theatre": {"id": 9406},
    "dates": [{
        "date": "2026-08-21",
        "movies": [{
            "filmId": 38376, "title": "The Odyssey",
            "showtimes": [
                {"showtimeId": 403870, "showStartTime": "2026-08-21T19:00:00"},
                {"showtimeId": 403871, "showStartTime": "2026-08-21T22:30:00"},
            ],
        }, {
            "filmId": 99999, "title": "Something Else",
            "showtimes": [
                {"showtimeId": 500001, "showStartTime": "2026-08-21T20:00:00"},
            ],
        }],
    }],
}

FLAT = {"showtimes": [
    {"id": 403870, "startDateTime": "2026-08-21T19:00:00", "movieId": 38376},
    {"id": 403875, "startDateTime": "2026-08-22T19:00:00", "movieId": 38376},
]}


class FindShowtimesTests(unittest.TestCase):
    def test_finds_nested_showtimes(self):
        found = find_showtimes(NESTED)
        self.assertEqual({f.id for f in found},
                         {"403870", "403871", "500001"})

    def test_film_filter_excludes_other_movies(self):
        found = find_showtimes(NESTED, film_id="38376")
        self.assertEqual({f.id for f in found}, {"403870", "403871"})

    def test_film_id_inherited_from_enclosing_movie(self):
        found = find_showtimes(NESTED, film_id="38376")
        self.assertTrue(all(f.film_id == "38376" for f in found))

    def test_flat_shape_with_alternate_key_names(self):
        found = find_showtimes(FLAT, film_id="38376")
        self.assertEqual({f.id for f in found}, {"403870", "403875"})

    def test_results_are_deduplicated_and_time_ordered(self):
        doubled = {"a": NESTED, "b": NESTED}
        found = find_showtimes(doubled, film_id="38376")
        self.assertEqual([f.id for f in found], ["403870", "403871"])

    def test_label_is_human_readable(self):
        found = find_showtimes(FLAT, film_id="38376")
        self.assertIn("7:00", found[0].label)

    def test_label_falls_back_when_time_unparseable(self):
        found = find_showtimes({"showtimes": [
            {"id": 1, "startDateTime": "2026-13-99T99:99"}]})
        self.assertTrue(found[0].label)

    def test_records_without_a_timestamp_are_ignored(self):
        # Avoids mistaking theatre/film ids for showtimes.
        self.assertEqual(find_showtimes({"theatreId": 9406, "filmId": 38376}), [])

    def test_garbage_payloads_are_safe(self):
        for junk in ({}, [], None, {"x": [1, "y", None]}):
            self.assertEqual(find_showtimes(junk), [])


class DatesAheadTests(unittest.TestCase):
    def test_seven_days_includes_today(self):
        today = datetime.date(2026, 8, 20)
        dates = dates_ahead(7, today)
        self.assertEqual(len(dates), 7)
        self.assertEqual(dates[0], "2026-08-20")
        self.assertEqual(dates[-1], "2026-08-26")

    def test_month_boundary(self):
        dates = dates_ahead(4, datetime.date(2026, 8, 30))
        self.assertEqual(dates, ["2026-08-30", "2026-08-31",
                                 "2026-09-01", "2026-09-02"])

    def test_zero_days_still_returns_today(self):
        self.assertEqual(len(dates_ahead(0, datetime.date(2026, 8, 20))), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
