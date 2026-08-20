"""End-to-end: fake Cineplex + fake ntfy, driven through the real CLI."""

import http.server
import json
import pathlib
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from seatwatch.__main__ import main

# Row E spans 1..15 -> centre is 8. E8 is dead centre, E1/E15 are edges.
SOLD_OUT = {"seats": [
    {"rowName": "D", "seatNumber": "8", "isAvailable": True},
    {"rowName": "E", "seatNumber": "1", "isAvailable": True},
    {"rowName": "E", "seatNumber": "8", "isAvailable": False},
    {"rowName": "E", "seatNumber": "15", "isAvailable": True},
]}
CANCELLATION = json.loads(json.dumps(SOLD_OUT))
CANCELLATION["seats"][2]["isAvailable"] = True

STATE = {"payload": SOLD_OUT, "pushes": []}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if "seat-availability" in self.path:
            body = json.dumps(STATE["payload"]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        STATE["pushes"].append({
            "path": self.path,
            "title": self.headers.get("Title", ""),
            "priority": self.headers.get("Priority", ""),
            "click": self.headers.get("Click", ""),
            "body": self.rfile.read(length).decode(),
        })
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        STATE["payload"] = SOLD_OUT
        STATE["pushes"] = []
        self.tmp = tempfile.TemporaryDirectory()
        base = f"http://127.0.0.1:{self.port}"
        self.cfg = pathlib.Path(self.tmp.name) / "config.toml"
        self.cfg.write_text(f'''
[theatre]
id = "7031"
name = "Test Cinema"
booking_url = "https://example.invalid/book"

[criteria]
min_row = "E"
max_centre_offset = 0.5

[alerts]
priority = "max"

[poll]
interval_seconds = 20
duration_seconds = 0
cooldown_seconds = 21600
alert_on_first_run = true
health_warn_after = 3
state_path = "{self.tmp.name}/state.json"

[api]
base_url = "{base}"

[[showtimes]]
id = "555"
label = "Fri 21 Aug, 7:00 PM"
url = "https://example.invalid/seats"
''')
        self.env = {"NTFY_TOPIC": "test-topic",
                    "NTFY_SERVER": f"http://127.0.0.1:{self.port}"}
        self._patch_env()

    def _patch_env(self):
        import os
        self.saved = {k: os.environ.get(k) for k in
                      ("NTFY_TOPIC", "NTFY_SERVER", "WEBHOOK_URL",
                       "GITHUB_TOKEN", "GITHUB_REPOSITORY")}
        for k, v in self.saved.items():
            os.environ.pop(k, None)
        os.environ.update(self.env)

    def tearDown(self):
        import os
        for k in self.env:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v
        self.tmp.cleanup()

    def run_cli(self, *args):
        return main(["--config", str(self.cfg), *args])

    def test_check_runs_clean_against_a_live_endpoint(self):
        self.assertEqual(self.run_cli("check"), 0)

    def test_sold_out_middle_produces_no_push(self):
        self.assertEqual(self.run_cli("watch"), 0)
        titles = [p["title"] for p in STATE["pushes"]]
        # E1 and E15 are edge seats, filtered by max_centre_offset.
        self.assertEqual(titles, [], f"unexpected push: {STATE['pushes']}")

    def test_cancellation_in_the_middle_pushes(self):
        self.run_cli("watch")                    # baseline: nothing matches
        STATE["payload"] = CANCELLATION          # someone cancels E8
        self.run_cli("watch")
        self.assertEqual(len(STATE["pushes"]), 1)
        push = STATE["pushes"][0]
        self.assertIn("/test-topic", push["path"])
        self.assertIn("1 seat", push["title"])
        self.assertIn("E8", push["body"])
        self.assertEqual(push["click"], "https://example.invalid/seats")

    def test_same_seat_does_not_push_twice(self):
        self.run_cli("watch")
        STATE["payload"] = CANCELLATION
        self.run_cli("watch")
        self.run_cli("watch")
        self.run_cli("watch")
        self.assertEqual(len(STATE["pushes"]), 1)

    def test_test_alert_reaches_the_channel(self):
        self.assertEqual(self.run_cli("test-alert"), 0)
        self.assertEqual(len(STATE["pushes"]), 1)
        self.assertIn("seatwatch test", STATE["pushes"][0]["title"])

    def test_missing_showtime_is_reported_not_crashed(self):
        STATE["payload"] = {}
        self.assertEqual(self.run_cli("watch"), 0)
        self.assertEqual(STATE["pushes"], [])

    def test_configured_priority_reaches_ntfy(self):
        self.run_cli("watch")
        STATE["payload"] = CANCELLATION
        self.run_cli("watch")
        self.assertEqual(STATE["pushes"][0]["priority"], "max")

    def test_a_broken_endpoint_warns_instead_of_going_quiet(self):
        # An unparseable payload must not read as "no seats available".
        STATE["payload"] = {"unexpected": "shape"}
        for _ in range(3):
            self.run_cli("watch")
        self.assertEqual(len(STATE["pushes"]), 1)
        self.assertIn("broken", STATE["pushes"][0]["title"])

    def test_health_warning_does_not_repeat(self):
        STATE["payload"] = {"unexpected": "shape"}
        for _ in range(6):
            self.run_cli("watch")
        self.assertEqual(len(STATE["pushes"]), 1)

    def test_recovery_still_alerts_normally(self):
        STATE["payload"] = {"unexpected": "shape"}
        for _ in range(3):
            self.run_cli("watch")
        STATE["payload"] = CANCELLATION
        self.run_cli("watch")
        titles = [p["title"] for p in STATE["pushes"]]
        self.assertEqual(len(titles), 2)
        self.assertIn("just opened up", titles[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
