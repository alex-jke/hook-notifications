"""Sources produce Events. A source is any class with a `name` and a
`run(emit)` method that loops forever and calls `emit(Event(...))` for each
thing it observes (it may raise; it is restarted after 30s). Register new
sources here and give them a section under `sources:` in the config."""
from collections.abc import Callable
from typing import Protocol

from hooks.events import Event
from hooks.sources.zulip_source import ZulipSource


class Source(Protocol):
    name: str

    def __init__(self, cfg: dict): ...
    def run(self, emit: Callable[[Event], None]) -> None: ...


SOURCES: dict[str, type[Source]] = {
    "zulip": ZulipSource,
}
