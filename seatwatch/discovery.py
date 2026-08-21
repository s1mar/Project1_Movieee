"""Find showtimes for a film at a theatre over the next N days.

Parses the real Cineplex showtimes payload (captured live). The feed is
key-gated - it needs CINEPLEX_API_KEY - so discovery only runs when a key is
set, and the watcher falls back to hand-listed showtimes otherwise.

Payload shape (list-rooted):
    [ { theatre, theatreId, dates: [ { startDate, movies: [ {
          id, name, presentationType,
          experiences: [ { experienceTypes: [...], sessions: [ {
              vistaSessionId, showStartDateTime, seatsRemaining,
              isInThePast, isSoldOut, isReservedSeating, seatMapUrl, ...
          } ] } ]
    } ] } ] } ]
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Found:
    id: str
    starts_at: str = ""
    film_id: str = ""
    film_name: str = ""
    experiences: tuple = ()
    seats_remaining: int | None = None
    seat_map_url: str = ""

    @property
    def label(self) -> str:
        exp = "/".join(self.experiences)
        when = self.starts_at
        try:
            when = datetime.datetime.fromisoformat(
                self.starts_at[:19]).strftime("%a %-d %b, %-I:%M %p")
        except ValueError:
            pass
        return f"{when} ({exp})" if exp else when or f"showtime {self.id}"


def _as_list(node):
    return node if isinstance(node, list) else [node] if node else []


def find_showtimes(payload, film_id: str = "",
                   want_experiences: tuple = ()) -> list[Found]:
    """Every showtime for the film, optionally filtered by experience.

    want_experiences: e.g. ("IMAX", "70mm") keeps only sessions whose
    experienceTypes contain ALL of those. Empty keeps every experience.
    """
    out: dict[str, Found] = {}
    for theatre in _as_list(payload):
        if not isinstance(theatre, dict):
            continue
        for date in _as_list(theatre.get("dates")):
            if not isinstance(date, dict):
                continue
            for movie in _as_list(date.get("movies")):
                if not isinstance(movie, dict):
                    continue
                mid = str(movie.get("id", ""))
                if film_id and mid != str(film_id):
                    continue
                name = str(movie.get("name", ""))
                for exp in _as_list(movie.get("experiences")):
                    if not isinstance(exp, dict):
                        continue
                    types = tuple(str(t) for t in
                                  _as_list(exp.get("experienceTypes")))
                    if want_experiences and not all(
                            w in types for w in want_experiences):
                        continue
                    for s in _as_list(exp.get("sessions")):
                        _add(out, s, mid, name, types)
    return sorted(out.values(), key=lambda f: (f.starts_at, f.id))


def _add(out, session, film_id, film_name, types):
    if not isinstance(session, dict):
        return
    if session.get("isInThePast"):
        return  # Already screened; nothing to watch.
    if session.get("isReservedSeating") is False:
        return  # General admission - no seat map to watch.
    sid = session.get("vistaSessionId")
    if sid in (None, ""):
        return
    sid = str(sid)
    seats = session.get("seatsRemaining")
    out.setdefault(sid, Found(
        id=sid,
        starts_at=str(session.get("showStartDateTime", "")),
        film_id=str(film_id),
        film_name=film_name,
        experiences=types,
        seats_remaining=seats if isinstance(seats, int) else None,
        seat_map_url=str(session.get("seatMapUrl", "")),
    ))


def dates_ahead(days: int, today: datetime.date | None = None) -> list[str]:
    start = today or datetime.date.today()
    return [(start + datetime.timedelta(days=i)).isoformat()
            for i in range(max(1, days))]


def describe_shape(node, depth: int = 0, max_depth: int = 4) -> list[str]:
    """Keys-and-types outline of a payload, values omitted. For CI logs."""
    pad = "  " * depth
    if depth >= max_depth:
        return [f"{pad}..."]
    if isinstance(node, dict):
        lines = []
        for key, value in list(node.items())[:12]:
            if isinstance(value, (dict, list)):
                lines.append(f"{pad}{key}: {type(value).__name__}[{len(value)}]")
                lines.extend(describe_shape(value, depth + 1, max_depth))
            else:
                lines.append(f"{pad}{key}: {type(value).__name__}")
        if len(node) > 12:
            lines.append(f"{pad}... +{len(node) - 12} more keys")
        return lines
    if isinstance(node, list):
        return describe_shape(node[0], depth, max_depth) if node else [f"{pad}(empty)"]
    return [f"{pad}{type(node).__name__}"]
