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

## Closing the gaps (optional)

Runs are chained by `concurrency`, but GitHub's scheduler can go silent for
over an hour, leaving a gap where nothing is watching. Two ways to close it,
both needing the same fine-grained token — pick one.

**Make the token first (both options use it).** GitHub → Settings →
Developer settings → Fine-grained tokens → Generate. Scope to **this repo
only**, **Contents: read and write** + **Actions: read and write**. (The
repository-dispatch endpoint needs Contents *write*, not just read.) Copy it.

### Option A — self-chaining (one secret, no external service) ← simplest

Add the token as a repo secret named `DISPATCH_TOKEN` (Settings → Secrets
and variables → Actions). That's the whole setup. At the end of every run
the workflow re-triggers itself, so the next run starts in seconds instead
of waiting on GitHub's cron. The `*/5` cron stays as a backstop for the rare
case a run dies before it can re-trigger.

### Option B — external pinger (independent of GitHub entirely)

Keep the token out of the repo and drive it from a free 1-minute cron
service ([cron-job.org](https://cron-job.org), UptimeRobot, ...). It fires
even if a run has crashed. Create a job running **every minute**:

- **URL:** `https://api.github.com/repos/s1mar/Project1_Movieee/dispatches`
- **Method:** `POST`
- **Headers:** `Accept: application/vnd.github+json`,
  `Authorization: Bearer <token>`, `X-GitHub-Api-Version: 2022-11-28`
- **Body:** `{"event_type":"seatwatch-ping"}`

Either way, once reliable triggering is in place the run duration can be cut
right down (`duration_seconds`), so it stops being a near-permanent job.
Send `{"event_type":"seatwatch-ping","client_payload":{"mode":"test-alert"}}`
(Option B) once to confirm a push arrives.

To stop, delete or pause the cron job; the workflow keeps running on its own
schedule.

## Control it from your phone (optional)

ntfy is bidirectional — you can type into a topic, not just receive from it.
Point the watcher at a **control topic** and command it from the ntfy app:

1. Pick a second random topic (e.g. `odyssey-ctl-9f3a`), subscribe to it in
   the app, and add it as a repo secret `CONTROL_TOPIC`.
2. Type a command into that topic (the compose box at the bottom):
   - **`pause`** (or `stop`) — the watcher stops watching *and* stops
     self-chaining. Only the 5-minute cron keeps ticking, watching for a
     resume, so it costs almost nothing while paused.
   - **`resume`** (or `start`) — watching restarts and the fast chain
     resumes on the next run.
   - **`status`** — pushes back whether it's running or paused and what it's
     watching.

No token or credential goes into the messages — it's just you messaging a
private topic that the watcher reads at the top of each run. The watcher's
own alerts carry a title, so they're never mistaken for commands.

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
