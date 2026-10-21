"""Zulip source: long-polls Zulip's real-time events API with your own
account's API key and turns each incoming message into an Event."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from hooks.events import Event

log = logging.getLogger("hooks.zulip")


class ZulipSource:
    """Config: site + email + api_key (normally ${ZULIP_...} from .env),
    or alternatively zuliprc: path to a downloaded zuliprc file."""

    name = "zulip"
    OPTIONS = {"site", "email", "api_key", "zuliprc", "max_body_chars"}
    # Zulip sends a heartbeat at least every ~minute, so this much silence
    # means the connection is dead even if no exception was raised.
    MAX_SILENCE = 10 * 60

    def __init__(self, cfg: dict):
        unknown = set(cfg) - self.OPTIONS
        if unknown:
            raise ValueError(f"source zulip: unknown options {sorted(unknown)}")
        if cfg.get("zuliprc"):
            self.client_args = {"config_file": str(Path(cfg["zuliprc"]).expanduser())}
        elif all(cfg.get(k) for k in ("site", "email", "api_key")):
            self.client_args = {k: cfg[k] for k in ("site", "email", "api_key")}
        else:
            raise ValueError("source zulip: set site, email and api_key (or zuliprc)")
        self.max_body = int(cfg.get("max_body_chars", 600))
        self.last_ok = 0.0

    def healthy(self) -> bool:
        return time.time() - self.last_ok < self.MAX_SILENCE

    def run(self, emit: Callable[[Event], None]) -> None:
        import zulip  # imported here so other sources work without the package

        client = zulip.Client(client="hooks", **self.client_args)
        me = client.get_profile()
        if me.get("result") != "success":
            raise RuntimeError(f"Zulip login failed: {me.get('msg')}")
        my_id, site = me["user_id"], client.base_url.rstrip("/").removesuffix("/api/v1").removesuffix("/api")
        log.info("connected to %s as %s", site, me.get("email"))

        backoff = 5
        while True:
            # (Re)register an event queue. Queues expire after ~10 min of
            # inactivity on the client side, so this also handles resume.
            reg = client.register(event_types=["message"], apply_markdown=False)
            if reg.get("result") != "success":
                log.warning("register failed (%s); retrying in %ss", reg.get("msg"), backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 300)
                continue
            backoff = 5
            queue_id, last_id = reg["queue_id"], reg["last_event_id"]
            log.info("event queue registered")

            while True:
                try:
                    res = client.get_events(queue_id=queue_id, last_event_id=last_id)
                except Exception as exc:  # network hiccup, laptop suspend, ...
                    log.warning("get_events error: %s; retrying in 10s", exc)
                    time.sleep(10)
                    continue
                if res.get("result") != "success":
                    if res.get("code") == "BAD_EVENT_QUEUE_ID":
                        log.info("event queue expired; re-registering")
                        break
                    log.warning("get_events failed: %s; retrying in 10s", res.get("msg"))
                    time.sleep(10)
                    continue
                self.last_ok = time.time()
                for ev in res.get("events", []):
                    last_id = max(last_id, ev["id"])
                    if ev.get("type") != "message":
                        continue
                    msg = ev["message"]
                    if msg.get("sender_id") == my_id:
                        continue
                    try:
                        emit(self._to_event(msg, ev.get("flags", []), site))
                    except Exception:
                        log.exception("handler failed for message %s", msg.get("id"))

    def _to_event(self, msg: dict, flags: list[str], site: str) -> Event:
        tags: set[str] = set()
        if msg["type"] == "private":
            tags.add("dm")
            where = "DM"
        else:
            channel, topic = msg.get("display_recipient", "?"), msg.get("subject", "")
            tags.update({f"channel:{channel}", f"topic:{topic}"})
            where = f"#{channel} > {topic}"
        if "mentioned" in flags:
            tags.add("mention")
        if "wildcard_mentioned" in flags or "stream_wildcard_mentioned" in flags \
                or "topic_wildcard_mentioned" in flags:
            tags.add("wildcard_mention")
        body = msg.get("content", "")
        if len(body) > self.max_body:
            body = body[: self.max_body] + " …"
        return Event(
            source="zulip",
            title=f"{msg.get('sender_full_name', '?')} ({where})",
            body=body,
            sender=msg.get("sender_full_name", ""),
            sender_id=msg.get("sender_email", ""),
            url=f"{site}/#narrow/near/{msg['id']}",
            tags=frozenset(tags),
        )
