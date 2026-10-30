"""Sanity-check the deterministic baseline against the checked-in synthetic labels."""

import csv
from pathlib import Path

from .baseline import classify_events


def main() -> None:
    dataset = Path(__file__).parents[3] / "dataset" / "synthetic_api_logs.csv"
    with dataset.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    events = [
        {
            "status_code": int(row["status_code"]),
            "elapsed_ms": int(row["response_ms"]),
            "business_rejected": row["category"] == "ORDER_REJECTION",
        }
        for row in rows
    ]
    predicted = classify_events(events)
    expected = [row["category"] for row in rows]
    correct = sum(actual == guess for actual, guess in zip(expected, predicted))
    print(f"Rule baseline: {correct}/{len(expected)} labeled rows matched")
    print("This is a deterministic rules check, not an ML training or evaluation claim.")


if __name__ == "__main__":
    main()
