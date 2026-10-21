"""Rules turn config entries into bus subscribers: match an Event, build a
Notification, hand it to a Notifier."""
from __future__ import annotations

import logging

from hooks.events import Event, Notification, Priority
from hooks.notifiers.base import Notifier, NotifyError

log = logging.getLogger("hooks.rules")


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class Matcher:
    """All given conditions must hold; omitted conditions are ignored."""

    def __init__(self, m: dict | None):
        m = m or {}
        unknown = set(m) - {"source", "sender", "any_tags", "all_tags", "keywords"}
        if unknown:
            raise ValueError(f"unknown match keys: {sorted(unknown)}")
        self.source = m.get("source")
        self.senders = {s.lower() for s in as_list(m.get("sender"))}
        self.any_tags = set(as_list(m.get("any_tags")))
        self.all_tags = set(as_list(m.get("all_tags")))
        self.keywords = [k.lower() for k in as_list(m.get("keywords"))]

    def __call__(self, e: Event) -> bool:
        if self.source and e.source != self.source:
            return False
        if self.senders and e.sender_id.lower() not in self.senders:
            return False
        if self.any_tags and not (self.any_tags & e.tags):
            return False
        if not self.all_tags <= e.tags:
            return False
        if self.keywords:
            text = f"{e.title} {e.body}".lower()
            if not any(k in text for k in self.keywords):
                return False
        return True


class RuleSubscriber:
    """A bus subscriber built from one rule in the config."""

    def __init__(self, name: str, matcher: Matcher, notifier: Notifier | None,
                 priority: Priority = Priority.NORMAL, final: bool = True):
        self.name = name
        self.matcher = matcher
        self.notifier = notifier      # None = match silently (useful to mute things)
        self.priority = priority
        self.final = final            # True = later rules don't see this event

    def __call__(self, event: Event) -> bool:
        if not self.matcher(event):
            return False
        target = self.notifier.name if self.notifier else "nothing (muted)"
        log.info("rule '%s' matched %s event from %s -> %s",
                 self.name, event.source, event.sender_id or event.sender, target)
        if self.notifier:
            try:
                self.notifier.send(Notification.from_event(event, self.priority))
            except NotifyError as exc:
                log.error("rule '%s': delivery failed: %s", self.name, exc)
        return self.final
