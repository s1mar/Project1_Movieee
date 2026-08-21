"""Read control commands from an ntfy topic.

ntfy is bidirectional: you subscribe to a topic to receive pushes, and you
can also publish plain messages to it (the compose box in the app). This
reads the most recent command a human typed into a control topic, so the
watcher can be paused, resumed, or asked for status from a phone - without
any credential living in the notification.

Commands are matched case-insensitively against the first word of a message,
so "pause", "Pause please", "PAUSE" all count. Messages the watcher itself
publishes (alerts, status replies) carry a title, so they are ignored here -
only bare user messages are treated as commands.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

TIMEOUT = 15

PAUSE = "pause"
RESUME = "resume"
STATUS = "status"

_ALIASES = {
    "pause": PAUSE, "stop": PAUSE, "off": PAUSE, "halt": PAUSE,
    "resume": RESUME, "start": RESUME, "on": RESUME, "go": RESUME,
    "status": STATUS, "state": STATUS, "ping": STATUS,
}
_COMMANDS = (PAUSE, RESUME, STATUS)


@dataclass(frozen=True)
class Command:
    kind: str          # PAUSE / RESUME / STATUS
    at: float          # message timestamp (epoch seconds)
    raw: str = ""


def parse_command(message: str, title: str = "") -> str | None:
    """Return the canonical command in a message, or None.

    A message with a title came from the watcher itself (alerts have
    titles), so it is never a command.
    """
    if title:
        return None
    if not message:
        return None
    first = message.strip().split()[0].lower() if message.strip() else ""
    return _ALIASES.get(first)


def commands(messages: list[dict]) -> list[Command]:
    """Every command in a list of ntfy message events, oldest first."""
    out = []
    for m in messages:
        if m.get("event") != "message":
            continue
        kind = parse_command(m.get("message", ""), m.get("title", ""))
        if kind is None:
            continue
        out.append(Command(kind=kind, at=float(m.get("time", 0) or 0),
                           raw=m.get("message", "")))
    return sorted(out, key=lambda c: c.at)


def is_paused(cmds: list[Command]) -> bool:
    """Paused iff the most recent pause/resume command is a pause.

    STATUS commands are ignored here, so asking for status never changes
    whether the watcher is paused.
    """
    for c in reversed(cmds):
        if c.kind == PAUSE:
            return True
        if c.kind == RESUME:
            return False
    return False


def pending_status(cmds: list[Command], after: float) -> Command | None:
    """The newest STATUS command later than `after`, or None."""
    latest = None
    for c in cmds:
        if c.kind == STATUS and c.at > after:
            latest = c
    return latest


def read_commands(topic: str, server: str = "https://ntfy.sh",
                  since: str = "12h") -> list[Command]:
    """Poll a control topic and return its commands, oldest first.

    Network or parse failures return [] (treated as "no commands"), so a
    flaky control channel never blocks the actual seat watching.
    """
    if not topic:
        return []
    params = urllib.parse.urlencode({"poll": "1", "since": since})
    url = f"{server.rstrip('/')}/{topic}/json?{params}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return []
    messages = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return commands(messages)
