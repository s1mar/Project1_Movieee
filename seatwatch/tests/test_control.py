import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.control import (Command, PAUSE, RESUME, STATUS, commands,
                               is_paused, parse_command, pending_status)


def msg(text, t, title=""):
    return {"event": "message", "message": text, "time": t, "title": title}


class ParseTests(unittest.TestCase):
    def test_bare_commands(self):
        self.assertEqual(parse_command("pause"), PAUSE)
        self.assertEqual(parse_command("resume"), RESUME)
        self.assertEqual(parse_command("status"), STATUS)

    def test_aliases(self):
        self.assertEqual(parse_command("stop"), PAUSE)
        self.assertEqual(parse_command("start"), RESUME)
        self.assertEqual(parse_command("ping"), STATUS)

    def test_case_and_extra_words(self):
        self.assertEqual(parse_command("PAUSE please"), PAUSE)
        self.assertEqual(parse_command("  Resume  now "), RESUME)

    def test_non_command(self):
        self.assertIsNone(parse_command("hello there"))
        self.assertIsNone(parse_command(""))

    def test_watcher_own_messages_are_not_commands(self):
        # Alerts carry a title; they must never be read back as a command.
        self.assertIsNone(parse_command("pause", title="1 seat opened up"))


class StateTests(unittest.TestCase):
    def test_default_is_running(self):
        self.assertFalse(is_paused([]))

    def test_latest_pause_resume_wins(self):
        cmds = commands([msg("pause", 100), msg("resume", 200)])
        self.assertFalse(is_paused(cmds))
        cmds = commands([msg("resume", 100), msg("pause", 200)])
        self.assertTrue(is_paused(cmds))

    def test_status_does_not_change_pause_state(self):
        # pause, then a later status: still paused.
        cmds = commands([msg("pause", 100), msg("status", 300)])
        self.assertTrue(is_paused(cmds))

    def test_ordering_is_by_time_not_list_order(self):
        cmds = commands([msg("resume", 300), msg("pause", 100)])
        self.assertFalse(is_paused(cmds))

    def test_pending_status_only_after_cursor(self):
        cmds = commands([msg("status", 100), msg("status", 500)])
        got = pending_status(cmds, after=200)
        self.assertIsNotNone(got)
        self.assertEqual(got.at, 500)
        self.assertIsNone(pending_status(cmds, after=600))

    def test_own_alerts_ignored_in_stream(self):
        cmds = commands([msg("pause", 100, title="alert"), msg("go", 200)])
        # The titled 'pause' is skipped; 'go' (resume) wins.
        self.assertFalse(is_paused(cmds))


if __name__ == "__main__":
    unittest.main(verbosity=2)
