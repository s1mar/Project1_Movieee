# seatwatch

Polls a Cineplex showtime's seat map on a GitHub Actions cron and pushes to
your phone when a seat you'd actually want frees up. Built for *The Odyssey*
in IMAX 70mm at Cinéma Banque Scotia Montréal, but the criteria are config.

Standard library only — no `pip install` step, so each run is a few seconds
of compute. This repo is public, so Actions minutes are free.

## Read this before you set it up

Three things you should know, because they affect whether this works for you:

1. **Cineplex's `robots.txt` disallows all non-search-engine automated
   access to the whole site** (`User-agent: * / Disallow: /`), and their
   terms discourage automated collection. This tool polls a JSON endpoint
   rather than crawling pages, identifies itself honestly in its
   `User-Agent`, and defaults to one request per showtime per 45 seconds —
   but it is still automated access to a site that asks you not to. That's
   your call to make, not mine. Keep the interval slow and the showtime list
   short.
2. **The seat endpoint is undocumented.** It was identified from public
   community projects, not Cineplex documentation. It can change or start
   requiring a key without notice. The parser is deliberately loose so
   cosmetic changes don't break it, and `dump` exists to show you what's
   actually coming back. This part is **not verified against the live API** —
   see "First run" below.
3. **`schedule:` cron is best-effort.** GitHub queues scheduled jobs and
   frequently runs them late — 10 to 30 minutes late is normal at peak, and
   runs can be dropped entirely. That's why one run polls repeatedly for
   ~4.5 minutes instead of taking a single snapshot. Treat the alert as
   "a seat opened recently", not "a seat opened 5 seconds ago".

## Setup

### 1. Add the showtimes

The theatre is already configured — `theatreId 9406`, Cinéma Banque Scotia
Montréal, read from `props.pageProps.theatreDetails` in that theatre page's
`__NEXT_DATA__`. The film is `38376`.

Showtime IDs change per screening, so add one per showing you want watched.
Open the showtime on cineplex.com, click through to the seat picker, copy the
address bar, and:

```bash
python -m seatwatch add-showtime \
  --url "<paste>" --label "Fri 21 Aug, 7:00 PM"
```

That pulls the IDs out of the URL and appends the `[[showtimes]]` block. If
the URL shape isn't one it recognises, it prints every number it found so you
can pass the right one with `--showtime-id`. With an API key set,
`discover --date YYYY-MM-DD` lists them instead.

### 2. Set up push

