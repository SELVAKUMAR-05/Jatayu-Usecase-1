"""Generate synthetic dataset for training ML models"""
from __future__ import annotations

import csv
import random
from pathlib import Path

random.seed(42)


SERVICES = ["CRM", "OMS", "Inventory", "Payment", "Provisioning", "Logistics", "Notification"]
ENDPOINTS = ["/orders/create", "/inventory/check", "/payment/charge", "/provision/activate", "/logistics/ship", "/notify/send"]
CATEGORIES = ["NORMAL", "API_ERROR", "ORDER_DELAY", "ORDER_REJECTION"]


def generate(n: int = 5000):
    rows = []
    for i in range(n):
        service = random.choice(SERVICES)
        endpoint = random.choice(ENDPOINTS)
        status_code = random.choices([200, 201, 400, 401, 422, 429, 500, 502, 503, 504], weights=[0.6,0.1,0.05,0.01,0.03,0.01,0.07,0.05,0.05,0.03])[0]
        elapsed_ms = int(random.gauss(800, 400))
        if status_code >= 500 or status_code == 504:
            elapsed_ms = int(random.gauss(45000, 15000))
        retry_count = random.randint(0, 3)
        queue_depth = random.randint(0, 150)
        recent_failures = random.randint(0, 10)
        sla_ms = 30000
        order_stage = random.choice(["CREATED", "VALIDATING", "INVENTORY", "PAYMENT", "PROVISIONING", "SHIPPING", "NOTIFYING"])
        business_rejected = 1 if status_code == 422 and random.random() < 0.7 else 0
        # label
        if business_rejected or status_code == 422:
            label = "ORDER_REJECTION"
        elif status_code >= 500 or status_code == 504 or elapsed_ms > sla_ms:
            label = "API_ERROR" if status_code >= 500 else "ORDER_DELAY"
        elif elapsed_ms > sla_ms * 0.8:
            label = "ORDER_DELAY"
        elif status_code >= 400:
            label = "API_ERROR"
        else:
            label = "NORMAL"
        rows.append({
            "request_id": f"req_{i:06d}",
            "service": service,
            "endpoint": endpoint,
            "status_code": status_code,
            "elapsed_ms": max(10, elapsed_ms),
            "retry_count": retry_count,
            "queue_depth": queue_depth,
            "recent_failures": recent_failures,
            "order_stage": order_stage,
            "business_rejected": business_rejected,
            "label": label,
        })
    return rows


def main():
    out = Path(__file__).parent / "synthetic_training.csv"
    rows = generate(5000)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
