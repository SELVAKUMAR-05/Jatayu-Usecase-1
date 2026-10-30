"""
Telemetry and tracing utilities
"""
from __future__ import annotations

from typing import Any
import json
from datetime import datetime

from app.core.utils import now_utc


class TelemetryCollector:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    def record(self, event_type: str, data: dict[str, Any], order_id: str | None = None, trace_id: str | None = None, correlation_id: str | None = None):
        evt = {
            "event_id": f"evt_{id(self)}_{len(self.events)}",
            "event_type": event_type,
            "order_id": order_id,
            "trace_id": trace_id,
            "correlation_id": correlation_id,
            "timestamp": now_utc().isoformat(),
            "data": data,
        }
        self.events.append(evt)
        return evt

    def get_recent(self, limit: int = 100):
        return list(reversed(self.events[-limit:]))


telemetry = TelemetryCollector()
