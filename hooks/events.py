"""The data that flows through the system.

Event         what a source observed (a Zulip message, later an email, ...)
Notification  what a notifier delivers (derived from an Event by a rule)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Priority(IntEnum):
    LOW = 1      # silent / no sound where the provider supports it
    NORMAL = 2
    HIGH = 3
    URGENT = 4   # may bypass Do Not Disturb where the provider supports it

    @classmethod
    def parse(cls, value) -> Priority:
        if isinstance(value, cls):
            return value
        try:
            return cls[str(value).strip().upper()]
        except KeyError:
            raise ValueError(f"unknown priority '{value}' (use: {', '.join(p.name.lower() for p in cls)})") from None


@dataclass(frozen=True)
class Event:
    source: str                 # e.g. "zulip"
    title: str                  # short headline
    body: str                   # message text
    sender: str = ""            # display name
    sender_id: str = ""         # stable id, e.g. an email address
    url: str = ""               # link back to the original
    tags: frozenset[str] = field(default_factory=frozenset)  # e.g. {"dm", "mention", "channel:lab"}


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    url: str = ""
    priority: Priority = Priority.NORMAL
    tags: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_event(cls, e: Event, priority: Priority = Priority.NORMAL) -> Notification:
        return cls(title=e.title, body=e.body, url=e.url, priority=priority,
                   tags=frozenset({e.source}))
