from __future__ import annotations

import pytest

from hooks.app import build_notifiers
from hooks.events import Notification, Priority
from hooks.notifiers import Notifier, NotifyError
from hooks.notifiers.composite import Fallback, FanOut, MinPriority, Retry

N = Notification("title", "body", priority=Priority.HIGH)


class Rec(Notifier):
    def __init__(self, name, fail=0):
        super().__init__(name)
        self.fail, self.got = fail, []

    def send(self, n):
        if self.fail:
            self.fail -= 1
            raise NotifyError("boom")
        self.got.append(n)


def test_fanout_succeeds_if_any_target_succeeds():
    a, b = Rec("a", fail=1), Rec("b")
    FanOut("f", [a, b]).send(N)
    assert not a.got and b.got


def test_fanout_fails_if_all_fail():
    with pytest.raises(NotifyError):
        FanOut("f", [Rec("x", 1), Rec("y", 1)]).send(N)


def test_fallback_stops_at_first_success():
    a, b, c = Rec("a", fail=1), Rec("b"), Rec("c")
    Fallback("fb", [a, b, c]).send(N)
    assert b.got and not c.got


def test_retry():
    r = Rec("r", fail=2)
    Retry("x", r, attempts=3, delay=0).send(N)
    assert r.got
    with pytest.raises(NotifyError):
        Retry("x", Rec("r", fail=5), attempts=2, delay=0).send(N)


def test_min_priority():
    r = Rec("r")
    MinPriority("m", r, Priority.URGENT).send(N)
    assert not r.got


def test_config_errors_are_caught_early():
    with pytest.raises(ValueError, match="cycle"):
        build_notifiers({"x": {"type": "fanout", "targets": ["y"]}, "y": {"type": "fanout", "targets": ["x"]}})
    with pytest.raises(ValueError, match="unknown options"):
        build_notifiers({"x": {"type": "ntfy", "topic": "t", "tpoic": 1}})
    with pytest.raises(ValueError, match="unknown type"):
        build_notifiers({"x": {"type": "carrier-pigeon"}})
    with pytest.raises(ValueError, match="unknown notifier"):
        build_notifiers({"x": {"type": "retry", "target": "nope"}})
    log = {"l": {"type": "log"}}
    with pytest.raises(ValueError, match=r"unknown options \['attemps'\]"):
        build_notifiers({**log, "x": {"type": "retry", "target": "l", "attemps": 3}})
    with pytest.raises(ValueError, match=r"missing options \['target'\]"):
        build_notifiers({**log, "x": {"type": "retry", "targt": "l"}})
    with pytest.raises(ValueError, match="unknown priority 'urgnet'"):
        build_notifiers({**log, "x": {"type": "min_priority", "target": "l", "priority": "urgnet"}})
    with pytest.raises(ValueError, match="unknown options"):
        build_notifiers({**log, "x": {"type": "min_priority", "target": "l", "priority": "high", "x": 1}})


def test_ntfy_payload(http):
    (n,) = build_notifiers({"p": {"type": "ntfy", "topic": "abc", "token": "tk"}}).values()
    n.send(Notification("Grüezi", "", url="https://x", priority=Priority.URGENT))
    url, body = http.calls[0]
    assert url == "https://ntfy.sh"
    assert body["topic"] == "abc" and body["priority"] == 5 and body["click"] == "https://x"
    assert body["title"] == "Grüezi"


def test_http_error_raises_notify_error(http):
    http.failing.add("ntfy.sh")
    (n,) = build_notifiers({"p": {"type": "ntfy", "topic": "abc"}}).values()
    with pytest.raises(NotifyError, match="502"):
        n.send(N)


def test_telegram_payload(http):
    (n,) = build_notifiers({"t": {"type": "telegram", "bot_token": "TKN", "chat_id": 1}}).values()
    n.send(Notification("T", "B", priority=Priority.LOW))
    url, body = http.calls[0]
    assert url == "https://api.telegram.org/botTKN/sendMessage"
    assert body["disable_notification"] is True
