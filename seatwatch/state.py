"""Remembers what was already available so we alert on changes, not on facts.

A seat that has been free for three hours is not news. Alerts fire when a
seat crosses from unavailable to available, and a per-seat cooldown stops a
flickering seat from paging you repeatedly.
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field

SCHEMA_VERSION = 1


@dataclass
class State:
    path: pathlib.Path
    data: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "State":
        p = pathlib.Path(path)
        if p.exists():
            try:
                data = json.loads(p.read_text())
                if data.get("version") == SCHEMA_VERSION:
                    return cls(path=p, data=data)
            except (json.JSONDecodeError, OSError):
                pass  # Corrupt or stale state is not worth failing a run over.
        return cls(path=p, data={"version": SCHEMA_VERSION, "showtimes": {}})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))

    def _entry(self, key: str) -> dict:
        return self.data.setdefault("showtimes", {}).setdefault(
            key, {"available": [], "alerted": {}, "first_seen": None})

    def is_first_run(self, key: str) -> bool:
        return self._entry(key).get("first_seen") is None

    def newly_available(self, key: str, labels: list[str],
                        cooldown_seconds: int = 6 * 3600,
                        now: float | None = None) -> list[str]:
        """Labels worth alerting about: newly free and not recently alerted."""
        now = time.time() if now is None else now
        entry = self._entry(key)
        previous = set(entry.get("available", []))
        alerted = entry.get("alerted", {})

        fresh = []
        for label in labels:
            if label in previous:
                continue  # Already free last time we looked.
            last = alerted.get(label)
            if last is not None and now - last < cooldown_seconds:
                continue  # Paged about this one recently; stay quiet.
            fresh.append(label)
        return fresh

    def record(self, key: str, labels: list[str], alerted_labels: list[str],
               now: float | None = None) -> None:
        now = time.time() if now is None else now
        entry = self._entry(key)
        entry["available"] = sorted(set(labels))
        entry["first_seen"] = entry.get("first_seen") or now
        entry["last_checked"] = now
        for label in alerted_labels:
            entry.setdefault("alerted", {})[label] = now
        # Forget cooldowns for seats that have been sold again and are long
        # gone, so the file does not grow without bound.
        cutoff = now - 30 * 24 * 3600
        entry["alerted"] = {k: v for k, v in entry.get("alerted", {}).items()
                            if v > cutoff}

    def note_health(self, key: str, ok: bool, warn_after: int = 3,
                    quiet_seconds: int = 24 * 3600,
                    now: float | None = None) -> bool:
        """Track consecutive bad polls. True when it's time to warn.

        Without this, a broken endpoint is indistinguishable from a sold-out
        show: both are silence. Silence should mean "no seats", not "no idea".
        """
        now = time.time() if now is None else now
        entry = self._entry(key)
        if ok:
            entry["failures"] = 0
            return False
        entry["failures"] = entry.get("failures", 0) + 1
        if entry["failures"] < warn_after:
            return False
        last = entry.get("last_health_warning")
        if last is not None and now - last < quiet_seconds:
            return False
        entry["last_health_warning"] = now
        return True

    def prune(self, live_keys: set[str]) -> None:
        """Drop showtimes that no longer exist (screened or delisted)."""
        shows = self.data.get("showtimes", {})
        for key in list(shows):
            if key not in live_keys:
                del shows[key]
