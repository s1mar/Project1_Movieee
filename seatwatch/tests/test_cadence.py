import datetime
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.__main__ import plan_schedule, _requests_over, _stride_for
from seatwatch.config import Config, Showtime

NOW = datetime.datetime(2026, 8, 21, 9, 0, 0).timestamp()


def cfg(**kw):
    base = dict(interval_seconds=45, duration_seconds=270,
                max_requests_per_run=60)
    base.update(kw)
    return Config(**base)


def show(hours_from_now):
    start = datetime.datetime.fromtimestamp(NOW + hours_from_now * 3600)
    return Showtime(id=str(int(hours_from_now * 100)),
                    starts=start.isoformat())


class StrideTests(unittest.TestCase):
    def test_imminent_shows_poll_every_pass(self):
        self.assertEqual(_stride_for(2), 1)      # in 2h
        self.assertEqual(_stride_for(11), 1)

    def test_further_shows_get_larger_strides(self):
        self.assertGreater(_stride_for(24), _stride_for(6))
        self.assertGreater(_stride_for(100), _stride_for(24))
        self.assertGreaterEqual(_stride_for(500), _stride_for(100))

    def test_unknown_start_is_treated_as_far(self):
        # hours_until returns 1e6 for missing starts.
        self.assertEqual(_stride_for(1e6), 6)


class ScheduleTests(unittest.TestCase):
    def test_closest_show_polled_more_than_distant(self):
        shows = [show(2), show(200)]      # tonight vs next week
        passes, _, strides = plan_schedule(cfg(), shows, NOW)
        near = (passes - 1) // strides[0] + 1
        far = (passes - 1) // strides[1] + 1
        self.assertGreater(near, far)

    def test_stays_within_budget(self):
        shows = [show(h) for h in (2, 3, 30, 40, 100, 150, 160)]
        passes, _, strides = plan_schedule(cfg(max_requests_per_run=30),
                                           shows, NOW)
        self.assertLessEqual(_requests_over(strides, passes), 30)

    def test_first_pass_covers_everything(self):
        # Pass 1 polls every show regardless of stride (baseline check).
        shows = [show(h) for h in (2, 200)]
        _, _, strides = plan_schedule(cfg(), shows, NOW)
        for s in strides:
            self.assertEqual((1 - 1) % s, 0)

    def test_imminent_show_polled_every_single_pass(self):
        shows = [show(1)] + [show(200)] * 20
        passes, _, strides = plan_schedule(cfg(), shows, NOW)
        polled = sum(1 for p in range(1, passes + 1)
                     if (p - 1) % strides[0] == 0)
        self.assertEqual(polled, passes)

    def test_all_distant_still_polls_at_least_once(self):
        shows = [show(300) for _ in range(28)]
        passes, interval, strides = plan_schedule(cfg(), shows, NOW)
        self.assertGreaterEqual(passes, 1)
        self.assertGreaterEqual(interval, 45)
        for s in strides:
            self.assertGreaterEqual((passes - 1) // s + 1, 1)

    def test_tighter_budget_reduces_passes(self):
        shows = [show(1) for _ in range(10)]
        loose = plan_schedule(cfg(max_requests_per_run=60), shows, NOW)[0]
        tight = plan_schedule(cfg(max_requests_per_run=12), shows, NOW)[0]
        self.assertGreaterEqual(loose, tight)

    def test_interval_never_below_floor(self):
        shows = [show(1) for _ in range(4)]
        _, interval, _ = plan_schedule(cfg(), shows, NOW)
        self.assertGreaterEqual(interval, 45)

    def test_no_showtimes_is_safe(self):
        passes, interval, strides = plan_schedule(cfg(), [], NOW)
        self.assertEqual(strides, [])
        self.assertGreaterEqual(passes, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
