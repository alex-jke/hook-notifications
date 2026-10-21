"""Dead-man's switch. If hooks crashes, the laptop dies or Zulip stops
answering, you'd otherwise never find out, and miss exactly the messages
this project exists for.

Every `interval` seconds this pings an external URL, but only while all
sources report healthy. Point it at a free check on https://healthchecks.io
(or any compatible service); it alerts you when pings stop. When a source is
unhealthy, it pings `<url>/fail`, so you're alerted immediately.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

log = logging.getLogger("hooks.health")


class Heartbeat:
    def __init__(self, url: str, sources: list, interval: float = 300, grace: float = 90):
        self.url, self.sources = url.rstrip("/"), sources
        self.interval, self.grace = float(interval), float(grace)

    @classmethod
    def from_config(cls, cfg: dict | None, sources: list) -> Heartbeat | None:
        if not cfg:
            return None
        cfg = dict(cfg)
        url = cfg.pop("ping_url", None)
        if not url:
            raise ValueError("health: ping_url is required")
        unknown = set(cfg) - {"interval"}
        if unknown:
            raise ValueError(f"health: unknown options {sorted(unknown)}")
        return cls(url, sources, interval=cfg.get("interval", 300))

    def status(self) -> tuple[bool, str]:
        bad = [s.name for s in self.sources if not getattr(s, "healthy", lambda: True)()]
        return (not bad, f"unhealthy: {', '.join(bad)}" if bad else "ok")

    def ping_once(self) -> None:
        ok, msg = self.status()
        try:
            requests.post(self.url if ok else f"{self.url}/fail", data=msg, timeout=10)
        except requests.RequestException as exc:
            log.warning("heartbeat ping failed: %s", exc)
        if not ok:
            log.warning("heartbeat: %s", msg)

    def start(self) -> None:
        def loop():
            time.sleep(self.grace)  # let sources connect first
            while True:
                self.ping_once()
                time.sleep(self.interval)
        threading.Thread(target=loop, name="heartbeat", daemon=True).start()
