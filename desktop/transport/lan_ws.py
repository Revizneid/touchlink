"""Local LAN WebSocket transport stub used as the compatibility transport for Sprint 3.1."""

from __future__ import annotations

from typing import Any, Dict

from .base import Transport


class LanWsTransport(Transport):
    def __init__(self, *, endpoint: str | None = None, name: str = "lan_ws") -> None:
        super().__init__()
        self.endpoint = endpoint
        self.name = name
        self._sent: list[Any] = []
        self._last_video: Any = None

    def start(self) -> bool:
        self._started = True
        return True

    def send_video(self, frame: Any) -> Any:
        self._last_video = frame
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


__all__ = ["LanWsTransport"]
