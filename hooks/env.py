"""Secrets handling: a minimal .env reader and strict ${NAME} expansion.

Values come from the .env file; real environment variables override them
(handy for CI or a one-off `NTFY_TOPIC=test hooks test`).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingSecrets(ValueError):
    def __init__(self, names: list[str], env_path: Path | None):
        self.names = names
        where = f" in {env_path}" if env_path else ""
        super().__init__(
            f"missing or empty secret(s){where}: {', '.join(names)}. "
            "Run `hooks init` to add the keys, then fill in the values."
        )


def read_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Supports comments, blank lines, `export KEY=...`
    and single or double quotes around the value."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{path}:{lineno}: expected KEY=VALUE")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:  # trailing comment on an unquoted value
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def find_vars(obj) -> list[str]:
    """All ${NAME} references in a parsed config, in order of appearance."""
    found: list[str] = []

    def walk(o):
        if isinstance(o, str):
            for name in VAR_RE.findall(o):
                if name not in found:
                    found.append(name)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
    walk(obj)
    return found


def expand(obj, env: dict[str, str], env_path: Path | None = None):
    """Replace ${NAME} everywhere. Raises MissingSecrets listing every
    missing or empty value at once, so you can fix them in one go."""
    missing = [n for n in find_vars(obj) if not env.get(n)]
    if missing:
        raise MissingSecrets(missing, env_path)

    def sub(o):
        if isinstance(o, str):
            return VAR_RE.sub(lambda m: env[m.group(1)], o)
        if isinstance(o, list):
            return [sub(v) for v in o]
        if isinstance(o, dict):
            return {k: sub(v) for k, v in o.items()}
        return o
    return sub(obj)


def load_env(path: Path) -> dict[str, str]:
    env = read_env_file(path)
    env.update({k: v for k, v in os.environ.items() if v})
    return env
