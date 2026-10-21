"""The Notifier interface and the registry that maps config `type:` names to
implementations.

To add a provider:

    @register("myprovider")
    class MyNotifier(Notifier):
        def __init__(self, name, *, api_key, **_):
            super().__init__(name)
            ...
        def send(self, n: Notification) -> None:
            ...  # raise NotifyError on failure

and import the module in hooks/notifiers/__init__.py. Config:

    notifiers:
      foo: { type: myprovider, api_key: ... }
"""
from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable

from hooks.events import Notification

NOTIFIER_TYPES: dict[str, type[Notifier]] = {}

# resolve(name) -> Notifier, handed to composites so they can refer to others
Resolver = Callable[[str], "Notifier"]


class NotifyError(Exception):
    """Delivery failed. Composites rely on this to decide what to do next."""


class Notifier(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def send(self, n: Notification) -> None:
        """Deliver n. Must raise NotifyError if it was not delivered."""

    @classmethod
    def from_config(cls, name: str, cfg: dict, resolve: Resolver) -> Notifier:
        """Default: pass config keys as keyword arguments to __init__.
        Composites override this to resolve the notifiers they wrap."""
        params = inspect.signature(cls.__init__).parameters
        accepts_any = any(p.kind is p.VAR_KEYWORD for p in params.values())
        unknown = [k for k in cfg if k not in params and not accepts_any]
        if unknown:
            raise ValueError(f"notifier '{name}' ({cls.type_name}): unknown options {unknown}")
        return cls(name, **cfg)

    type_name = "?"

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}>"


def register(type_name: str):
    def deco(cls: type[Notifier]) -> type[Notifier]:
        if type_name in NOTIFIER_TYPES:
            raise ValueError(f"notifier type '{type_name}' registered twice")
        cls.type_name = type_name
        NOTIFIER_TYPES[type_name] = cls
        return cls
    return deco
