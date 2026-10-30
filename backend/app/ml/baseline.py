"""Reproducible, deterministic baseline utilities; no trained model is claimed."""

from collections import Counter


def classify_events(events: list[dict[str, int | str]]) -> list[str]:
    """Classify telemetry with explicit rules rather than an untrained ML model."""
    labels: list[str] = []
    for event in events:
        code = int(event.get("status_code", 200))
        elapsed = int(event.get("elapsed_ms", 0))
        rejected = bool(event.get("business_rejected", False))
        if rejected:
            labels.append("ORDER_REJECTION")
        elif code >= 400:
            labels.append("API_ERROR")
        elif elapsed > 30000:
            labels.append("ORDER_DELAY")
        else:
            labels.append("NORMAL")
    return labels


def frequent_failure(labels: list[str]) -> str | None:
    failures = [label for label in labels if label != "NORMAL"]
    return Counter(failures).most_common(1)[0][0] if failures else None
