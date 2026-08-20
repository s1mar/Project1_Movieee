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
    url: str = ""
    priority: str = "high"


def _post(url: str, data: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        resp.read()


def send_ntfy(alert: Alert, topic: str, server: str = "https://ntfy.sh") -> None:
    """Push to an ntfy topic. Topic name is the only secret, so keep it odd."""
    headers = {
        "Title": alert.title,
        "Priority": alert.priority,
        "Tags": "clapper,tickets",
        "Content-Type": "text/plain; charset=utf-8",
    }
    if alert.url:
        # Tapping the notification opens the seat picker directly.
        headers["Click"] = alert.url
        headers["Actions"] = f"view, Book now, {alert.url}"
    _post(f"{server.rstrip('/')}/{topic}", alert.body.encode("utf-8"), headers)


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
