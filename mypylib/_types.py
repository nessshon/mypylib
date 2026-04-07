from __future__ import annotations

from enum import Enum
from typing import Any, NamedTuple


class ByteUnit(Enum):
    """Binary unit exponents (powers of 1024) for byte-to-unit conversion."""

    B = 0
    KB = 1
    MB = 2
    GB = 3
    TB = 4


class DiskSpace(NamedTuple):
    """Disk usage snapshot in a single unit."""

    total: float
    used: float
    free: float


class MemoryInfo(NamedTuple):
    """Memory usage snapshot (values in binary GB)."""

    total: float
    used: float
    percent: float


class UnameInfo(NamedTuple):
    """System uname info (nodename excluded for privacy)."""

    sysname: str
    release: str
    version: str
    machine: str


class Dict(dict[str, Any]):
    """A ``dict`` subclass that allows attribute-style access.

    Nested ``dict`` and ``list`` values are recursively converted
    so that ``obj.key.nested`` works at any depth.
    """

    def __init__(self, *args: dict[str, Any], **kwargs: Any) -> None:
        super().__init__()
        for item in args:
            self._parse_dict(item)
        self._parse_dict(kwargs)

    def _parse_dict(self, d: dict[str, Any]) -> None:
        """Merge *d* into self, converting nested dicts and lists.

        :param d: Source dictionary to merge.
        """
        for key, value in d.items():
            if isinstance(value, dict):
                value = Dict(value)
            if isinstance(value, list):
                value = self._parse_list(value)
            self[key] = value

    @staticmethod
    def _parse_list(lst: list[Any]) -> list[Any]:
        """Return a copy of *lst* with nested dicts converted to :class:`Dict`.

        :param lst: Source list.
        :return: New list with converted elements.
        """
        result: list[Any] = []
        for value in lst:
            if isinstance(value, dict):
                value = Dict(value)
            result.append(value)
        return result

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value

    def __getattr__(self, key: str) -> Any:
        return self.get(key)
