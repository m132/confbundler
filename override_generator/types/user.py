from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(init=False)
class Group:
    name: str = 'root'
    id: int = 0

    def __init__(self, name: str, id: int | None = None):
        self.name = name
        if id is not None:
            self.id = id


@dataclass(init=False)
class User:
    name: str = 'root'
    id: int = 0
    groups: list[Group] = field(default_factory=list)

    def __init__(self, name: str, id: int | None = None,
                 groups: Iterable[Group] | None = None):
        self.name = name
        if id is not None:
            self.id = id
        self.groups = list(groups) if groups else []
