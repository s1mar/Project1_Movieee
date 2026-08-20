"""seatwatch - watch a Cineplex showtime for seats that match your taste.

    python -m seatwatch check        one pass, print what matches, no alerts
    python -m seatwatch watch        poll for a while, alert on newly free seats
    python -m seatwatch dump         raw seat JSON, for fixing the parser
    python -m seatwatch discover     list showtimes for a date (needs API key)
    python -m seatwatch add-showtime paste a seat-picker URL, get a config block
    python -m seatwatch test-alert   prove the notification path works
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

from . import config as config_mod
from .cineplex import (SEAT_AVAILABILITY, SEAT_LAYOUT, CineplexError, Client,
                       NotFound)
from .notify import Alert, dispatch
from .seats import Match, extract_seats, match_seats
from .urlparse_ids import extract as extract_ids
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
    """Fetch and match one showtime.

    Returns (matches, free_count, healthy). `healthy` is False when the
    parser saw no seats at all, which means the payload shape changed -
    not that the show is empty.
    """
    avail_path, layout_path = _paths(cfg)
    theatre = showtime.theatre_id or cfg.theatre_id
    payload = client.seat_map(theatre, showtime.id, avail_path, layout_path)
    seats = extract_seats(payload)
    if not seats and verbose:
        print(f"  ! parsed 0 seats for {showtime.id}; "
              f"run `dump` to inspect the payload")
    matches = match_seats(seats, cfg.criteria)
    free = sum(1 for s in seats if s.available)
    healthy = bool(seats)
    if verbose:
        name = showtime.label or showtime.id
        print(f"  {name}: {len(seats)} seats, {free} free, "
              f"{len(matches)} matching"
              + (f" -> {_describe(matches)}" if matches else ""))
    return matches, free, healthy


def cmd_check(args, cfg):
    client = _client(cfg)
    if not cfg.showtimes:
        print("No showtimes configured. Add them to seatwatch/config.toml.")
        return 2
    found = 0
    for showtime in cfg.showtimes:
        try:
            matches, _, _ = poll_once(cfg, client, showtime)
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
                matches, _, healthy = poll_once(cfg, client, showtime)
                problem = "" if healthy else "the parser saw zero seats"
            except NotFound:
                print(f"  {showtime.label or showtime.id}: gone; skipping")
                state.note_health(key, True)
                continue
            except CineplexError as exc:
                matches, healthy, problem = [], False, str(exc)
                print(f"  {showtime.label or showtime.id}: ERROR {exc}")

            if state.note_health(key, healthy, cfg.health_warn_after):
                warn = Alert(
                    title="seatwatch is broken, not quiet",
                    body=(f"{cfg.health_warn_after} polls in a row failed for "
                          f"{showtime.label or showtime.id}.\n\n{problem}\n\n"
                          f"Silence from here means nothing until this is "
                          f"fixed. Run: python -m seatwatch dump"),
                    url=showtime.url or cfg.booking_url, priority="default")
                if dispatch(warn):
                    print("  >> health warning sent")
            if not healthy:
                state.record(key, [], [])
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
                 url=showtime.url or cfg.booking_url, priority=cfg.priority)


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
    film = args.film_id or cfg.film_id
    if film:
        # Keep only the branches mentioning this film, so the dump is the
        # Odyssey's showtimes rather than the whole day's programme.
        blob = json.dumps(payload)
        if film not in blob:
            print(f"No sign of film {film} at this theatre on {args.date}.")
            return 0
    print(json.dumps(payload, indent=2)[:args.limit])
    return 0


def cmd_add_showtime(args, cfg):
    """Turn a pasted seat-picker URL into a [[showtimes]] block."""
    found = extract_ids(args.url)
    if args.showtime_id:
        found.showtime_id = args.showtime_id
    theatre = found.theatre_id or cfg.theatre_id
    if not found.showtime_id:
        print("Could not find a showtime ID in that URL.")
        if found.candidates:
            print("Numbers I did find - if one is the showtime, pass it with "
                  "--showtime-id:")
            for key, value in found.candidates.items():
                print(f"  {key} = {value}")
        return 2
    if found.theatre_id and cfg.theatre_id and found.theatre_id != cfg.theatre_id:
        print(f"Note: URL theatre {found.theatre_id} differs from configured "
              f"{cfg.theatre_id}; using the URL's.")

    block = ["", "[[showtimes]]", f'id = "{found.showtime_id}"']
    if args.label:
        block.append(f'label = "{args.label}"')
    block.append(f'url = "{args.url.strip()}"')
    if found.theatre_id and found.theatre_id != cfg.theatre_id:
        block.append(f'theatre_id = "{found.theatre_id}"')
    text = "\n".join(block) + "\n"

    path = pathlib.Path(args.config) if args.config else config_mod.DEFAULT_PATH
    with path.open("a") as fh:
        fh.write(text)
    print(f"Appended to {path}:{text}")
    print(f"Now run:  python -m seatwatch dump --theatre {theatre} "
          f"--showtime {found.showtime_id}")
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

    add = sub.add_parser("add-showtime")
    add.add_argument("--url", required=True,
                     help="seat-picker URL copied from the address bar")
    add.add_argument("--label", default="", help='e.g. "Fri 21 Aug, 7:00 PM"')
    add.add_argument("--showtime-id", default="",
                     help="override if the URL shape is unrecognised")

    disc = sub.add_parser("discover")
    disc.add_argument("--date", required=True, help="YYYY-MM-DD")
    disc.add_argument("--limit", type=int, default=6000)
    disc.add_argument("--film-id", default="", help="defaults to config film_id")

    args = parser.parse_args(argv)
    cfg = config_mod.load(args.config)

    handlers = {"check": cmd_check, "watch": cmd_watch, "dump": cmd_dump,
                "discover": cmd_discover, "test-alert": cmd_test_alert,
                "add-showtime": cmd_add_showtime}
    return handlers[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
