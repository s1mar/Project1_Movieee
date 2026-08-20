"""Seat-map parsing, filtering and ranking.

The Cineplex ticketing API is undocumented, so the exact JSON shape is not
guaranteed to be stable. Rather than bind to one nesting, `extract_seats`
walks the payload and picks out anything that looks like a seat record,
inheriting row names from enclosing row objects. That keeps the watcher
alive across cosmetic API changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# Field-name candidates, lowercased. Order matters: earlier names win.
_ROW_KEYS = ("rowname", "row", "rowlabel", "rowid", "rowindex")
_COL_KEYS = ("columnname", "seatnumber", "seatname", "column", "colname",
             "number", "seatlabel", "columnindex", "col")
_AVAIL_KEYS = ("isavailable", "available", "isopen", "isfree")
_STATUS_KEYS = ("status", "seatstatus", "state", "availabilitystatus")
_TYPE_KEYS = ("seattype", "type", "seatstyle", "category")

_AVAILABLE_WORDS = {"available", "open", "free", "unsold", "vacant", "0", "a"}
_UNAVAILABLE_WORDS = {"sold", "unavailable", "taken", "occupied", "reserved",
                      "held", "broken", "blocked", "house", "notavailable"}

# Seat types we skip unless the user opts in - grabbing a wheelchair or
# companion seat you don't need takes it from someone who does.
_ACCESSIBLE_WORDS = {"wheelchair", "companion", "accessible", "handicap",
                     "transfer"}


@dataclass(frozen=True)
class Seat:
    row: str
    col: str
    available: bool
    seat_type: str = ""
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def label(self) -> str:
        return f"{self.row}{self.col}"

    @property
    def is_accessible(self) -> bool:
        blob = f"{self.seat_type} {self.raw.get('seatTypeName', '')}".lower()
        return any(w in blob for w in _ACCESSIBLE_WORDS)


def _first(d: dict, keys: Iterable[str]) -> Any:
    lowered = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k in lowered and lowered[k] not in (None, ""):
            return lowered[k]
    return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _read_availability(d: dict) -> bool | None:
    """True/False if the record states availability, None if it doesn't."""
    flag = _first(d, _AVAIL_KEYS)
    if isinstance(flag, bool):
        return flag
    if flag is not None and _norm(flag) in ("true", "false"):
        return _norm(flag) == "true"

    status = _first(d, _STATUS_KEYS)
    if status is not None:
        s = _norm(status)
        if s in _AVAILABLE_WORDS:
            return True
        if s in _UNAVAILABLE_WORDS or any(w in s for w in _UNAVAILABLE_WORDS):
            return False
        if "available" in s:  # e.g. "NotAvailable" already caught above
            return True
    return None


def extract_seats(payload: Any) -> list[Seat]:
    """Walk an arbitrary seat-map payload and collect every seat record."""
    found: list[Seat] = []
    _walk(payload, inherited_row=None, out=found)
    # De-duplicate on (row, col) - some payloads repeat seats across
    # a layout section and an availability section.
    seen: dict[tuple[str, str], Seat] = {}
    for seat in found:
        # First mention wins; records with no availability verdict were
        # already dropped by _walk, so every survivor here is equally good.
        seen.setdefault((seat.row, seat.col), seat)
    return sorted(seen.values(), key=lambda s: (row_ordinal(s.row), col_number(s.col)))


def _walk(node: Any, inherited_row: str | None, out: list[Seat]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, inherited_row, out)
        return
    if not isinstance(node, dict):
        return

    row_here = _first(node, _ROW_KEYS)
    row_ctx = str(row_here) if row_here is not None else inherited_row

    col = _first(node, _COL_KEYS)
    if col is not None and row_ctx is not None and not _has_child_seats(node):
        avail = _read_availability(node)
        if avail is not None:
            out.append(Seat(
                row=str(row_ctx).strip().upper(),
                col=str(col).strip(),
                available=avail,
                seat_type=str(_first(node, _TYPE_KEYS) or ""),
                raw=node,
            ))
            return

    for value in node.values():
        _walk(value, row_ctx, out)


