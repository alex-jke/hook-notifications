"""End to end: fake Zulip -> source -> bus -> rules -> notifiers -> fake HTTP."""
from __future__ import annotations

import pytest
from conftest import StopSource, zulip_msg

from hooks.app import build_bus, build_notifiers, build_sources

SUP = "Prof.Mueller@uni.example"

CFG = {
    "sources": {"zulip": {"site": "https://uni.zulipchat.com", "email": "me@uni.example", "api_key": "k"}},
    "notifiers": {
        "ntfy_phone": {"type": "ntfy", "topic": "t0p1c"},
        "phone": {"type": "retry", "target": "ntfy_phone", "attempts": 1},
        "telegram": {"type": "telegram", "bot_token": "TKN", "chat_id": 42},
        "reliable": {"type": "fallback", "targets": ["telegram", "ntfy_phone"]},
    },
    "rules": [
        {"name": "sup-direct", "match": {"source": "zulip", "sender": SUP, "any_tags": ["dm", "mention"]},
         "priority": "urgent", "notify": ["phone"]},
        {"name": "sup-any", "match": {"source": "zulip", "sender": SUP}, "priority": "high", "notify": ["phone"]},
        {"name": "other-dm", "match": {"source": "zulip", "any_tags": ["dm"]}, "priority": "low",
         "notify": ["reliable"]},
    ],
}


def run_source(cfg, bus):
    (src,) = build_sources(cfg)
    with pytest.raises(StopSource):
        src.run(bus.dispatch)
    return src


def test_routing_priorities_and_fallback(http, fake_zulip):
    fz = fake_zulip([
        {"result": "success", "events": [
            zulip_msg(1, SUP, "Can you send me the plots today?", name="Prof. Müller"),
            zulip_msg(2, SUP, "@**Me** please check", type_="stream", flags=["mentioned"],
                      stream="lab", topic="paper", name="Prof. Müller"),
            zulip_msg(3, SUP, "General remark", type_="stream", stream="lab", topic="misc", name="Prof. Müller"),
            zulip_msg(4, "other@uni.example", "lunch?", type_="stream", stream="random", topic="food"),
            zulip_msg(5, "me@uni.example", "my own message", sender_id=1),
            {"type": "heartbeat", "id": 6},
        ]},
        {"result": "error", "code": "BAD_EVENT_QUEUE_ID", "msg": "expired"},
        {"result": "success", "events": [zulip_msg(7, "other@uni.example", "x" * 2000)]},
    ])
    http.failing.add("api.telegram.org")
    bus = build_bus(CFG, build_notifiers(CFG["notifiers"]))
    src = run_source(CFG, bus)

    assert fz.client_kwargs["site"] == "https://uni.zulipchat.com"
    assert len(fz.registers) == 2, "re-registers after queue expiry"
    assert fz.registers[0]["apply_markdown"] is False
    assert src.healthy()

    ntfy = http.to("ntfy.sh")
    assert [n["priority"] for n in ntfy] == [5, 5, 4, 2]
    assert ntfy[0]["title"] == "Prof. Müller (DM)"
    assert ntfy[0]["click"] == "https://uni.zulipchat.com/#narrow/near/1"
    assert "lab > paper" in ntfy[1]["title"]
    assert ntfy[3]["message"].endswith(" …"), "long bodies are truncated"
    assert len(http.to("api.telegram.org")) == 1, "telegram tried first, failed, fell back to ntfy"


def test_dry_run_sends_nothing(http, fake_zulip):
    fake_zulip([{"result": "success", "events": [zulip_msg(1, SUP, "hi")]}])
    bus = build_bus(CFG, build_notifiers(CFG["notifiers"]), dry_run=True)
    run_source(CFG, bus)
    assert http.calls == []


def test_non_final_rule_lets_later_rules_see_event(http, fake_zulip):
    cfg = {**CFG, "rules": [
        {"name": "log-all", "match": {}, "notify": [], "final": False},
        CFG["rules"][0],
    ]}
    fake_zulip([{"result": "success", "events": [zulip_msg(1, SUP, "hi")]}])
    run_source(cfg, build_bus(cfg, build_notifiers(cfg["notifiers"])))
    assert len(http.to("ntfy.sh")) == 1


def test_rule_config_errors_are_caught_early():
    notifiers = build_notifiers(CFG["notifiers"])
    typo = {"name": "r", "match": {"sender": SUP}, "notfy": ["phone"]}  # would silently mute the rule
    with pytest.raises(ValueError, match=r"rule 'r': unknown keys \['notfy'\]"):
        build_bus({"rules": [typo]}, notifiers)
    with pytest.raises(ValueError, match="unknown priority 'urgnet'"):
        build_bus({"rules": [{"name": "r", "priority": "urgnet", "notify": ["phone"]}]}, notifiers)


def test_unknown_top_level_config_key(tmp_path):
    from hooks.app import load_config
    (tmp_path / "config.yaml").write_text("rule:\n  - name: r\n")
    with pytest.raises(ValueError, match=r"unknown top-level keys \['rule'\]"):
        load_config(tmp_path / "config.yaml", tmp_path / ".env")


def test_zulip_source_config_validation():
    from hooks.sources.zulip_source import ZulipSource
    with pytest.raises(ValueError, match="site, email and api_key"):
        ZulipSource({"site": "x"})
    with pytest.raises(ValueError, match="unknown options"):
        ZulipSource({"zuliprc": "~/z", "sitee": "typo"})
    assert ZulipSource({"zuliprc": "~/z"}).client_args["config_file"].endswith("/z")


def test_bus_publish_is_async():
    import threading

    from hooks.bus import EventBus
    from hooks.events import Event

    got, done, release = [], threading.Event(), threading.Event()

    class Slow:
        name = "slow"

        def __call__(self, e):
            release.wait(5)
            got.append(e.title)
            if len(got) == 2:
                done.set()
            return True

    bus = EventBus()
    unsubscribe = bus.subscribe(Slow())
    bus.start()
    bus.publish(Event("t", "a", ""))
    bus.publish(Event("t", "b", ""))
    assert got == [], "publish must not wait for subscribers"
    release.set()
    assert done.wait(5)
    unsubscribe()
    bus.stop()
    assert got == ["a", "b"]
