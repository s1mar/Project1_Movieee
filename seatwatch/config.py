"""Config loading. TOML via the stdlib, so still no third-party deps."""

from __future__ import annotations

import os
import pathlib
import tomllib
from dataclasses import dataclass, field

from .seats import Criteria

DEFAULT_PATH = pathlib.Path(__file__).parent / "config.toml"


@dataclass
class Showtime:
    id: str
    label: str = ""
    url: str = ""
    theatre_id: str = ""

    def key(self, default_theatre: str) -> str:
        return f"{self.theatre_id or default_theatre}:{self.id}"


@dataclass
class Config:
    theatre_id: str = ""
    location_id: str = ""
    theatre_name: str = ""
    booking_url: str = ""
    film_id: str = ""
    priority: str = "high"
    criteria: Criteria = field(default_factory=Criteria)
    showtimes: list[Showtime] = field(default_factory=list)
    interval_seconds: int = 45
    duration_seconds: int = 270
    cooldown_seconds: int = 6 * 3600
    alert_on_first_run: bool = True
    state_path: str = "state.json"
    health_warn_after: int = 3
    base_url: str = "https://apis.cineplex.com"
    availability_path: str = ""
    layout_path: str = ""

    @property
    def api_key(self) -> str:
        return os.environ.get("CINEPLEX_API_KEY", "")


def load(path: str | pathlib.Path | None = None) -> Config:
    p = pathlib.Path(path) if path else DEFAULT_PATH
    raw = tomllib.loads(p.read_text())

    theatre = raw.get("theatre", {})
    crit = raw.get("criteria", {})
    poll = raw.get("poll", {})
    api = raw.get("api", {})
    alerts = raw.get("alerts", {})

    cfg = Config(
        theatre_id=str(theatre.get("id", "")),
        location_id=str(theatre.get("location_id", theatre.get("id", ""))),
        theatre_name=theatre.get("name", ""),
        booking_url=theatre.get("booking_url", ""),
        film_id=str(theatre.get("film_id", "")),
        priority=str(alerts.get("priority", "high")),
        criteria=Criteria(
            min_row=str(crit.get("min_row", "E")),
            max_row=str(crit["max_row"]) if crit.get("max_row") else None,
            max_centre_offset=float(crit.get("max_centre_offset", 0.5)),
            include_accessible=bool(crit.get("include_accessible", False)),
            min_adjacent=int(crit.get("min_adjacent", 1)),
        ),
        showtimes=[
            Showtime(id=str(s["id"]), label=s.get("label", ""),
                     url=s.get("url", ""), theatre_id=str(s.get("theatre_id", "")))
            for s in raw.get("showtimes", []) if s.get("id")
        ],
        interval_seconds=int(poll.get("interval_seconds", 45)),
        duration_seconds=int(poll.get("duration_seconds", 270)),
        cooldown_seconds=int(poll.get("cooldown_seconds", 6 * 3600)),
        alert_on_first_run=bool(poll.get("alert_on_first_run", True)),
        state_path=poll.get("state_path", "state.json"),
        health_warn_after=int(poll.get("health_warn_after", 3)),
        base_url=api.get("base_url", "https://apis.cineplex.com"),
        availability_path=api.get("availability_path", ""),
        layout_path=api.get("layout_path", ""),
    )

    # Never poll faster than every 20s - this is someone else's ticketing API.
    cfg.interval_seconds = max(20, cfg.interval_seconds)
    return cfg
