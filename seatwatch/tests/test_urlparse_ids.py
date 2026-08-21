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

    def test_real_cineplex_ticketing_preview_shape(self):
        # The shape Cineplex actually uses for the seat preview page.
        got = extract("https://www.cineplex.com/ticketing/preview"
                      "?locationId=9406&showtimeId=778812")
        self.assertEqual((got.theatre_id, got.showtime_id), ("9406", "778812"))
        self.assertTrue(got.complete)

    def test_preview_shape_with_extra_params_and_fragment(self):
        got = extract("https://www.cineplex.com/ticketing/preview"
                      "?lang=en&locationId=9406&showtimeId=778812&utm_source=x#seats")
        self.assertEqual((got.theatre_id, got.showtime_id), ("9406", "778812"))

    def test_preview_shape_theatreid_variant(self):
        got = extract("https://www.cineplex.com/ticketing/preview"
                      "?theatreId=9406&showtimeId=778812")
        self.assertEqual((got.theatre_id, got.showtime_id), ("9406", "778812"))

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


class MultiUrlPasteTests(unittest.TestCase):
    """A pasted blob of URLs should not need splitting up by hand."""

    BLOB = """https://www.cineplex.com/ticketing/preview?theatreId=9406&showtimeId=403871
    https://www.cineplex.com/ticketing/preview?theatreId=9406&showtimeId=403872
https://www.cineplex.com/ticketing/preview?locationId=9406&showtimeId=403873"""

    def test_whitespace_separated_blob_yields_every_id(self):
        ids = [extract(u).showtime_id for u in self.BLOB.split() if u.strip()]
        self.assertEqual(ids, ["403871", "403872", "403873"])

    def test_mixed_param_names_in_one_blob(self):
        theatres = {extract(u).theatre_id for u in self.BLOB.split() if u.strip()}
        self.assertEqual(theatres, {"9406"})

    def test_junk_lines_are_isolated_not_fatal(self):
        lines = self.BLOB.split() + ["https://example.com/nope", "garbage"]
        good = [extract(u) for u in lines]
        self.assertEqual(sum(1 for g in good if g.complete), 3)


class BareIdTests(unittest.TestCase):
    """Reading numbers off a page is less work than copying whole URLs."""

    def test_bare_numeric_id(self):
        got = extract("403870")
        self.assertEqual(got.showtime_id, "403870")
        self.assertTrue(got.complete or got.showtime_id)

    def test_trailing_comma_is_tolerated(self):
        self.assertEqual(extract("403872,").showtime_id, "403872")

    def test_surrounding_punctuation_is_stripped(self):
        for token in ("(403872)", "'403872'", "[403872]", "403872;"):
            self.assertEqual(extract(token).showtime_id, "403872", token)

    def test_bare_id_carries_no_theatre(self):
        # The configured theatre fills this in when the block is written.
        self.assertEqual(extract("403870").theatre_id, "")

    def test_non_numeric_token_is_not_an_id(self):
        self.assertEqual(extract("garbage").showtime_id, "")
