"""Alert delivery. ntfy is the primary channel; the rest are opt-in."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

TIMEOUT = 15


@dataclass
class Alert:
    title: str
    body: str
    url: str = ""          # primary tap target: the app deep link
    booking_url: str = ""  # secondary: straight into the browser booking flow
    priority: str = "high"


def resolve_deeplink(deeplink_url: str) -> str:
    """Turn the feed's apis.cineplex.com deeplink into the www.cineplex.com
    page it redirects to, so the app (which registers www links, not the api
    host) can catch it. Returns the input unchanged if it isn't a deeplink.
    """
    parsed = urllib.parse.urlparse(deeplink_url)
    if "/deeplink" not in parsed.path:
        return deeplink_url
    q = urllib.parse.parse_qs(parsed.query)
    def one(k, default=""):
        return (q.get(k) or [default])[0]
    slug = one("m", "the-odyssey")
    params = urllib.parse.urlencode({
        "deepLinkToSession": "true", "filmSlug": slug,
        "VistaSessionId": one("s"), "VistaHOCategoryCode": one("a"),
        "LocationId": one("l"), "IsSeriesShowtime": one("ss", "False"),
    })
    return f"https://www.cineplex.com/Movie/{slug}?{params}"


def _post(url: str, data: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        resp.read()


_PRIORITY_MAP = {"max": 5, "urgent": 5, "high": 4, "default": 3,
                 "low": 2, "min": 1}


def send_ntfy(alert: Alert, topic: str, server: str = "https://ntfy.sh") -> None:
    """Push to an ntfy topic via JSON publish.

    JSON is used rather than HTTP headers because the tap target can be an
    Android intent:// URL, whose ';' and '#' characters are not valid in a
    header value (ntfy rejects them with 400).
    """
    payload = {
        "topic": topic,
        "title": alert.title,
        "message": alert.body,
        "priority": _PRIORITY_MAP.get(alert.priority.lower(), 4),
        "tags": ["clapper", "tickets"],
    }
    actions = []
    if alert.url:
        # Tapping the notification opens the Cineplex app straight to this
        # showtime (falls back to the website if the app isn't installed).
        payload["click"] = alert.url
        actions.append({"action": "view", "label": "Open app",
                        "url": alert.url})
    if alert.booking_url:
        actions.append({"action": "view", "label": "Book in browser",
                        "url": alert.booking_url})
    if actions:
        payload["actions"] = actions[:3]
    _post(server.rstrip("/"), json.dumps(payload).encode("utf-8"),
          {"Content-Type": "application/json"})


def send_webhook(alert: Alert, webhook_url: str) -> None:
    """Discord and Slack both accept a JSON body with a `content`/`text` key."""
    text = f"**{alert.title}**\n{alert.body}"
    if alert.url:
        text += f"\n{alert.url}"
    payload = {"content": text, "text": text}
    _post(webhook_url, json.dumps(payload).encode("utf-8"),
          {"Content-Type": "application/json"})


def send_github_issue(alert: Alert, repo: str, token: str,
                      issue_number: str = "") -> None:
    """Comment on an existing issue, or open a new one."""
    body = alert.body + (f"\n\n{alert.url}" if alert.url else "")
    api = "https://api.github.com"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "seatwatch",
    }
    if issue_number:
        url = f"{api}/repos/{repo}/issues/{issue_number}/comments"
        payload = {"body": body}
    else:
        url = f"{api}/repos/{repo}/issues"
        payload = {"title": alert.title, "body": body}
    _post(url, json.dumps(payload).encode("utf-8"), headers)


def dispatch(alert: Alert, env: dict | None = None) -> list[str]:
    """Fire every channel that is configured. Returns the ones that worked.

    One dead channel must not stop the others - the whole point is that the
    message gets through.
    """
    env = os.environ if env is None else env
    delivered: list[str] = []
    failures: list[str] = []

    channels = []
    if env.get("NTFY_TOPIC"):
        channels.append(("ntfy", lambda: send_ntfy(
            alert, env["NTFY_TOPIC"],
            env.get("NTFY_SERVER") or "https://ntfy.sh")))
    if env.get("WEBHOOK_URL"):
        channels.append(("webhook", lambda: send_webhook(alert, env["WEBHOOK_URL"])))
    if env.get("GITHUB_TOKEN") and env.get("GITHUB_REPOSITORY"):
        channels.append(("github-issue", lambda: send_github_issue(
            alert, env["GITHUB_REPOSITORY"], env["GITHUB_TOKEN"],
            env.get("ALERT_ISSUE_NUMBER", ""))))

    for name, fn in channels:
        try:
            fn()
            delivered.append(name)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            failures.append(f"{name}: {exc}")

    if failures:
        print("  ! notification failures: " + "; ".join(failures))
    return delivered
