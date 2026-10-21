"""Secrets handling, `hooks init` and the CLI against a temporary HOOKS_HOME."""
from __future__ import annotations

import os
import stat

import pytest

from hooks import paths
from hooks.__main__ import main
from hooks.env import MissingSecrets, expand, find_vars, read_env_file
from hooks.init import run_init


def test_read_env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# c\n\nA=1\nexport B="two words"\nC=\'q\'\nD=x # trailing\nE=\n')
    assert read_env_file(p) == {"A": "1", "B": "two words", "C": "q", "D": "x", "E": ""}
    p.write_text("not a pair\n")
    with pytest.raises(ValueError, match=":1:"):
        read_env_file(p)


def test_expand_reports_all_missing_at_once():
    cfg = {"a": "${X}", "b": ["${Y}", "lit"], "c": {"d": "pre-${X}-post"}}
    assert find_vars(cfg) == ["X", "Y"]
    assert expand(cfg, {"X": "1", "Y": "2"}) == {"a": "1", "b": ["2", "lit"], "c": {"d": "pre-1-post"}}
    with pytest.raises(MissingSecrets) as e:
        expand(cfg, {"X": ""})
    assert e.value.names == ["X", "Y"]


def test_init_is_idempotent_and_never_overwrites(tmp_path):
    cfg, env = tmp_path / "config.yaml", tmp_path / ".env"
    run_init(cfg, env, paths.example_config(), out=lambda *_: None)
    keys = read_env_file(env)
    assert {"ZULIP_SITE", "ZULIP_EMAIL", "ZULIP_API_KEY", "NTFY_TOPIC"} <= set(keys)
    assert all(v == "" for v in keys.values())
    if os.name == "posix":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o600

    # user fills in a value and adds a new secret reference to config
    env.write_text(env.read_text().replace("NTFY_TOPIC=", "NTFY_TOPIC=mytopic"))
    cfg.write_text(cfg.read_text() + "\nextra:\n  token: ${NEW_TOKEN}\n")
    run_init(cfg, env, paths.example_config(), out=lambda *_: None)
    keys = read_env_file(env)
    assert keys["NTFY_TOPIC"] == "mytopic"
    assert keys["NEW_TOKEN"] == ""
    assert env.read_text().count("NTFY_TOPIC=") == 1


def test_cli_init_check_test(tmp_path, monkeypatch, http):
    monkeypatch.setenv("HOOKS_HOME", str(tmp_path))
    assert main(["init"]) == 0
    assert main(["check"]) == 1, "empty secrets must fail the check"

    env = tmp_path / ".env"
    text = env.read_text()
    for k, v in {"ZULIP_SITE": "https://z.example", "ZULIP_EMAIL": "me@x", "ZULIP_API_KEY": "k",
                 "NTFY_TOPIC": "topic"}.items():
        text = text.replace(f"{k}=\n", f"{k}={v}\n")
    env.write_text(text)
    assert main(["check"]) == 0
    assert main(["test", "phone"]) == 0
    assert http.to("ntfy.sh")[0]["topic"] == "topic"
    assert main(["test", "nope"]) == 1


def test_real_environment_overrides_env_file(tmp_path, monkeypatch):
    from hooks.env import load_env
    (tmp_path / ".env").write_text("A=file\nB=file\n")
    monkeypatch.setenv("A", "shell")
    env = load_env(tmp_path / ".env")
    assert env["A"] == "shell" and env["B"] == "file"


def test_heartbeat(http):
    from hooks.health import Heartbeat

    class Src:
        name, ok = "s", True

        def healthy(self):
            return self.ok

    s = Src()
    hb = Heartbeat.from_config({"ping_url": "https://hc-ping.com/uuid/"}, [s])
    hb.ping_once()
    s.ok = False
    hb.ping_once()
    assert [u for u, _ in http.calls] == ["https://hc-ping.com/uuid", "https://hc-ping.com/uuid/fail"]
    assert Heartbeat.from_config(None, [s]) is None
