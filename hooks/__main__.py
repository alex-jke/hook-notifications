"""Command line interface.

    hooks init                 create/refresh this machine's config.yaml and .env skeleton
    hooks check                validate config + secrets and exit
    hooks test [NOTIFIER ...]  send a test notification (all notifiers if none named)
    hooks run [--dry-run]      run in the foreground (what the service runs)
    hooks service install|uninstall|status|logs|restart
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from hooks import paths

log = logging.getLogger("hooks")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _build(dry_run: bool = False):
    from hooks.app import build_bus, build_notifiers, build_sources, load_config
    from hooks.health import Heartbeat

    cfg = load_config(paths.config_file(), paths.env_file())
    notifiers = build_notifiers(cfg.get("notifiers"))
    bus = build_bus(cfg, notifiers, dry_run=dry_run)
    sources = build_sources(cfg)
    heartbeat = None if dry_run else Heartbeat.from_config(cfg.get("health"), sources)
    return cfg, notifiers, bus, sources, heartbeat


def cmd_init(args) -> int:
    from hooks.init import run_init
    return run_init(paths.config_file(), paths.env_file(), paths.example_config())


def cmd_check(args) -> int:
    cfg, notifiers, _, sources, heartbeat = _build()
    log.info("config OK (%s): %d notifier(s), %d rule(s), sources: %s, heartbeat: %s",
             paths.config_file(), len(notifiers), len(cfg.get("rules") or []),
             ", ".join(s.name for s in sources) or "none", "on" if heartbeat else "off")
    return 0


def cmd_test(args) -> int:
    from hooks.events import Notification, Priority
    from hooks.notifiers import NotifyError

    _, notifiers, _, _, _ = _build()
    ok = True
    for name in args.notifiers or list(notifiers):
        if name not in notifiers:
            log.error("no notifier named '%s' (have: %s)", name, ", ".join(notifiers))
            ok = False
            continue
        try:
            notifiers[name].send(Notification("hooks test", f"Test notification via '{name}'.",
                                              priority=Priority.HIGH))
            log.info("%s: sent", name)
        except NotifyError as exc:
            log.error("%s: FAILED: %s", name, exc)
            ok = False
    return 0 if ok else 1


def cmd_run(args) -> int:
    from hooks.app import start_sources

    _, _, bus, sources, heartbeat = _build(dry_run=args.dry_run)
    if not sources:
        log.error("no sources enabled in %s", paths.config_file())
        return 1
    bus.start()
    start_sources(sources, bus)
    if heartbeat:
        heartbeat.start()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("running%s (config: %s)", " in dry-run mode" if args.dry_run else "", paths.config_file())
    stop.wait()
    log.info("shutting down")
    bus.stop()
    return 0


def cmd_service(args) -> int:
    from hooks.service import ACTIONS
    return ACTIONS[args.action]()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hooks", description="Personal notification hooks.")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("init", help="create/refresh config.yaml and the .env skeleton").set_defaults(fn=cmd_init)
    sub.add_parser("check", help="validate config and secrets").set_defaults(fn=cmd_check)
    t = sub.add_parser("test", help="send a test notification")
    t.add_argument("notifiers", nargs="*", metavar="NOTIFIER")
    t.set_defaults(fn=cmd_test)
    r = sub.add_parser("run", help="run in the foreground")
    r.add_argument("--dry-run", action="store_true", help="log what would be sent instead of sending")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("service", help="manage the background service (systemd/launchd)")
    s.add_argument("action", choices=["install", "uninstall", "status", "logs", "restart"])
    s.set_defaults(fn=cmd_service)

    args = p.parse_args(argv)
    _setup_logging(args.verbose)
    if not args.command:
        p.print_help()
        return 2
    try:
        return args.fn(args)
    except (ValueError, FileNotFoundError) as exc:  # config problems: short message, no traceback
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
