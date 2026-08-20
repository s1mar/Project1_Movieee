import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.state import State

KEY = "7031:99"


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_reports_everything_as_new(self):
        s = State.load(self.path)
        self.assertTrue(s.is_first_run(KEY))
        self.assertEqual(s.newly_available(KEY, ["E8", "E9"], now=1000),
                         ["E8", "E9"])

    def test_seat_free_on_both_passes_is_not_news(self):
        s = State.load(self.path)
        s.record(KEY, ["E8"], ["E8"], now=1000)
        self.assertEqual(s.newly_available(KEY, ["E8"], now=1100), [])

    def test_seat_that_appears_later_is_news(self):
        s = State.load(self.path)
        s.record(KEY, ["E8"], ["E8"], now=1000)
        self.assertEqual(s.newly_available(KEY, ["E8", "F9"], now=1100), ["F9"])

    def test_cooldown_suppresses_a_flickering_seat(self):
        s = State.load(self.path)
        s.record(KEY, ["E8"], ["E8"], now=1000)
        s.record(KEY, [], [], now=1100)          # sold again
        # Freed again 10 minutes later, still inside the 6h cooldown.
        self.assertEqual(s.newly_available(KEY, ["E8"], cooldown_seconds=21600,
                                           now=1700), [])

    def test_cooldown_expires(self):
        s = State.load(self.path)
        s.record(KEY, ["E8"], ["E8"], now=1000)
        s.record(KEY, [], [], now=1100)
        self.assertEqual(s.newly_available(KEY, ["E8"], cooldown_seconds=600,
                                           now=9000), ["E8"])

    def test_state_survives_a_round_trip(self):
        s = State.load(self.path)
        s.record(KEY, ["E8"], ["E8"], now=1000)
        s.save()
        reloaded = State.load(self.path)
        self.assertFalse(reloaded.is_first_run(KEY))
        self.assertEqual(reloaded.newly_available(KEY, ["E8"], now=1100), [])

    def test_corrupt_state_file_does_not_crash(self):
        self.path.write_text("{ not json")
        s = State.load(self.path)
        self.assertTrue(s.is_first_run(KEY))

    def test_prune_drops_dead_showtimes(self):
        s = State.load(self.path)
        s.record(KEY, ["E8"], [], now=1000)
        s.record("7031:100", ["E8"], [], now=1000)
        s.prune({KEY})
        self.assertEqual(list(s.data["showtimes"]), [KEY])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_single_failure_is_not_worth_warning_about(self):
        s = State.load(self.path)
        self.assertFalse(s.note_health(KEY, False, warn_after=3, now=1000))

    def test_warns_once_the_threshold_is_crossed(self):
        s = State.load(self.path)
        self.assertFalse(s.note_health(KEY, False, warn_after=3, now=1000))
        self.assertFalse(s.note_health(KEY, False, warn_after=3, now=1100))
        self.assertTrue(s.note_health(KEY, False, warn_after=3, now=1200))

    def test_does_not_nag_after_warning(self):
        s = State.load(self.path)
        for t in (1000, 1100, 1200):
            s.note_health(KEY, False, warn_after=3, now=t)
        self.assertFalse(s.note_health(KEY, False, warn_after=3, now=1300))

    def test_nags_again_after_the_quiet_period(self):
        s = State.load(self.path)
        for t in (1000, 1100, 1200):
            s.note_health(KEY, False, warn_after=3, now=t)
        self.assertTrue(s.note_health(KEY, False, warn_after=3,
                                      quiet_seconds=3600, now=1000 + 7200))

    def test_a_good_poll_resets_the_streak(self):
        s = State.load(self.path)
        s.note_health(KEY, False, warn_after=3, now=1000)
        s.note_health(KEY, False, warn_after=3, now=1100)
        s.note_health(KEY, True, warn_after=3, now=1200)
        self.assertFalse(s.note_health(KEY, False, warn_after=3, now=1300))
