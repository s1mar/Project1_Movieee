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
from .config import Showtime
from .cineplex import (SEAT_AVAILABILITY, SEAT_LAYOUT, CineplexError, Client,
                       NotFound, PostShowtime)
from .discovery import dates_ahead, describe_shape, find_showtimes
from .notify import Alert, dispatch
from .seats import Match, extract_seats, match_seats, parse_seatmap
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
    layout, availability = client.seat_map(theatre, showtime.id,
                                           avail_path, layout_path)
    seats = parse_seatmap(layout, availability)
    if not seats:
        # Unrecognised shape - fall back to the generic walker rather than
        # reporting a sold-out house.
        seats = extract_seats(availability) or extract_seats(layout)
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
        except (NotFound, PostShowtime):
            print(f"  {showtime.label or showtime.id}: gone (delisted or past)")
        except CineplexError as exc:
            print(f"  {showtime.label or showtime.id}: ERROR {exc}")
            return 1
    print(f"\n{found} matching seat(s) right now.")
    return 0


def discover_showtimes(cfg, client) -> list:
    """Every showtime for the configured film over the next N days.

    Needs CINEPLEX_API_KEY - the showtimes feed is the one gated endpoint.
    Returns [] (and says why) rather than failing the run, so a missing key
    degrades to the hand-listed showtimes instead of breaking the watcher.
    """
    if not cfg.discover_days:
        return []
    if not cfg.api_key:
        print("  discovery is on but CINEPLEX_API_KEY is unset; "
              "falling back to the showtimes listed in config.toml")
        return []

    location = cfg.location_id or cfg.theatre_id
    found: dict[str, Showtime] = {}
    sample = None
    for date in dates_ahead(cfg.discover_days):
        try:
            payload = client.showtimes(location, date)
        except CineplexError as exc:
            print(f"  discovery failed for {date}: {str(exc)[:120]}")
            continue
        sample = sample if sample is not None else payload
        for hit in find_showtimes(payload, cfg.film_id):
            found.setdefault(hit.id, Showtime(
                id=hit.id, label=hit.label,
                url=f"https://www.cineplex.com/ticketing/preview"
                    f"?theatreId={location}&showtimeId={hit.id}"))
    if found:
        print(f"  discovered {len(found)} showtime(s) over "
              f"{cfg.discover_days} day(s)")
    elif sample is not None:
        # The showtimes shape is unverified. Print its outline (keys and
        # types only, never values) so a failed parse is diagnosable from
        # the run log instead of needing a local repro.
        print("  discovery parsed 0 showtimes. Payload outline:")
        for line in describe_shape(sample)[:40]:
            print(f"    {line}")
    return list(found.values())


