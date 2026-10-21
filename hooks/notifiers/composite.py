"""Notifiers built from other notifiers. Because they implement the same
interface, they can be nested freely, e.g. a fallback whose first member is
a fan-out wrapped in a retry."""
from __future__ import annotations

import logging
import time

from hooks.events import Notification, Priority
from hooks.notifiers.base import Notifier, NotifyError, Resolver, register

log = logging.getLogger("hooks.notifiers")


class _Composite(Notifier):
    def __init__(self, name: str, targets: list[Notifier]):
        super().__init__(name)
        if not targets:
            raise ValueError(f"notifier '{name}': needs at least one target")
        self.targets = targets

    @classmethod
    def from_config(cls, name: str, cfg: dict, resolve: Resolver) -> Notifier:
        cfg = dict(cfg)
        targets = [resolve(t) for t in cfg.pop("targets", [])]
        if cfg:
            raise ValueError(f"notifier '{name}' ({cls.type_name}): unknown options {list(cfg)}")
        return cls(name, targets)


def _check_options(name: str, type_name: str, cfg: dict, required: set[str], optional: set[str] = frozenset()) -> None:
    missing = sorted(required - set(cfg))
    if missing:
        raise ValueError(f"notifier '{name}' ({type_name}): missing options {missing}")
    unknown = sorted(set(cfg) - required - optional)
    if unknown:
        raise ValueError(f"notifier '{name}' ({type_name}): unknown options {unknown}")


@register("fanout")
class FanOut(_Composite):
    """Send to every target. Succeeds if at least one target succeeded."""

    def send(self, n: Notification) -> None:
        errors = []
        for t in self.targets:
            try:
                t.send(n)
            except NotifyError as exc:
                log.warning("%s: target '%s' failed: %s", self.name, t.name, exc)
                errors.append(f"{t.name}: {exc}")
        if len(errors) == len(self.targets):
            raise NotifyError(f"all targets failed ({'; '.join(errors)})")


@register("fallback")
class Fallback(_Composite):
    """Try targets in order and stop at the first that succeeds."""

    def send(self, n: Notification) -> None:
        errors = []
        for t in self.targets:
            try:
                t.send(n)
                return
            except NotifyError as exc:
                log.warning("%s: '%s' failed, trying next: %s", self.name, t.name, exc)
                errors.append(f"{t.name}: {exc}")
        raise NotifyError(f"all targets failed ({'; '.join(errors)})")


@register("retry")
class Retry(Notifier):
    """Retry a single target with exponential backoff."""

    def __init__(self, name: str, target: Notifier, attempts: int = 3, delay: float = 5):
        super().__init__(name)
        self.target, self.attempts, self.delay = target, max(1, int(attempts)), float(delay)

    @classmethod
    def from_config(cls, name: str, cfg: dict, resolve: Resolver) -> Notifier:
        _check_options(name, cls.type_name, cfg, {"target"}, {"attempts", "delay"})
        cfg = dict(cfg)
        target = resolve(cfg.pop("target"))
        return cls(name, target, **cfg)

    def send(self, n: Notification) -> None:
        for i in range(self.attempts):
            try:
                self.target.send(n)
                return
            except NotifyError as exc:
                if i == self.attempts - 1:
                    raise
                wait = self.delay * 2 ** i
                log.warning("%s: attempt %d failed (%s); retrying in %.0fs", self.name, i + 1, exc, wait)
                time.sleep(wait)


@register("min_priority")
class MinPriority(Notifier):
    """Pass on only notifications at or above a priority, e.g. to send only
    urgent things to a loud channel inside a fan-out."""

    def __init__(self, name: str, target: Notifier, priority: Priority):
        super().__init__(name)
        self.target, self.priority = target, priority

    @classmethod
    def from_config(cls, name: str, cfg: dict, resolve: Resolver) -> Notifier:
        _check_options(name, cls.type_name, cfg, {"target", "priority"})
        return cls(name, resolve(cfg["target"]), Priority.parse(cfg["priority"]))

    def send(self, n: Notification) -> None:
        if n.priority >= self.priority:
            self.target.send(n)
