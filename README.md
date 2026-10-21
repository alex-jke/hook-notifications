# hooks

Get a phone notification when something you care about happens, starting
with Zulip messages from specific people, for organizations whose Zulip
server has no mobile push.

`hooks` listens to Zulip's real-time API with your own account, matches each
message against rules you write in YAML, and delivers matches through
pluggable notifiers: [ntfy](https://ntfy.sh), Telegram, or any of the ~100
services supported by [Apprise](https://github.com/caronc/apprise).

```
 Sources                 EventBus (pub/sub)           Notifiers
┌─────────┐  publish   ┌───────────────────┐ send  ┌──────────────────────────┐
│ zulip   │──Event────▶│ rule subscriber 1 │──────▶│ phone = retry(ntfy)      │
│ (more   │            │ rule subscriber 2 │──────▶│ reliable = fallback(     │
│  later) │            │ …                 │       │   telegram, ntfy)        │
└─────────┘            └───────────────────┘       └──────────────────────────┘
```

## Quick start

Requires Python ≥ 3.10 on Linux or macOS.

```bash
git clone https://github.com/<you>/hooks.git && cd hooks
./setup.sh                # venv + install + creates config.yaml and .env (both git-ignored)
$EDITOR .env              # fill in the secrets (keys are listed with hints)
$EDITOR config.yaml       # who/what should notify you, and how
.venv/bin/hooks check     # validate
.venv/bin/hooks test      # your phone should buzz
.venv/bin/hooks run --dry-run    # watch real messages, send nothing
.venv/bin/hooks service install  # run in the background (systemd user unit / launchd agent)
```

You need two things to fill in `.env`:
- **Zulip API key**: *Personal settings → Account & privacy → API key*.
- **ntfy topic**: install the ntfy app and subscribe to a long random topic
  (`openssl rand -hex 12`). Anyone who knows the topic can read it.

## Per-machine files (never committed)

| file          | contents                                                 |
|---------------|----------------------------------------------------------|
| `config.yaml` | what this machine does: sources, notifiers, rules        |
| `.env`        | secrets, referenced from config.yaml as `${NAME}`        |
| `logs/`       | log file when running under launchd (macOS)              |

`hooks init` creates both files and is safe to re-run. When you add a
`${NEW_SECRET}` to `config.yaml`, re-running it appends an empty `NEW_SECRET=`
line to `.env` and never touches existing values. Real environment
variables override `.env`. Set `HOOKS_HOME` to keep these files somewhere
other than the checkout.

> Enable the Zulip source on **one** machine only, or every notification arrives twice.

## Configuration

See [`config.example.yaml`](config.example.yaml), which documents every option. In short:

- **Rules** are checked in order. Each one has `match` (source, sender, any_tags,
  all_tags, keywords), a `priority` (low, normal, high or urgent) and `notify`
  (a list of notifier names). A matching rule consumes the event unless it has `final: false`.
- **Zulip tags** are `dm`, `mention`, `wildcard_mention`, `channel:<name>` and `topic:<name>`.
- **Notifiers**:
  - Providers: `ntfy`, `telegram`, `apprise`, `log`.
  - Combinators: `fanout`, `fallback`, `retry`, `min_priority`. Combinators
    refer to other notifiers by name and can be nested.
- **Health** (optional): pings a [healthchecks.io](https://healthchecks.io) check while
  everything is connected, so you're alerted if hooks itself goes down.

## Commands

```
hooks init                       create/refresh config.yaml and the .env skeleton
hooks check                      validate config and secrets
hooks test [NOTIFIER ...]        send a test notification
hooks run [--dry-run]            run in the foreground
hooks service install|uninstall|status|logs|restart
scripts/deploy.sh user@host      pull + install + restart on a remote machine over SSH
```

On Linux, the service keeps running after you log out only if lingering is
enabled for your user, which needs an admin once: `sudo loginctl enable-linger $USER`.

## Extending

- **Delivery provider**: add a `Notifier` subclass in `hooks/notifiers/`.
  Decorate it with `@register("name")`, implement `send()`, and raise
  `NotifyError` on failure. Its `__init__` keyword arguments become the
  config options. Import the module in `hooks/notifiers/__init__.py`.
- **Source**: add a class with `name`, `run(emit)` and optionally `healthy()` in
  `hooks/sources/`, then register it in `hooks/sources/__init__.py`.
- **Other subscribers** (digest, archive, …): anything callable with a
  `name` can subscribe to the `EventBus`.

## Development

```bash
./setup.sh --dev
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Tests use fakes for Zulip and HTTP and never touch the network.

## License

MIT, see [LICENSE](LICENSE). Dependencies are permissively licensed:
`zulip` (Apache-2.0), `requests` (Apache-2.0), `PyYAML` (MIT) and, optionally, `apprise` (BSD).
