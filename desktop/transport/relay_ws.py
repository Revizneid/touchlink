"""Relay WebSocket transport stub that mirrors the existing relay connection behavior."""

from __future__ import annotations

from typing import Any, Dict

from .base import Transport


class RelayWsTransport(Transport):
    def __init__(self, *, endpoint: str | None = None, name: str = "relay_ws") -> None:
        super().__init__()
        self.endpoint = endpoint
        self.name = name
        self._sent: list[Any] = []

    def start(self) -> bool:
        self._started = True
        return True

    def send_video(self, frame: Any) -> Any:
        return {"transport": self.name, "video_frame": frame}

    def send_data(self, message: Any) -> Any:
        self._sent.append(message)
        if callable(self._data_callback):
            self._data_callback(message)
        return {"transport": self.name, "sent": message}

    def stats(self) -> Dict[str, Any]:
        return {"transport": self.name, "started": self.started, "sent_count": len(self._sent)}

    def close(self) -> None:
        self._started = False


__all__ = ["RelayWsTransport"]
