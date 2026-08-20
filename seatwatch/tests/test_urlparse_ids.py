import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.urlparse_ids import extract


class ExtractTests(unittest.TestCase):
    def test_rest_style_path(self):
        got = extract("https://apis.cineplex.com/prod/ticketing/api/v1/"
                      "theatre/9406/showtime/778812/seat-availability")
        self.assertEqual((got.theatre_id, got.showtime_id), ("9406", "778812"))
        self.assertTrue(got.complete)

    def test_session_style_path(self):
        got = extract("https://www.cineplex.com/theatres/9406/sessions/4471")
        self.assertEqual((got.theatre_id, got.showtime_id), ("9406", "4471"))

    def test_query_string_params(self):
        got = extract("https://www.cineplex.com/ticketing/seat-selection"
                      "?theatreId=9406&showtimeId=778812&lang=en")
        self.assertEqual((got.theatre_id, got.showtime_id), ("9406", "778812"))

    def test_alternate_param_names(self):
        got = extract("https://www.cineplex.com/x?locationId=9406&sessionId=99")
        self.assertEqual((got.theatre_id, got.showtime_id), ("9406", "99"))

    def test_params_nested_in_a_redirect(self):
        got = extract("https://www.cineplex.com/go?returnUrl="
                      "https%3A%2F%2Fx%2Fy%3FtheatreId%3D9406%26showtimeId%3D5150")
        self.assertEqual((got.theatre_id, got.showtime_id), ("9406", "5150"))

    def test_unknown_shape_reports_candidates(self):
        got = extract("https://www.cineplex.com/weird/9406/thing/778812/")
        self.assertFalse(got.complete)
        self.assertIn("9406", got.candidates.values())
        self.assertIn("778812", got.candidates.values())

    def test_garbage_does_not_crash(self):
        got = extract("not a url at all")
        self.assertFalse(got.complete)

    def test_empty_string(self):
        self.assertFalse(extract("").complete)


if __name__ == "__main__":
    unittest.main(verbosity=2)
