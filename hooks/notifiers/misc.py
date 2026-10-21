"""Catch-all and debugging providers."""
from __future__ import annotations

import logging

from hooks.events import Notification, Priority
from hooks.notifiers.base import Notifier, NotifyError, register

log = logging.getLogger("hooks.notifiers")


@register("log")
class LogNotifier(Notifier):
    """Writes the notification to the log. Handy for testing rules and as
    the stand-in for every notifier in --dry-run mode."""

    def __init__(self, name: str, *, label: str | None = None):
        super().__init__(name)
        self.label = label or name

    def send(self, n: Notification) -> None:
        log.info("[%s] %s | %s | %s", self.label, n.priority.name, n.title,
                 n.body.replace("\n", " ")[:160])


@register("apprise")
class AppriseNotifier(Notifier):
    """Any of the ~100 services Apprise supports (Signal, Matrix, Pushover,
    Discord, email, ...). Requires `pip install apprise`.
    urls: one Apprise URL or a list, see https://github.com/caronc/apprise/wiki"""

    TYPE = {Priority.LOW: "info", Priority.NORMAL: "info",
            Priority.HIGH: "warning", Priority.URGENT: "failure"}

    def __init__(self, name: str, *, urls):
        super().__init__(name)
        try:
            import apprise
        except ImportError as exc:
            raise ValueError(f"notifier '{name}': `pip install apprise` to use type apprise") from exc
        self._apprise = apprise.Apprise()
        for url in urls if isinstance(urls, list) else [urls]:
            if not self._apprise.add(url):
                raise ValueError(f"notifier '{name}': invalid Apprise URL")

    def send(self, n: Notification) -> None:
        body = n.body + (f"\n\n{n.url}" if n.url else "")
        if not self._apprise.notify(title=n.title, body=body, notify_type=self.TYPE[n.priority]):
            raise NotifyError("apprise reported failure")
