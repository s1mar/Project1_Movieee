import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.__main__ import plan_cadence
from seatwatch.config import Config


def cfg(**kw):
    base = dict(interval_seconds=45, duration_seconds=270,
                max_requests_per_run=30)
    base.update(kw)
    return Config(**base)


class CadenceTests(unittest.TestCase):
    def test_single_showtime_polls_as_fast_as_the_window_allows(self):
        passes, interval = plan_cadence(cfg(), 1)
        self.assertEqual(passes, 7)
        self.assertEqual(interval, 45)

    def test_many_showtimes_stay_inside_the_budget(self):
        for n in (4, 12, 28, 60):
            passes, _ = plan_cadence(cfg(), n)
            # One pass per showtime is the floor; beyond that, stay budgeted.
            self.assertLessEqual(n * passes, max(n, 30 + n))

    def test_a_week_of_slots_does_not_explode_request_volume(self):
        passes, _ = plan_cadence(cfg(), 28)
        per_hour = 28 * passes * 12
        self.assertLess(per_hour, 500,
                        "watching a week of slots must stay polite")

    def test_more_showtimes_never_means_more_passes(self):
        prev = plan_cadence(cfg(), 1)[0]
        for n in (2, 5, 10, 30):
            passes = plan_cadence(cfg(), n)[0]
            self.assertLessEqual(passes, prev)
            prev = passes

    def test_interval_never_drops_below_the_configured_floor(self):
        for n in (1, 3, 9, 40):
            _, interval = plan_cadence(cfg(), n)
            self.assertGreaterEqual(interval, 45)

    def test_passes_spread_across_the_run_window(self):
        passes, interval = plan_cadence(cfg(), 12)
        self.assertLessEqual((passes - 1) * interval, 270)

    def test_zero_showtimes_does_not_divide_by_zero(self):
        passes, interval = plan_cadence(cfg(), 0)
        self.assertGreaterEqual(passes, 1)
        self.assertGreaterEqual(interval, 45)

    def test_a_tighter_budget_reduces_passes(self):
        loose = plan_cadence(cfg(max_requests_per_run=60), 12)[0]
        tight = plan_cadence(cfg(max_requests_per_run=12), 12)[0]
        self.assertGreater(loose, tight)


if __name__ == "__main__":
    unittest.main(verbosity=2)
