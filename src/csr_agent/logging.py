"""Structured logging utilities for per-task event tracing."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """Return UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class LogEvent:
    """A single structured event."""

    unique_id: str
    stage: str
    event_id: str
    timestamp: str
    message: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "unique_id": self.unique_id,
            "stage": self.stage,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "message": self.message,
            "payload": self.payload,
        }


class StructuredLogger:
    """Collect and optionally persist structured events."""

    def __init__(self, sink_path: Path | None = None) -> None:
        self._sink_path = sink_path
        self._events: list[LogEvent] = []
        if sink_path is not None:
            sink_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def events(self) -> list[LogEvent]:
        return list(self._events)

    def emit(
        self,
        unique_id: str,
        stage: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> LogEvent:
        event = LogEvent(
            unique_id=unique_id,
            stage=stage,
            event_id=str(uuid.uuid4()),
            timestamp=utc_now_iso(),
            message=message,
            payload=payload or {},
        )
        self._events.append(event)
        if self._sink_path is not None:
            with self._sink_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event