def _has_child_seats(node: dict) -> bool:
    """A row object carries a list of seats; a seat object does not."""
    for key, value in node.items():
        if "seat" in key.lower() and isinstance(value, list) and value:
            if any(isinstance(v, dict) for v in value):
                return True
    return False


def row_ordinal(row: str) -> int:
    """Order rows front-to-back: A=1 ... Z=26, AA=27, AB=28 ..."""
    r = re.sub(r"[^A-Z]", "", str(row).upper())
    if not r:
        digits = re.sub(r"[^0-9]", "", str(row))
        return int(digits) if digits else 0
    value = 0
    for ch in r:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value


def col_number(col: str) -> int:
    digits = re.sub(r"[^0-9]", "", str(col))
    return int(digits) if digits else 0


@dataclass(frozen=True)
class Criteria:
    min_row: str = "E"
    max_row: str | None = None
    # 0.0 = dead centre of the row, 1.0 = the outermost seat. 0.5 keeps the
    # middle half of each row.
    max_centre_offset: float = 0.5
    include_accessible: bool = False
    min_adjacent: int = 1


@dataclass(frozen=True)
class Match:
    seat: Seat
    centre_offset: float
    score: float

    @property
    def label(self) -> str:
        return self.seat.label


def row_extent(seats: list[Seat], row: str) -> tuple[int, int]:
    """Leftmost and rightmost column number physically present in a row."""
    cols = [col_number(s.col) for s in seats if s.row == row]
    cols = [c for c in cols if c]
    return (min(cols), max(cols)) if cols else (0, 0)


def centre_offset(seats: list[Seat], seat: Seat) -> float:
    """How far from the middle of its row a seat sits, as 0.0-1.0."""
    lo, hi = row_extent(seats, seat.row)
    if hi <= lo:
        return 0.0
    centre = (lo + hi) / 2
    half_width = (hi - lo) / 2
    return abs(col_number(seat.col) - centre) / half_width


def match_seats(seats: list[Seat], criteria: Criteria) -> list[Match]:
    """Available seats meeting the criteria, best (most central) first."""
    lo_row = row_ordinal(criteria.min_row)
    hi_row = row_ordinal(criteria.max_row) if criteria.max_row else None

    matches: list[Match] = []
    for seat in seats:
        if not seat.available:
            continue
        if not criteria.include_accessible and seat.is_accessible:
            continue
        ordinal = row_ordinal(seat.row)
        if ordinal < lo_row or (hi_row is not None and ordinal > hi_row):
            continue
        offset = centre_offset(seats, seat)
        if offset > criteria.max_centre_offset:
            continue
        matches.append(Match(seat=seat, centre_offset=offset,
                             score=round(1.0 - offset, 4)))

    if criteria.min_adjacent > 1:
        matches = _require_adjacent(matches, criteria.min_adjacent)

    matches.sort(key=lambda m: (-m.score, row_ordinal(m.seat.row),
                                col_number(m.seat.col)))
    return matches


def _require_adjacent(matches: list[Match], n: int) -> list[Match]:
    """Keep only seats sitting in a run of >= n consecutive free seats."""
    by_row: dict[str, list[Match]] = {}
    for m in matches:
        by_row.setdefault(m.seat.row, []).append(m)

    kept: list[Match] = []
    for row_matches in by_row.values():
        row_matches.sort(key=lambda m: col_number(m.seat.col))
        run: list[Match] = []
        for m in row_matches:
            if run and col_number(m.seat.col) != col_number(run[-1].seat.col) + 1:
                if len(run) >= n:
                    kept.extend(run)
                run = []
            run.append(m)
        if len(run) >= n:
            kept.extend(run)
    return kept
