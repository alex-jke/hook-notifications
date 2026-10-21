"""A small publish/subscribe event bus.

Sources publish Events; subscribers are called in subscription order on a
dedicated worker thread, so a slow notifier never blocks a source. A
subscriber returns True to consume the event and stop propagation.
"""
from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Protocol

from hooks.events import Event

log = logging.getLogger("hooks.bus")


class Subscriber(Protocol):
    name: str

    def __call__(self, event: Event) -> bool:
        """Handle the event. Return True to stop later subscribers seeing it."""
        ...


class EventBus:
    _STOP = object()

    def __init__(self) -> None:
        self._subs: list[Subscriber] = []
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None

    # --- subscription -------------------------------------------------
    def subscribe(self, sub: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subs.append(sub)

        def unsubscribe() -> None:
            with self._lock:
                if sub in self._subs:
                    self._subs.remove(sub)
        return unsubscribe

    # --- publishing ---------------------------------------------------
    def publish(self, event: Event) -> None:
        """Thread-safe; returns immediately."""
        self._queue.put(event)

    def dispatch(self, event: Event) -> None:
        """Deliver one event synchronously (used by the worker and in tests)."""
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            try:
                if sub(event):
                    return
            except Exception:
                log.exception("subscriber '%s' failed", getattr(sub, "name", sub))
        log.debug("event not consumed: %s | %s", event.source, event.title)

    # --- lifecycle ----------------------------------------------------
    def start(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(target=self._run, name="bus", daemon=True)
            self._worker.start()

    def stop(self, timeout: float = 10) -> None:
        if self._worker is not None:
            self._queue.put(self._STOP)
            self._worker.join(timeout)
            self._worker = None

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                return
            self.dispatch(item)
