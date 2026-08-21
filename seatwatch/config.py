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
    starts: str = ""  # ISO start datetime, for proximity-weighted polling.
    booking_url: str = ""  # direct browser booking flow (fallback button)

    def key(self, default_theatre: str) -> str:
        return f"{self.theatre_id or default_theatre}:{self.id}"

    def hours_until(self, now: float) -> float:
        """Hours from `now` (epoch seconds) until the show starts.

        Returns a large sentinel when the start time is unknown, so
        unknowns are treated as far-off rather than imminent.
        """
        if not self.starts:
            return 1e6
        import datetime
        try:
            dt = datetime.datetime.fromisoformat(self.starts[:19])
        except ValueError:
            return 1e6
        return (dt.timestamp() - now) / 3600.0


@dataclass
class Config:
    theatre_id: str = ""
    location_id: str = ""
    theatre_name: str = ""
    booking_url: str = ""
    film_id: str = ""
    priority: str = "high"
    android_app_package: str = ""  # e.g. com.fivemobile.cineplex -> app-open link
    criteria: Criteria = field(default_factory=Criteria)
    showtimes: list[Showtime] = field(default_factory=list)
    interval_seconds: int = 45
    duration_seconds: int = 270
    cooldown_seconds: int = 6 * 3600
    alert_on_first_run: bool = True
    state_path: str = "state.json"
    health_warn_after: int = 3
    max_requests_per_run: int = 30
    discover_days: int = 0
    discover_experiences: tuple = ()
    base_url: str = "https://apis.cineplex.com"
    availability_path: str = ""
    layout_path: str = ""
    control_since: str = "12h"
    control_topic_cfg: str = ""

    @property
    def api_key(self) -> str:
        return os.environ.get("CINEPLEX_API_KEY", "")

    @property
    def control_topic(self) -> str:
        # Topic you type pause/resume/status into. Prefer the CONTROL_TOPIC
        # secret (private); fall back to the value committed in config.toml.
        # The committed one is readable in a public repo, so anyone could
        # send pause/resume - fine for a personal seat watcher; set the
        # secret to keep the channel private.
        return os.environ.get("CONTROL_TOPIC") or self.control_topic_cfg

    @property
    def ntfy_server(self) -> str:
        return os.environ.get("NTFY_SERVER") or "https://ntfy.sh"


def load(path: str | pathlib.Path | None = None) -> Config:
    p = pathlib.Path(path) if path else DEFAULT_PATH
    raw = tomllib.loads(p.read_text())

    theatre = raw.get("theatre", {})
    crit = raw.get("criteria", {})
    poll = raw.get("poll", {})
    api = raw.get("api", {})
    alerts = raw.get("alerts", {})
    disc = raw.get("discovery", {})

    cfg = Config(
        theatre_id=str(theatre.get("id", "")),
        location_id=str(theatre.get("location_id", theatre.get("id", ""))),
        theatre_name=theatre.get("name", ""),
        booking_url=theatre.get("booking_url", ""),
        film_id=str(theatre.get("film_id", "")),
        priority=str(alerts.get("priority", "high")),
        android_app_package=str(alerts.get("android_app_package", "")),
        criteria=Criteria(
            min_row=str(crit.get("min_row", "E")),
            max_row=str(crit["max_row"]) if crit.get("max_row") else None,
            max_centre_offset=float(crit.get("max_centre_offset", 0.5)),
            include_accessible=bool(crit.get("include_accessible", False)),
            min_adjacent=int(crit.get("min_adjacent", 1)),
        ),
        showtimes=[
            Showtime(id=str(s["id"]), label=s.get("label", ""),
                     url=s.get("url", ""), theatre_id=str(s.get("theatre_id", "")),
                     starts=str(s.get("starts", "")),
                     booking_url=str(s.get("booking_url", "")))
            for s in raw.get("showtimes", []) if s.get("id")
        ],
        interval_seconds=int(poll.get("interval_seconds", 45)),
        duration_seconds=int(poll.get("duration_seconds", 270)),
        cooldown_seconds=int(poll.get("cooldown_seconds", 6 * 3600)),
        alert_on_first_run=bool(poll.get("alert_on_first_run", True)),
        state_path=poll.get("state_path", "state.json"),
        health_warn_after=int(poll.get("health_warn_after", 3)),
        max_requests_per_run=int(poll.get("max_requests_per_run", 30)),
        discover_days=int(disc.get("days", 0)) if disc.get("enabled") else 0,
        discover_experiences=tuple(disc.get("experiences", [])),
        base_url=api.get("base_url", "https://apis.cineplex.com"),
        availability_path=api.get("availability_path", ""),
        layout_path=api.get("layout_path", ""),
        control_since=str(raw.get("control", {}).get("since", "12h")),
        control_topic_cfg=str(raw.get("control", {}).get("topic", "")),
    )

    # Never poll faster than every 20s - this is someone else's ticketing API.
    cfg.interval_seconds = max(20, cfg.interval_seconds)
    return cfg
