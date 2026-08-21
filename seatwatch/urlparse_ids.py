"""Pull theatre/showtime IDs out of a Cineplex URL pasted from the address bar.

Cineplex has moved its ticketing URL shape around over the years, so rather
than bind to one layout this tries the known patterns and then falls back to
reporting candidates for a human to pick from.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

# Ordered most-specific first.
_PAIR_PATTERNS = [
    re.compile(r"/theatre/(?P<theatre>\d+)/showtime/(?P<showtime>\d+)", re.I),
    re.compile(r"/theatres?/(?P<theatre>\d+)/sessions?/(?P<showtime>\d+)", re.I),
]

_THEATRE_PARAMS = ("theatreid", "locationid", "cinemaid", "theatre", "location")
_SHOWTIME_PARAMS = ("showtimeid", "sessionid", "vistasessionid", "showtime",
                    "session", "performanceid")


@dataclass
class Extracted:
    theatre_id: str = ""
    showtime_id: str = ""
    candidates: dict = None

    @property
    def complete(self) -> bool:
        return bool(self.theatre_id and self.showtime_id)


def extract(url: str) -> Extracted:
    result = Extracted(candidates={})
    token = url.strip().strip(",;|'\"()[]")

    # A bare showtime id is the least you can be asked to supply: reading
    # numbers off a page beats copying whole URLs.
    if token.isdigit():
        return Extracted(theatre_id="", showtime_id=token, candidates={})

    parsed = urllib.parse.urlparse(token)

    for pattern in _PAIR_PATTERNS:
        m = pattern.search(parsed.path)
        if m:
            return Extracted(theatre_id=m.group("theatre"),
                             showtime_id=m.group("showtime"), candidates={})

    # Query string, including params buried in a nested redirect URL.
    query = urllib.parse.parse_qs(parsed.query)
    for raw in list(query.values()):
        for value in raw:
            if "=" in value and ("http" in value or "&" in value):
                for k, v in urllib.parse.parse_qs(
                        urllib.parse.urlparse(value).query or value).items():
                    query.setdefault(k, v)

    lowered = {k.lower(): v[0] for k, v in query.items() if v}
    for key in _THEATRE_PARAMS:
        if key in lowered and lowered[key].isdigit():
            result.theatre_id = lowered[key]
            break
    for key in _SHOWTIME_PARAMS:
        if key in lowered and lowered[key].isdigit():
            result.showtime_id = lowered[key]
            break

    # Anything numeric left over, so a new URL shape is still recoverable.
    result.candidates = {k: v for k, v in lowered.items() if v.isdigit()}
    for i, seg in enumerate(s for s in parsed.path.split("/") if s.isdigit()):
        result.candidates.setdefault(f"path[{i}]", seg)
    return result
