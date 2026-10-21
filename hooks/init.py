"""`hooks init`: create this machine's git-ignored files, safely and
repeatably.

- config.yaml is copied from config.example.yaml if it doesn't exist yet.
- .env gets an empty `NAME=` line for every ${NAME} that config.yaml uses
  and .env doesn't have yet. Existing values are never touched, so re-run it
  whenever you add a notifier or source that needs a new secret.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import yaml

from hooks.env import find_vars, read_env_file

ENV_HEADER = """\
# Secrets for hooks on this machine. This file is git-ignored: never commit it.
# config.yaml refers to these values as ${NAME}.
# After adding a new ${NAME} to config.yaml, run `hooks init` again to add the key here.
"""

# Shown as a comment above a newly added key. Unknown names just get a blank line.
HINTS = {
    "ZULIP_SITE": "Zulip server URL, e.g. https://yourorg.zulipchat.com",
    "ZULIP_EMAIL": "Your Zulip login email (Personal settings -> Account & privacy)",
    "ZULIP_API_KEY": "Personal settings -> Account & privacy -> API key",
    "NTFY_TOPIC": "Long random ntfy topic; anyone who knows it can read it. e.g.: openssl rand -hex 12",
    "NTFY_TOKEN": "Only needed for a protected/self-hosted ntfy server",
    "TELEGRAM_BOT_TOKEN": "From @BotFather",
    "TELEGRAM_CHAT_ID": "Message your bot, then see https://api.telegram.org/bot<TOKEN>/getUpdates",
    "HEALTHCHECK_URL": "Ping URL of a check on https://healthchecks.io (dead-man's switch)",
}


def _private(path: Path) -> None:
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def run_init(config: Path, env: Path, example: Path, out=print) -> int:
    config.parent.mkdir(parents=True, exist_ok=True)

    if config.exists():
        out(f"kept     {config}")
    else:
        shutil.copyfile(example, config)
        out(f"created  {config}  (from {example.name}; edit it for this machine)")
    _private(config)

    try:
        needed = find_vars(yaml.safe_load(config.read_text()) or {})
    except yaml.YAMLError as exc:
        out(f"error: {config} is not valid YAML: {exc}")
        return 1

    existed = env.exists()
    current = read_env_file(env)
    new = [n for n in needed if n not in current]

    text = env.read_text() if existed else ENV_HEADER
    if new:
        if text and not text.endswith("\n"):
            text += "\n"
        for name in new:
            hint = HINTS.get(name)
            text += f"\n# {hint}\n{name}=\n" if hint else f"\n{name}=\n"
        env.write_text(text)
    elif not existed:
        env.write_text(text)
    _private(env)

    out(f"{'updated ' if existed else 'created '} {env}" + (f"  (+{len(new)} key(s): {', '.join(new)})" if new else ""))
    empty = [n for n in needed if not current.get(n)]
    unused = [n for n in current if n not in needed]
    if empty:
        out(f"\nfill in: {', '.join(empty)}  ->  {env}")
    if unused:
        out(f"note: not used by config.yaml (harmless, delete if you like): {', '.join(unused)}")
    if not empty:
        out("\nall secrets present. Next: `hooks check`, then `hooks test`.")
    return 0
