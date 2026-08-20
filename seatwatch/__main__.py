"""seatwatch - watch a Cineplex showtime for seats that match your taste.

    python -m seatwatch check        one pass, print what matches, no alerts
    python -m seatwatch watch        poll for a while, alert on newly free seats
    python -m seatwatch dump         raw seat JSON, for fixing the parser
    python -m seatwatch discover     list showtimes for a date (needs API key)
    python -m seatwatch test-alert   prove the notification path works
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import config as config_mod
from .cineplex import (SEAT_AVAILABILITY, SEAT_LAYOUT, CineplexError, Client,
                       NotFound)
from .notify import Alert, dispatch
from .seats import Match, extract_seats, match_seats
from .state import State


def _client(cfg) -> Client:
    return Client(base_url=cfg.base_url, api_key=cfg.api_key)


def _paths(cfg) -> tuple[str, str]:
    return (cfg.availability_path or SEAT_AVAILABILITY,
            cfg.layout_path or SEAT_LAYOUT)


def _describe(matches: list[Match], limit: int = 8) -> str:
    best = matches[:limit]
    parts = [f"{m.label} ({int(m.score * 100)}% centred)" for m in best]
    extra = len(matches) - len(best)
    if extra > 0:
        parts.append(f"+{extra} more")
    return ", ".join(parts)


def poll_once(cfg, client, showtime, verbose=True):
    """Fetch and match one showtime. Returns (matches, total_available)."""
    avail_path, layout_path = _paths(cfg)
    theatre = showtime.theatre_id or cfg.theatre_id
    payload = client.seat_map(theatre, showtime.id, avail_path, layout_path)
    seats = extract_seats(payload)
    if not seats and verbose:
        print(f"  ! parsed 0 seats for {showtime.id}; "
              f"run `dump` to inspect the payload")
    matches = match_seats(seats, cfg.criteria)
    free = sum(1 for s in seats if s.available)
    if verbose:
        name = showtime.label or showtime.id
        print(f"  {name}: {len(seats)} seats, {free} free, "
              f"{len(matches)} matching"
              + (f" -> {_describe(matches)}" if matches else ""))
    return matches, free


def cmd_check(args, cfg):
    client = _client(cfg)
    if not cfg.showtimes:
        print("No showtimes configured. Add them to seatwatch/config.toml.")
        return 2
    found = 0
    for showtime in cfg.showtimes:
        try:
            matches, _ = poll_once(cfg, client, showtime)
            found += len(matches)
        except NotFound:
            print(f"  {showtime.label or showtime.id}: gone (delisted or past)")
        except CineplexError as exc:
            print(f"  {showtime.label or showtime.id}: ERROR {exc}")
            return 1
    print(f"\n{found} matching seat(s) right now.")
    return 0


def cmd_watch(args, cfg):
    client = _client(cfg)
    state = State.load(cfg.state_path)
    if not cfg.showtimes:
        print("No showtimes configured. Add them to seatwatch/config.toml.")
        return 2

    deadline = time.time() + cfg.duration_seconds
    live_keys = {s.key(cfg.theatre_id) for s in cfg.showtimes}
    alerts_sent = 0
    passes = 0

    while True:
        passes += 1
        print(f"[pass {passes}] {time.strftime('%H:%M:%S')}")
        for showtime in cfg.showtimes:
            key = showtime.key(cfg.theatre_id)
            try:
                matches, _ = poll_once(cfg, client, showtime)
            except NotFound:
                print(f"  {showtime.label or showtime.id}: gone; skipping")
                continue
            except CineplexError as exc:
                print(f"  {showtime.label or showtime.id}: ERROR {exc}")
                continue

            labels = [m.label for m in matches]
            first_run = state.is_first_run(key)
            if first_run and not cfg.alert_on_first_run:
                fresh = []
            else:
                fresh = state.newly_available(key, labels, cfg.cooldown_seconds)

            alerted = []
            if fresh:
                best = [m for m in matches if m.label in fresh]
                alert = _build_alert(cfg, showtime, best, first_run)
                delivered = dispatch(alert)
                if delivered:
                    alerted = fresh
                    alerts_sent += 1
                    print(f"  >> ALERTED via {', '.join(delivered)}: "
                          f"{', '.join(fresh)}")
                else:
                    print(f"  !! no channel delivered; will retry next pass")
            state.record(key, labels, alerted)

        state.prune(live_keys)
        state.save()

        if time.time() + cfg.interval_seconds >= deadline:
            break
        time.sleep(cfg.interval_seconds)

    print(f"\nDone: {passes} passes, {alerts_sent} alert(s) sent.")
    return 0


def _build_alert(cfg, showtime, matches, first_run):
    when = showtime.label or f"showtime {showtime.id}"
    count = len(matches)
    seat_word = "seat" if count == 1 else "seats"
    verb = "available" if first_run else "just opened up"
    title = f"{count} {seat_word} {verb} - {when}"
    lines = [
        f"{cfg.theatre_name or 'Cineplex'} - {when}",
        f"Rows {cfg.criteria.min_row}+ , middle of the row:",
        "",
        _describe(matches, limit=12),
        "",
        "Cancellations go fast - book now.",
    ]
    return Alert(title=title, body="\n".join(lines),
                 url=showtime.url or cfg.booking_url)


def cmd_dump(args, cfg):
    client = _client(cfg)
    avail_path, layout_path = _paths(cfg)
    theatre = args.theatre or cfg.theatre_id
    showtime = args.showtime or (cfg.showtimes[0].id if cfg.showtimes else "")
    if not theatre or not showtime:
        print("Need --theatre and --showtime (or entries in config.toml).")
        return 2
    payload = client.seat_map(theatre, showtime, avail_path, layout_path)
    print(json.dumps(payload, indent=2)[:args.limit])
    seats = extract_seats(payload)
    print(f"\n--- parser saw {len(seats)} seats, "
          f"{sum(1 for s in seats if s.available)} available ---")
    for seat in seats[:20]:
        print(f"  {seat.label:>6}  {'free' if seat.available else 'sold'}"
              f"  {seat.seat_type}")
    return 0


def cmd_discover(args, cfg):
    client = _client(cfg)
    if not cfg.api_key:
        print("discover needs CINEPLEX_API_KEY; the showtimes feed is gated.")
        return 2
    payload = client.showtimes(cfg.location_id or cfg.theatre_id, args.date)
    print(json.dumps(payload, indent=2)[:args.limit])
    return 0


def cmd_test_alert(args, cfg):
    alert = Alert(
        title="seatwatch test",
        body="If you can read this, alerts work. Real ones name the seats.",
        url=cfg.booking_url, priority="default")
    delivered = dispatch(alert)
    if delivered:
        print(f"Delivered via: {', '.join(delivered)}")
        return 0
    print("No channel delivered. Set NTFY_TOPIC (and/or WEBHOOK_URL).")
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="seatwatch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check")
    sub.add_parser("watch")
    sub.add_parser("test-alert")

    d = sub.add_parser("dump")
    d.add_argument("--theatre")
    d.add_argument("--showtime")
    d.add_argument("--limit", type=int, default=6000)

    disc = sub.add_parser("discover")
    disc.add_argument("--date", required=True, help="YYYY-MM-DD")
    disc.add_argument("--limit", type=int, default=6000)

    args = parser.parse_args(argv)
    cfg = config_mod.load(args.config)

    handlers = {"check": cmd_check, "watch": cmd_watch, "dump": cmd_dump,
                "discover": cmd_discover, "test-alert": cmd_test_alert}
    return handlers[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
