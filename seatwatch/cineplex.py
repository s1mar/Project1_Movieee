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
from dataclasses import dataclass

DEFAULT_BASE = "https://apis.cineplex.com"
SEAT_AVAILABILITY = "/prod/ticketing/api/v1/theatre/{theatre_id}/showtime/{showtime_id}/seat-availability"
SEAT_LAYOUT = "/prod/ticketing/api/v1/theatre/{theatre_id}/showtime/{showtime_id}/seat-layout"
SHOWTIMES = "/prod/cpx/theatrical/api/v1/showtimes"

# Identify the watcher honestly rather than impersonating a browser, and
# leave a contact path in the string.
USER_AGENT = ("seatwatch/1.0 (personal seat-availability watcher; "
              "+https://github.com/s1mar/Project1_Movieee)")


class CineplexError(RuntimeError):
    pass


class NotFound(CineplexError):
    """Showtime is gone - sold out and delisted, or already screened."""


@dataclass
class Client:
    base_url: str = DEFAULT_BASE
    api_key: str = ""
    timeout: int = 20
    max_retries: int = 3

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
                    return json.loads(resp.read().decode("utf-8"))
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

    def seat_map(self, theatre_id: str, showtime_id: str,
                 availability_path: str = SEAT_AVAILABILITY,
                 layout_path: str = SEAT_LAYOUT) -> dict:
        """Seat data for one showtime, preferring the availability feed."""
        ids = {"theatre_id": theatre_id, "showtime_id": showtime_id}
        try:
            return self.get(availability_path.format(**ids))
        except NotFound:
            raise
        except CineplexError:
            return self.get(layout_path.format(**ids))

    def showtimes(self, location_id: str, date: str,
                  path: str = SHOWTIMES, language: str = "en") -> dict:
        """Showtimes for a theatre on a date. Needs an API key."""
        return self.get(path, {"language": language,
                               "locationId": location_id, "date": date})
