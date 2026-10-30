from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}{uid}" if prefix else uid


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_correlation_id() -> str:
    return uuid.uuid4().hex
