"""Minimal Cineplex ticketing client.

Standard library only, so the GitHub Actions job needs no `pip install`
step - that keeps each run down to a few seconds of billable time.

The endpoints below are undocumented and were identified from public
community projects, not from Cineplex documentation. They are treated as
templates in config so a path change can be fixed without touching code.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

DEFAULT_BASE = "https://apis.cineplex.com"
SEAT_AVAILABILITY = "/prod/ticketing/api/v1/theatre/{theatre_id}/showtime/{showtime_id}/seat-availability"
SEAT_LAYOUT = "/prod/ticketing/api/v1/theatre/{theatre_id}/showtime/{showtime_id}/seat-layout"
# Confirmed against the live feed: the showtimes list is a query, not a path.
# Gated behind the API key. Returns a list of theatre blocks.
SHOWTIMES = "/prod/cpx/theatrical/api/v1/showtimes"

# Identify the watcher honestly rather than impersonating a browser, and
# leave a contact path in the string.
USER_AGENT = ("seatwatch/1.0 (personal seat-availability watcher; "
              "+https://github.com/s1mar/Project1_Movieee)")


def _read_body(resp) -> str:
    """Decode a response body, transparently gunzipping if the server
    gzipped it despite us not asking (observed on the showtimes feed)."""
    raw = resp.read()
    if resp.headers.get("Content-Encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


class CineplexError(RuntimeError):
    pass


class NotFound(CineplexError):
    """Showtime is gone - sold out and delisted, or already screened."""


class PostShowtime(CineplexError):
    """The screening has already started or finished."""


@dataclass
class Client:
    base_url: str = DEFAULT_BASE
    api_key: str = ""
    timeout: int = 20
    max_retries: int = 3
    # Seat layout is fixed for a showtime; only availability moves. Cached so
    # a 45-second poll loop doesn't re-download it every pass.
    _layouts: dict = field(default_factory=dict, repr=False)

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.api_key:
            headers["Ocp-Apim-Subscription-Key"] = self.api_key
        return headers

    def get(self, path: str, params: dict | None = None) -> dict:
        url = self.base_url.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            if attempt:
                # Back off hard; a busy ticketing API deserves the room.
                time.sleep(2 ** attempt)
            req = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(_read_body(resp))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:200]
                if exc.code == 404:
                    raise NotFound(f"404 for {url}: {body}") from exc
                if exc.code in (401, 403):
                    raise CineplexError(
                        f"{exc.code} for {url}. The endpoint now needs an API "
                        f"key - set CINEPLEX_API_KEY. Body: {body}") from exc
                if exc.code == 429 or exc.code >= 500:
                    last_error = exc
                    continue
                raise CineplexError(f"{exc.code} for {url}: {body}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                continue
        raise CineplexError(f"giving up on {url} after "
                            f"{self.max_retries} tries: {last_error}")

    def seat_layout(self, theatre_id: str, showtime_id: str,
                    layout_path: str = SEAT_LAYOUT) -> dict:
        """Row labels, seat labels, types and grid positions. Cached."""
        key = (theatre_id, showtime_id)
        if key not in self._layouts:
            self._layouts[key] = self.get(layout_path.format(
                theatre_id=theatre_id, showtime_id=showtime_id))
        return self._layouts[key]

    def seat_map(self, theatre_id: str, showtime_id: str,
                 availability_path: str = SEAT_AVAILABILITY,
                 layout_path: str = SEAT_LAYOUT) -> tuple[dict, dict]:
        """(layout, availability) for one showtime.

        Availability alone is a flat id->status map with no row letters, so
        both halves are needed to answer "is anything free in row E".
        """
        availability = self.get(availability_path.format(
            theatre_id=theatre_id, showtime_id=showtime_id))
        if availability.get("isPostShowtime"):
            raise PostShowtime(f"showtime {showtime_id} has already screened")
        layout = self.seat_layout(theatre_id, showtime_id, layout_path)
        return layout, availability

    def showtimes(self, location_id: str, date: str,
                  path: str = SHOWTIMES, language: str = "en"):
        """Showtimes for a theatre on a date (YYYY-MM-DD). Needs an API key.

        Returns the raw payload, a list of theatre blocks.
        """
        return self.get(path, {"locationId": location_id, "date": date,
                               "language": language})