Install [ntfy](https://ntfy.sh) on your phone and subscribe to a topic name
only you know — topic names are the only access control, so use something
random like `odyssey-mtl-7f3a9c21`, not `odyssey`.

Then add it as a repo secret (**Settings → Secrets and variables → Actions**):

| Secret | Required | What |
|---|---|---|
| `NTFY_TOPIC` | yes | Your topic name. Never put this in `config.toml` — this repo is public. |
| `NTFY_SERVER` | no | Self-hosted ntfy. Defaults to `https://ntfy.sh`. |
| `WEBHOOK_URL` | no | Discord/Slack incoming webhook, if you want a second channel. |
| `CINEPLEX_API_KEY` | no | Only if the seat endpoint starts returning 401/403, or for `discover` — the showtimes feed is key-gated. |

Set repo **variable** `ALERT_ISSUE_NUMBER` to also comment on an issue.

### 3. Verify, then merge to master

```bash
python -m seatwatch dump        # does the parser see real seats?
python -m seatwatch check       # what matches right now?
NTFY_TOPIC=your-topic python -m seatwatch test-alert
```

Then **merge this branch to `master`**. GitHub only runs `schedule:`
workflows from the default branch — on a feature branch nothing fires.

## How the seat data actually works

Verified against the live API (theatre 9406, showtime 403870). **No API key
is needed** for either endpoint.

Seat state comes from two endpoints that are useless apart:

| Endpoint | Gives |
|---|---|
| `.../seat-availability` | flat `{seat_id: "Available"\|"Occupied"}`, plus `isSoldOut` / `isPostShowtime` |
| `.../seat-layout` | row **labels**, seat labels, seat types, grid columns |

They join on seat id. The catch that makes the join mandatory: an id like
`1_8_14` encodes a **physical** row number, and physical numbers run
*backwards* relative to the row letters — row A is physical 12, row K is
physical 1. Reading the id alone and calling row 5 "E" would silently watch
the wrong end of the cinema.

The layout also contains an unlabelled row with zero seats — that's the
aisle, and it's why physical row 7 never appears in availability. Rows
without a label are skipped.

Layout is fetched once per showtime and cached, since only availability
changes between polls.

Seat types come through explicitly as `Standard` / `Wheelchair` /
`Companion`, so `include_accessible = false` filters on the real type rather
than guessing from names.

If Cineplex changes the shape, `dump` prints both payloads next to what the
parser made of them, and the health warning below means you find out rather
than assuming the show is just full.

## Watching many showtimes

`[discovery]` watches every Odyssey showtime at the theatre over the next
`days` days, instead of you listing each one. It needs `CINEPLEX_API_KEY`,
because the showtimes feed is the one Cineplex endpoint that requires a key
— the open ticketing endpoints only answer questions about a showtime you
can already name. Without the key it prints why and falls back to the
`[[showtimes]]` blocks, rather than failing.

Polling every showtime on every pass does not scale — a week of slots at the
single-showtime cadence would be thousands of requests an hour. So each run
gets a `max_requests_per_run` budget and **spends it on the soonest shows
first**, because a cancellation for tonight matters more and there is less
time to catch it:

| Time until showtime | Poll frequency |
|---|---|
| < 12 h (imminent) | every pass — hardest |
| < 48 h | every 2nd pass |
| < 7 days | every 3rd pass |
| further / unknown | a single baseline check per run |

Pass 1 always polls everything, so every show gets at least one check per
cron fire; the remaining budget goes to the near ones. With the default
budget of 60 and this week's 28 slots, the soonest show is polled ~every
67 s (~48×/hour) while next Thursday's gets ~2×/run. As each show approaches
it climbs the tiers automatically — the scheduler recomputes proximity every
run. Lower `max_requests_per_run` to be gentler, raise it to poll harder.

## Criteria

```toml
[criteria]
min_row = "E"              # E and further back; A-D are too close for 70mm
max_row = ""               # optional back limit, e.g. "L"
max_centre_offset = 0.5    # 0.0 = dead centre, 1.0 = the aisle seat
include_accessible = false # leave wheelchair/companion seats alone
min_adjacent = 1           # 2 = only tell me about pairs
```

`max_centre_offset` is a fraction of the row's half-width, so it means the
same thing in a 14-seat row and a 24-seat row. `0.5` keeps the middle half;
drop to `0.3` if you're fussy. Alerts are ranked most-central first.

## Alert behaviour

Alerts go out at ntfy priority `max`, which pierces Do Not Disturb so an
early-morning cancellation actually wakes you. Drop `priority` under
`[alerts]` to `"high"` for a loud notification that still respects DND.

Silence is meant to mean "no seats", so it must not also mean "the endpoint
changed and nothing works". After `health_warn_after` consecutive failed
polls (default 3) you get a one-off *"seatwatch is broken, not quiet"* push,
then quiet for 24h so it can't nag. A good poll resets the streak.


Alerts fire on the *transition* from taken to free, not on every poll, so a
seat that's been free all afternoon won't page you. State lives on the
orphan `seatwatch-state` branch (one parentless commit, force-pushed, so it
never accumulates history). A seat that flickers is suppressed for
`cooldown_seconds` (default 6h).

## Commands

| Command | Does |
|---|---|
| `python -m seatwatch check` | One pass, prints matches, sends nothing |
| `python -m seatwatch watch` | Polls for `duration_seconds`, alerts on new seats |
| `python -m seatwatch dump` | Raw seat JSON + what the parser made of it |
| `python -m seatwatch add-showtime --url …` | Turn a pasted URL into a config block |
| `python -m seatwatch discover --date YYYY-MM-DD` | List showtimes (needs API key) |
| `python -m seatwatch test-alert` | Prove the push path works |

## Faster / more reliable triggering (optional)

Each run already polls continuously for ~50 minutes and the `concurrency`
guard chains them, so coverage is near-continuous off GitHub's own cron. If
you want a reliability backstop that doesn't depend on GitHub's (often late)
scheduler, point a free 1-minute external cron at the repo's dispatch
endpoint. The workflow already listens for it (`repository_dispatch` type
`seatwatch-ping`); a ping during an active run just keeps one run pending,
so if a run ever dies the next ping restarts it within a minute.

**1. Make a fine-grained token.** GitHub → Settings → Developer settings →
Fine-grained tokens → Generate. Scope it to **this repo only**, with
**Contents: read** and **Actions: read and write**. Copy the token.

**2. Point a cron service at the dispatch endpoint.** On
[cron-job.org](https://cron-job.org) (free) or similar, create a job that
runs **every minute**:

- **URL:** `https://api.github.com/repos/s1mar/Project1_Movieee/dispatches`
- **Method:** `POST`
- **Headers:**
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <your fine-grained token>`
  - `X-GitHub-Api-Version: 2022-11-28`
- **Body:** `{"event_type":"seatwatch-ping"}`

That's it — the token lives in the cron service, never in this repo. Send
`{"event_type":"seatwatch-ping","client_payload":{"mode":"test-alert"}}`
once to confirm the wiring fires a push.

To stop, delete or pause the cron job; the workflow keeps running on its own
schedule.

## Tests

```bash
python -m unittest discover -s seatwatch/tests -t . -v
```

103 tests: row ordering, centre-offset maths, payload-shape tolerance,
URL-shape extraction, showtime discovery, proximity-weighted scheduling,
alert de-duplication and cooldown, health-warning and empty-watchlist
notices, an end-to-end run of the real CLI against a fake Cineplex and a
fake ntfy, and regression tests over payloads captured from the live API
(including the inverted row numbering and the aisle row).

## Turning it off

Disable the **seatwatch** workflow under the repo's Actions tab, or delete
the `[[showtimes]]` blocks — with no `[[showtimes]]` block the job no-ops
immediately. Note that GitHub disables scheduled workflows automatically
after 60 days without repo activity.
