import datetime
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.discovery import dates_ahead, describe_shape, find_showtimes

# A trimmed copy of the real showtimes payload (theatre 9406, one date),
# keeping The Odyssey with IMAX/70mm, plain 70mm and Regular experiences,
# plus one past session and one general-admission session to exclude.
REAL = [{
    "theatre": "Cinema Banque Scotia Montreal", "theatreId": 9406,
    "dates": [{
        "startDate": "2026-08-21",
        "movies": [{
            "id": 37617, "name": "The Odyssey",
            "presentationType": "Film Presentation",
            "experiences": [
                {"experienceTypes": ["IMAX", "70mm"], "sessions": [
                    {"vistaSessionId": 404523,
                     "showStartDateTime": "2026-08-21T11:00:00",
                     "seatsRemaining": 18, "isInThePast": False,
                     "isReservedSeating": True, "isSoldOut": False,
                     "seatMapUrl": "https://x/preview?theatreId=9406&showtimeId=404523"},
                    {"vistaSessionId": 404521,
                     "showStartDateTime": "2026-08-21T18:45:00",
                     "seatsRemaining": 5, "isInThePast": False,
                     "isReservedSeating": True, "isSoldOut": False,
                     "seatMapUrl": ""},
                    {"vistaSessionId": 400000,
                     "showStartDateTime": "2026-08-21T08:00:00",
                     "seatsRemaining": 0, "isInThePast": True,
                     "isReservedSeating": True, "isSoldOut": True,
                     "seatMapUrl": ""},
                ]},
                {"experienceTypes": ["70mm"], "sessions": [
                    {"vistaSessionId": 405873,
                     "showStartDateTime": "2026-08-21T14:00:00",
                     "seatsRemaining": 303, "isInThePast": False,
                     "isReservedSeating": True, "isSoldOut": False,
                     "seatMapUrl": ""}]},
                {"experienceTypes": ["Regular"], "sessions": [
                    {"vistaSessionId": 405871,
                     "showStartDateTime": "2026-08-21T12:10:00",
                     "seatsRemaining": 155, "isInThePast": False,
                     "isReservedSeating": False, "isSoldOut": False,
                     "seatMapUrl": ""}]},
            ],
        }, {
            "id": 99999, "name": "Another Film",
            "experiences": [{"experienceTypes": ["IMAX", "70mm"], "sessions": [
                {"vistaSessionId": 500001,
                 "showStartDateTime": "2026-08-21T20:00:00",
                 "seatsRemaining": 10, "isInThePast": False,
                 "isReservedSeating": True, "isSoldOut": False,
                 "seatMapUrl": ""}]}],
        }],
    }],
}]


class FindShowtimesTests(unittest.TestCase):
    def test_finds_odyssey_across_all_experiences(self):
        found = find_showtimes(REAL, film_id="37617")
        # 404523, 404521 (IMAX70), 405873 (70mm) - not the past one, not GA.
        self.assertEqual({f.id for f in found}, {"404523", "404521", "405873"})

    def test_imax_70mm_filter(self):
        found = find_showtimes(REAL, film_id="37617",
                               want_experiences=("IMAX", "70mm"))
        self.assertEqual({f.id for f in found}, {"404523", "404521"})

    def test_film_filter_excludes_other_movies(self):
        found = find_showtimes(REAL, film_id="37617")
        self.assertNotIn("500001", {f.id for f in found})

    def test_past_sessions_are_excluded(self):
        self.assertNotIn("400000", {f.id for f in find_showtimes(REAL)})

    def test_general_admission_is_excluded(self):
        # Regular 405871 is isReservedSeating False - no seat map to watch.
        self.assertNotIn("405871", {f.id for f in find_showtimes(REAL)})

    def test_session_id_comes_from_vista_session_id(self):
        found = find_showtimes(REAL, film_id="37617",
                               want_experiences=("IMAX", "70mm"))
        self.assertTrue(all(f.id.isdigit() for f in found))

    def test_label_carries_time_and_experience(self):
        f = next(f for f in find_showtimes(REAL, film_id="37617")
                 if f.id == "404523")
        self.assertIn("11:00", f.label)
        self.assertIn("IMAX", f.label)

    def test_seats_remaining_is_captured(self):
        f = next(f for f in find_showtimes(REAL, film_id="37617")
                 if f.id == "404521")
        self.assertEqual(f.seats_remaining, 5)

    def test_results_time_ordered(self):
        ids = [f.id for f in find_showtimes(REAL, film_id="37617")]
        self.assertEqual(ids, ["404523", "405873", "404521"])

    def test_garbage_payloads_are_safe(self):
        for junk in ({}, [], None, "x", {"dates": "nope"}):
            self.assertEqual(find_showtimes(junk), [])


class DatesAheadTests(unittest.TestCase):
    def test_seven_days_includes_today(self):
        dates = dates_ahead(7, datetime.date(2026, 8, 21))
        self.assertEqual(len(dates), 7)
        self.assertEqual(dates[0], "2026-08-21")
        self.assertEqual(dates[-1], "2026-08-27")

    def test_month_boundary(self):
        self.assertEqual(dates_ahead(3, datetime.date(2026, 8, 30)),
                         ["2026-08-30", "2026-08-31", "2026-09-01"])


class DescribeShapeTests(unittest.TestCase):
    def test_prints_structure_not_values(self):
        secret = "super-secret"
        lines = "\n".join(describe_shape({"k": secret, "n": 42}))
        self.assertNotIn(secret, lines)
        self.assertNotIn("42", lines)
        self.assertIn("k: str", lines)

    def test_depth_bounded(self):
        node = d = {}
        for _ in range(20):
            node["c"] = {}
            node = node["c"]
        self.assertIn("...", "\n".join(describe_shape(d)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
