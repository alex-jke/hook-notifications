"""Shared fakes. Tests never touch the network or a real Zulip server."""
from __future__ import annotations

import sys
import types

import pytest
import requests


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok"):
        self.status_code, self.text = status_code, text


class HttpRecorder:
    """Replaces requests.post. Records calls; hosts in `failing` get HTTP 502."""

    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []
        self.failing: set[str] = set()

    def __call__(self, url, timeout=None, json=None, headers=None, data=None, **kw):
        self.calls.append((url, json))
        if any(h in url for h in self.failing):
            return FakeResponse(502, "bad gateway")
        return FakeResponse()

    def to(self, host: str) -> list[dict | None]:
        return [body for url, body in self.calls if host in url]


@pytest.fixture
def http(monkeypatch) -> HttpRecorder:
    rec = HttpRecorder()
    monkeypatch.setattr(requests, "post", rec)
    return rec


class StopSource(BaseException):
    """Ends a source's run loop in tests. BaseException on purpose: sources
    deliberately catch Exception and retry forever."""


class FakeZulip:
    """Minimal stand-in for zulip.Client. `batches` are the successive
    get_events responses; when exhausted, StopSource ends the run."""

    def __init__(self, batches: list[dict], my_id: int = 1):
        self.batches, self.my_id, self.registers = list(batches), my_id, []
        fake = self

        class Client:
            def __init__(self, **kwargs):
                fake.client_kwargs = kwargs
                self.base_url = "https://uni.zulipchat.com/api/v1"

            def get_profile(self):
                return {"result": "success", "user_id": fake.my_id, "email": "me@uni.example"}

            def register(self, **kw):
                fake.registers.append(kw)
                return {"result": "success", "queue_id": f"q{len(fake.registers)}", "last_event_id": -1}

            def get_events(self, queue_id, last_event_id):
                if not fake.batches:
                    raise StopSource
                return fake.batches.pop(0)

        self.module = types.SimpleNamespace(Client=Client)


def zulip_msg(id, sender, content, *, type_="private", flags=(), stream=None, topic=None,
              sender_id=7, name="Someone"):
    m = {"id": id, "sender_email": sender, "sender_full_name": name, "sender_id": sender_id,
         "type": type_, "content": content}
    if stream:
        m.update(display_recipient=stream, subject=topic)
    return {"type": "message", "id": id, "message": m, "flags": list(flags)}


@pytest.fixture
def fake_zulip(monkeypatch):
    def install(batches, my_id=1) -> FakeZulip:
        fz = FakeZulip(batches, my_id)
        monkeypatch.setitem(sys.modules, "zulip", fz.module)
        return fz
    return install