def plan_cadence(cfg, showtime_count: int) -> tuple[int, int]:
    """How many passes to make, and how long to wait between them.

    Polling every showtime on every pass does not scale: a week of slots at
    the single-showtime cadence would be thousands of requests an hour
    against someone else's ticketing API. The run gets a request budget and
    spreads whatever passes it can afford across its duration instead.
    """
    count = max(1, showtime_count)
    affordable = max(1, cfg.max_requests_per_run // count)
    by_time = max(1, cfg.duration_seconds // cfg.interval_seconds + 1)
    passes = min(affordable, by_time)
    interval = (max(cfg.interval_seconds, cfg.duration_seconds // passes)
                if passes > 1 else cfg.interval_seconds)
    return passes, int(interval)


def cmd_watch(args, cfg):
    client = _client(cfg)
    state = State.load(cfg.state_path)

    discovered = discover_showtimes(cfg, client)
    known = {s.id for s in cfg.showtimes}
    cfg.showtimes = cfg.showtimes + [s for s in discovered if s.id not in known]

    if not cfg.showtimes:
        print("No showtimes configured. Add them to seatwatch/config.toml "
              "or enable [discovery] with an API key.")
        return 2

    passes_planned, interval = plan_cadence(cfg, len(cfg.showtimes))
    print(f"{len(cfg.showtimes)} showtime(s): {passes_planned} pass(es) "
          f"every {interval}s (budget {cfg.max_requests_per_run} req/run)")

    deadline = time.time() + cfg.duration_seconds
    live_keys = {s.key(cfg.theatre_id) for s in cfg.showtimes}
    alerts_sent = 0
    passes = 0
    gone: set[str] = set()

    while True:
        passes += 1
        print(f"[pass {passes}] {time.strftime('%H:%M:%S')}")
        for showtime in cfg.showtimes:
            key = showtime.key(cfg.theatre_id)
            try:
                matches, _, healthy = poll_once(cfg, client, showtime)
                problem = "" if healthy else "the parser saw zero seats"
            except (NotFound, PostShowtime):
                print(f"  {showtime.label or showtime.id}: gone; skipping")
                state.note_health(key, True)
                gone.add(key)
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

        # Every screening has been and gone. Without this the watcher would
        # poll an empty list forever, and silence would read as "no seats"
        # when it actually means "nothing left to watch".
        if cfg.showtimes and gone >= live_keys:
            if state.note_health("__watchlist__", False, warn_after=1):
                nudge = Alert(
                    title="seatwatch has nothing left to watch",
                    body=(f"All {len(live_keys)} watched showtime(s) have "
                          f"screened or been delisted.\n\nAdd more with "
                          f"`seatwatch add-showtime --url ...`, or enable "
                          f"[discovery] with an API key."),
                    url=cfg.booking_url, priority="default")
                if dispatch(nudge):
                    print("  >> watchlist-empty notice sent")
        elif gone < live_keys:
            state.note_health("__watchlist__", True)

        state.prune(live_keys | {"__watchlist__"})
        state.save()

        if passes >= passes_planned or time.time() + interval >= deadline:
            break
        time.sleep(interval)

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
        f"Rows {cfg.criteria.min_row}+, middle of the row:",
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
    layout, availability = client.seat_map(theatre, showtime,
                                           avail_path, layout_path)
    print("--- availability (truncated) ---")
    print(json.dumps(availability, indent=2)[:args.limit // 2])
    print("\n--- layout (truncated) ---")
    print(json.dumps(layout, indent=2)[:args.limit // 2])
    seats = parse_seatmap(layout, availability)
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
    """Turn pasted seat-picker URLs into [[showtimes]] blocks.

    Accepts any number of URLs, in any amount of whitespace - so the output
    of a browser console snippet, or a column copied off a page, can be
    pasted straight in without splitting it up by hand.
    """
    raw = " ".join(args.url)
    candidates = [u for u in raw.split() if u.strip()]
    if not candidates:
        print("No URLs given.")
        return 2

    path = pathlib.Path(args.config) if args.config else config_mod.DEFAULT_PATH
    existing = {s.id for s in cfg.showtimes}
    added, skipped, failed = [], [], []

    for url in candidates:
        found = extract_ids(url)
        if args.showtime_id and len(candidates) == 1:
            found.showtime_id = args.showtime_id
        if not found.showtime_id:
            failed.append((url, found.candidates))
            continue
        if found.showtime_id in existing:
            skipped.append(found.showtime_id)
            continue
        existing.add(found.showtime_id)

        block = ["", "[[showtimes]]", f'id = "{found.showtime_id}"']
        label = args.label if (args.label and len(candidates) == 1) else ""
        if label:
            block.append(f'label = "{label}"')
        block.append(f'url = "{url}"')
        if found.theatre_id and found.theatre_id != cfg.theatre_id:
            block.append(f'theatre_id = "{found.theatre_id}"')
        with path.open("a") as fh:
            fh.write("\n".join(block) + "\n")
        added.append(found.showtime_id)

    if added:
        print(f"Added {len(added)} showtime(s) to {path}: {', '.join(added)}")
    if skipped:
        print(f"Already present, skipped: {', '.join(skipped)}")
    for url, cands in failed:
        print(f"No showtime ID in: {url[:80]}")
        if cands:
            print("  numbers found: "
                  + ", ".join(f"{k}={v}" for k, v in cands.items()))
    if added:
        print("\nNext: python -m seatwatch check")
    return 0 if added or skipped else 2


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
    add.add_argument("--url", required=True, nargs="+",
                     help="one or more seat-picker URLs; whitespace-separated "
                          "blobs are split, so a whole paste works")
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
