"""Abstract transport layer for the upcoming WebRTC and transport refactor."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class Transport(ABC):
    """Common transport interface used by the desktop core and future WebRTC implementation."""

    def __init__(self) -> None:
        self._data_callback: Callable[[Any], None] | None = None
        self._peer_callback: Callable[[str, dict[str, Any]], None] | None = None
        self._started = False

    @property
    def started(self) -> bool:
        return bool(self._started)

    def on_data(self, callback: Callable[[Any], None]) -> None:
        self._data_callback = callback

    def on_peer_change(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        self._peer_callback = callback

    @abstractmethod
    def start(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def send_video(self, frame: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def send_data(self, message: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


__all__ = ["Transport"]
