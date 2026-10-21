"""Where hooks keeps its per-machine files.

Everything lives in the project checkout (git-ignored), unless HOOKS_HOME
points elsewhere:

    config.yaml   what this machine does (sources, notifiers, rules)
    .env          secrets referenced from config.yaml as ${NAME}
    logs/         log output when run by launchd (macOS)
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent


def home() -> Path:
    return Path(os.environ.get("HOOKS_HOME") or PROJECT_ROOT).expanduser().resolve()


def config_file() -> Path:
    return home() / "config.yaml"


def env_file() -> Path:
    return home() / ".env"


def example_config() -> Path:
    return PROJECT_ROOT / "config.example.yaml"


def log_dir() -> Path:
    return home() / "logs"
