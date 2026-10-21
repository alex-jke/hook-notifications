"""Builds the running system from the config file:

    sources ──publish──▶ EventBus ──▶ RuleSubscribers ──▶ Notifiers
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import yaml

from hooks.bus import EventBus
from hooks.env import expand, load_env
from hooks.events import Priority
from hooks.notifiers import NOTIFIER_TYPES, Notifier
from hooks.notifiers.composite import FanOut
from hooks.notifiers.misc import LogNotifier
from hooks.rules import Matcher, RuleSubscriber, as_list
from hooks.sources import SOURCES

log = logging.getLogger("hooks")

CONFIG_KEYS = {"sources", "notifiers", "rules", "health"}
RULE_KEYS = {"name", "match", "priority", "notify", "final"}


def load_config(config_path: Path, env_path: Path) -> dict:
    """Read config.yaml and fill in ${NAME} secrets from .env / the environment."""
    if not config_path.exists():
        raise FileNotFoundError(f"{config_path} not found. Run `hooks init` (or ./setup.sh) first.")
    raw = yaml.safe_load(config_path.read_text()) or {}
    unknown = set(raw) - CONFIG_KEYS
    if unknown:
        raise ValueError(f"{config_path}: unknown top-level keys {sorted(unknown)} "
                         f"(expected: {', '.join(sorted(CONFIG_KEYS))})")
    return expand(raw, load_env(env_path), env_path)


def build_notifiers(cfg: dict) -> dict[str, Notifier]:
    """Instantiate every notifier, resolving references between them
    (fanout/fallback/retry targets) in dependency order."""
    specs = cfg or {}
    built: dict[str, Notifier] = {}
    in_progress: set[str] = set()

    def resolve(name: str) -> Notifier:
        if name in built:
            return built[name]
        if name not in specs:
            raise ValueError(f"unknown notifier '{name}'")
        if name in in_progress:
            raise ValueError(f"notifier '{name}' refers to itself (cycle)")
        in_progress.add(name)
        spec = dict(specs[name] or {})
        type_name = spec.pop("type", None)
        if type_name not in NOTIFIER_TYPES:
            raise ValueError(f"notifier '{name}': unknown type '{type_name}' "
                             f"(available: {', '.join(sorted(NOTIFIER_TYPES))})")
        built[name] = NOTIFIER_TYPES[type_name].from_config(name, spec, resolve)
        in_progress.discard(name)
        return built[name]

    for name in specs:
        resolve(name)
    return built


def build_bus(cfg: dict, notifiers: dict[str, Notifier], dry_run: bool = False) -> EventBus:
    bus = EventBus()
    for i, r in enumerate(cfg.get("rules") or []):
        name = r.get("name", f"rule-{i + 1}")
        unknown = set(r) - RULE_KEYS
        if unknown:  # e.g. a misspelled `notify` would otherwise silently mute the rule
            raise ValueError(f"rule '{name}': unknown keys {sorted(unknown)}")
        targets = as_list(r.get("notify"))
        missing = [t for t in targets if t not in notifiers]
        if missing:
            raise ValueError(f"rule '{name}': unknown notifier(s) {missing}")
        if not targets:
            notifier = None
        elif dry_run:
            notifier = LogNotifier(f"dry-run:{'+'.join(targets)}", label=f"dry-run -> {', '.join(targets)}")
        elif len(targets) == 1:
            notifier = notifiers[targets[0]]
        else:
            notifier = FanOut("+".join(targets), [notifiers[t] for t in targets])
        bus.subscribe(RuleSubscriber(
            name=name,
            matcher=Matcher(r.get("match")),
            notifier=notifier,
            priority=Priority.parse(r.get("priority", "normal")),
            final=bool(r.get("final", True)),
        ))
    return bus


def _run_source_forever(src, publish) -> None:
    while True:
        try:
            src.run(publish)
        except Exception:
            log.exception("source '%s' crashed; restarting in 30s", src.name)
            time.sleep(30)


def build_sources(cfg: dict) -> list:
    sources = []
    for name, scfg in (cfg.get("sources") or {}).items():
        scfg = dict(scfg or {})
        if not scfg.pop("enabled", True):
            continue
        if name not in SOURCES:
            raise ValueError(f"unknown source '{name}' (available: {', '.join(SOURCES)})")
        sources.append(SOURCES[name](scfg))
    return sources


def start_sources(sources: list, bus: EventBus) -> None:
    for src in sources:
        threading.Thread(target=_run_source_forever, args=(src, bus.publish),
                         name=f"source:{src.name}", daemon=True).start()
