"""Find every showtime for a film at a theatre over the next N days.

The showtimes feed is the one Cineplex endpoint that *does* require a
subscription key - the open ticketing endpoints only answer questions about
a showtime you can already name. So this runs only when CINEPLEX_API_KEY is
set, and the watcher falls back to hand-listed showtimes otherwise.

The response shape has not been observed (no key was available when this was
written), so parsing is deliberately loose and `seatwatch discover` dumps the
raw payload to make adapting it a one-liner.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

_ID_KEYS = ("showtimeid", "sessionid", "vistasessionid", "id")
_TIME_KEYS = ("showstarttime", "startdatetime", "showtime", "starttime",
              "sessiondatetime", "datetime", "startsat")
_FILM_KEYS = ("filmid", "movieid", "vistafilmid", "parentfilmid")
_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


@dataclass(frozen=True)
class Found:
    id: str
    starts_at: str = ""
    film_id: str = ""

    @property
    def label(self) -> str:
        if not self.starts_at:
            return f"showtime {self.id}"
        try:
            dt = datetime.datetime.fromisoformat(self.starts_at[:19])
            return dt.strftime("%a %-d %b, %-I:%M %p")
        except ValueError:
            return self.starts_at


def _lower(d: dict) -> dict:
    return {k.lower(): v for k, v in d.items()}


def find_showtimes(payload, film_id: str = "") -> list[Found]:
    """Every showtime-looking record in a showtimes payload."""
    out: dict[str, Found] = {}
    _walk(payload, film_id, inherited_film="", out=out)
    return sorted(out.values(), key=lambda f: (f.starts_at, f.id))


def _walk(node, want_film: str, inherited_film: str, out: dict) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, want_film, inherited_film, out)
        return
    if not isinstance(node, dict):
        return

    low = _lower(node)
    film = ""
    for key in _FILM_KEYS:
        if low.get(key) not in (None, ""):
            film = str(low[key])
            break
    film = film or inherited_film

    start = ""
    for key in _TIME_KEYS:
        value = low.get(key)
        if isinstance(value, str) and _TIME_RE.match(value):
            start = value
            break

    if start:
        for key in _ID_KEYS:
            value = low.get(key)
            if value not in (None, "") and str(value).isdigit():
                if not want_film or film == str(want_film):
                    sid = str(value)
                    out.setdefault(sid, Found(id=sid, starts_at=start,
                                              film_id=film))
                break

    for value in node.values():
        _walk(value, want_film, film, out)


def dates_ahead(days: int, today: datetime.date | None = None) -> list[str]:
    """ISO dates from today through `days` (inclusive of today)."""
    start = today or datetime.date.today()
    return [(start + datetime.timedelta(days=i)).isoformat()
            for i in range(max(1, days))]


def describe_shape(node, depth: int = 0, max_depth: int = 4) -> list[str]:
    """A keys-and-types outline of a payload, without the payload.

    When discovery parses nothing, this goes to the log so the mismatch can
    be diagnosed from a CI run. It deliberately prints structure, never
    values, so nothing sensitive ends up in a public build log.
    """
    pad = "  " * depth
    if depth >= max_depth:
        return [f"{pad}..."]
    if isinstance(node, dict):
        lines = []
        for key, value in list(node.items())[:12]:
            kind = type(value).__name__
            if isinstance(value, (dict, list)):
                lines.append(f"{pad}{key}: {kind}[{len(value)}]")
                lines.extend(describe_shape(value, depth + 1, max_depth))
            else:
                lines.append(f"{pad}{key}: {kind}")
        if len(node) > 12:
            lines.append(f"{pad}... +{len(node) - 12} more keys")
        return lines
    if isinstance(node, list):
        return describe_shape(node[0], depth, max_depth) if node else [f"{pad}(empty)"]
    return [f"{pad}{type(node).__name__}"]
