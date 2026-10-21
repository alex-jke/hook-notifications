"""Providers that talk HTTP directly: ntfy and Telegram. No extra
dependencies beyond `requests` (already pulled in by the zulip package)."""
from __future__ import annotations

import requests

from hooks.events import Notification, Priority
from hooks.notifiers.base import Notifier, NotifyError, register

TIMEOUT = 15


def _post(url: str, **kwargs) -> requests.Response:
    try:
        r = requests.post(url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise NotifyError(f"request failed: {exc}") from exc
    if r.status_code >= 400:
        raise NotifyError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r


@register("ntfy")
class NtfyNotifier(Notifier):
    """https://ntfy.sh — install the app, subscribe to the same topic.
    Uses JSON publishing, so titles with umlauts etc. work."""

    PRIORITY = {Priority.LOW: 2, Priority.NORMAL: 3, Priority.HIGH: 4, Priority.URGENT: 5}

    def __init__(self, name: str, *, topic: str, server: str = "https://ntfy.sh",
                 token: str | None = None):
        super().__init__(name)
        if not topic:
            raise ValueError(f"notifier '{name}': ntfy needs a topic")
        self.topic, self.server, self.token = topic, server.rstrip("/"), token

    def send(self, n: Notification) -> None:
        payload = {
            "topic": self.topic,
            "title": n.title,
            "message": n.body or " ",
            "priority": self.PRIORITY[n.priority],
            "tags": sorted(n.tags),
        }
        if n.url:
            payload["click"] = n.url
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        _post(self.server, json=payload, headers=headers)


@register("telegram")
class TelegramNotifier(Notifier):
    """Create a bot with @BotFather, send it any message, then read your
    chat id from https://api.telegram.org/bot<TOKEN>/getUpdates."""

    def __init__(self, name: str, *, bot_token: str, chat_id: str | int):
        super().__init__(name)
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id

    def send(self, n: Notification) -> None:
        text = f"{'🚨 ' if n.priority >= Priority.URGENT else ''}{n.title}\n\n{n.body}"
        if n.url:
            text += f"\n\n{n.url}"
        _post(self.url, json={
            "chat_id": self.chat_id,
            "text": text[:4096],
            "disable_notification": n.priority <= Priority.LOW,
            "link_preview_options": {"is_disabled": True},
        })
