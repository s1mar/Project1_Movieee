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

# A miniature auditorium in Cineplex's real two-endpoint shape: the layout
# carries row letters and grid columns, availability is a flat id->status map
# whose ids encode *physical* rows that run backwards from the letters.
def _row(label, number, physical, cols):
    return {
        "number": number, "physicalNumber": physical, "label": label,
        "seats": [{"id": f"1_{physical}_{c}", "column": c,
                   "columnPhysicalNumber": c, "label": f"{label}{c}",
                   "seatGroupIds": [], "type": "Standard"} for c in cols],
    }


LAYOUT = {
    "totalRows": 3, "totalColumns": 15,
    "seatLegendTypes": ["Standard", "Wheelchair", "Companion"],
    "standardSeats": {
        "left": 0.0, "top": 0.0, "areaWidth": 15, "columnCount": 15,
        "columnWidth": 1, "rowCount": 3,
        "rows": [
            _row("D", 0, 4, [8]),
            _row("E", 1, 3, [1, 8, 15]),
            {"number": 2, "physicalNumber": 2, "label": None, "seats": []},
        ],
    },
}

# Row E spans columns 1..15, so its centre is 8: E8 is dead centre and
# E1/E15 are the edge seats that max_centre_offset should reject.
_SOLD = {
    "1_4_8": "Available",                     # row D - before min_row
    "1_3_1": "Available", "1_3_8": "Occupied", "1_3_15": "Available",
}
SOLD_OUT = {"seatAvailabilities": dict(_SOLD),
            "isSoldOut": False, "isPostShowtime": False}
CANCELLATION = {"seatAvailabilities": dict(_SOLD, **{"1_3_8": "Available"}),
                "isSoldOut": False, "isPostShowtime": False}

STATE = {"payload": SOLD_OUT, "layout": LAYOUT, "pushes": []}


class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if "seat-availability" in self.path:
            self._json(STATE["payload"])
        elif "seat-layout" in self.path:
            self._json(STATE["layout"])
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
        STATE["layout"] = LAYOUT
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
        STATE["layout"] = {}
        self.assertEqual(self.run_cli("watch"), 0)
        self.assertEqual(STATE["pushes"], [])

    def test_expired_showtime_triggers_a_watchlist_notice(self):
        # isPostShowtime means the screening has been and gone. Going quiet
        # would be indistinguishable from "no seats free".
        STATE["payload"] = {"seatAvailabilities": {}, "isPostShowtime": True}
        self.assertEqual(self.run_cli("watch"), 0)
        titles = [p["title"] for p in STATE["pushes"]]
        self.assertEqual(len(titles), 1)
        self.assertIn("nothing left to watch", titles[0])

    def test_watchlist_notice_does_not_repeat(self):
        STATE["payload"] = {"seatAvailabilities": {}, "isPostShowtime": True}
        for _ in range(4):
            self.run_cli("watch")
        self.assertEqual(len(STATE["pushes"]), 1)

    def test_a_live_showtime_suppresses_the_notice(self):
        self.run_cli("watch")
        self.assertEqual([p["title"] for p in STATE["pushes"]], [])

    def test_configured_priority_reaches_ntfy(self):
        self.run_cli("watch")
        STATE["payload"] = CANCELLATION
        self.run_cli("watch")
        self.assertEqual(STATE["pushes"][0]["priority"], "max")

    def test_a_broken_endpoint_warns_instead_of_going_quiet(self):
        # An unparseable payload must not read as "no seats available".
        STATE["payload"] = {"unexpected": "shape"}
        STATE["layout"] = {"unexpected": "shape"}
        for _ in range(3):
            self.run_cli("watch")
        self.assertEqual(len(STATE["pushes"]), 1)
        self.assertIn("broken", STATE["pushes"][0]["title"])

    def test_health_warning_does_not_repeat(self):
        STATE["payload"] = {"unexpected": "shape"}
        STATE["layout"] = {"unexpected": "shape"}
        for _ in range(6):
            self.run_cli("watch")
        self.assertEqual(len(STATE["pushes"]), 1)

    def test_recovery_still_alerts_normally(self):
        STATE["payload"] = {"unexpected": "shape"}
        STATE["layout"] = {"unexpected": "shape"}
        for _ in range(3):
            self.run_cli("watch")
        STATE["payload"] = CANCELLATION
        STATE["layout"] = LAYOUT
        self.run_cli("watch")
        titles = [p["title"] for p in STATE["pushes"]]
        self.assertEqual(len(titles), 2)
        self.assertIn("just opened up", titles[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
