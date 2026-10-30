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


def generate_delay_dataset(n: int = 5000, seed: int = 42):
    rng = random.Random(seed)
    stage_remaining_ms = {
        "VALIDATING": 85000,
        "INVENTORY": 75000,
        "PAYMENT": 55000,
        "PROVISIONING": 45000,
        "LOGISTICS": 30000,
    }
    rows = []
    for index in range(n):
        stage = rng.choice(list(stage_remaining_ms))
        processing_duration_ms = rng.randint(5000, 110000)
        queue_depth = rng.randint(0, 180)
        service_latency_ms = rng.randint(40, 5000)
        historical_service_latency_ms = rng.randint(50, 1800)
        previous_stage_duration_ms = rng.randint(500, 35000)
        queue_delay_ms = queue_depth * 240
        latency_deviation_ms = max(
            0, service_latency_ms - historical_service_latency_ms
        ) * 7
        noise_ms = rng.gauss(0, 6500)
        remaining_processing_ms = max(
            1000,
            int(
                stage_remaining_ms[stage]
                + queue_delay_ms
                + latency_deviation_ms
                + previous_stage_duration_ms * 0.25
                + noise_ms
            ),
        )
        sla_deadline_ms = 120000
        rows.append(
            {
                "sample_id": f"delay_{index:06d}",
                "processing_duration_ms": processing_duration_ms,
                "current_stage": stage,
                "queue_depth": queue_depth,
                "service_latency_ms": service_latency_ms,
                "previous_stage_duration_ms": previous_stage_duration_ms,
                "historical_service_latency_ms": historical_service_latency_ms,
                "sla_utilization": processing_duration_ms / sla_deadline_ms,
                "remaining_processing_ms": remaining_processing_ms,
                "sla_breach": int(
                    processing_duration_ms + remaining_processing_ms > sla_deadline_ms
                ),
            }
        )
    return rows


def generate_failure_classification_dataset(n: int = 12000, seed: int = 42):
    rng = random.Random(seed)
    scenarios = {
        "NORMAL": ([200, 201, 202, 204], ["request completed successfully", "response returned with valid payload", "service accepted the operation"]),
        "SERVER_ERROR": ([500, 502, 503, 504], ["upstream service returned an internal error", "service temporarily unavailable", "dependency failed while processing request"]),
        "AUTHENTICATION_FAILURE": ([401, 403], ["access token expired", "caller is not authorized for this resource", "credential check failed at the service"]),
        "RATE_LIMIT": ([429, 503], ["request rate limit exceeded", "too many requests; retry after the service window", "service throttled this caller"]),
        "REQUEST_VALIDATION": ([400, 409, 422], ["required field failed validation", "request payload contains an invalid value", "service rejected an unsupported field"]),
        "API_TIMEOUT": ([500, 502, 504], ["gateway timed out waiting for the downstream response", "request exceeded the response deadline", "downstream operation did not respond in time"]),
        "NETWORK_FAILURE": ([0, 502, 504], ["connection reset before response", "network route to service was unavailable", "connection was interrupted before completion"]),
        "SCHEMA_MISMATCH": ([200, 400, 502], ["response payload did not match the expected schema", "required response field was missing", "service returned an incompatible payload"]),
    }
    generic_messages = [
        "downstream request failed",
        "service could not complete the operation",
        "unexpected response from dependency",
    ]
    services = ["CRM", "OMS", "Inventory", "Payment", "Provisioning", "Logistics", "Notification"]
    endpoints = ["/orders/create", "/inventory/check", "/payment/authorize", "/provision/activate", "/logistics/ship", "/notify/send"]
    rows = []
    for index in range(n):
        label = rng.choice(list(scenarios))
        status_codes, messages = scenarios[label]
        status_code = rng.choice(status_codes)
        response_ms = rng.randint(80, 3200)
        if label == "API_TIMEOUT":
            response_ms = rng.randint(500, 60000)
        elif label == "SERVER_ERROR":
            response_ms = rng.randint(100, 18000)
        elif label == "NETWORK_FAILURE":
            response_ms = rng.randint(5, 8000)
        elif label == "NORMAL":
            response_ms = rng.randint(30, 2500)
        rows.append(
            {
                "sample_id": f"failure_{index:06d}",
                "status_code": status_code,
                "response_ms": response_ms,
                "service": rng.choice(services),
                "endpoint": rng.choice(endpoints),
                "error_message": rng.choice(generic_messages if rng.random() < 0.18 else messages),
                "retry_count": rng.randint(0, 4),
                "label": label,
            }
        )
    return rows


def generate_rejection_dataset(n: int = 9000, seed: int = 43):
    rng = random.Random(seed)
    scenarios = {
        "INVALID_ADDRESS": ([400, 422], "Address Validation", "/orders/address/validate", ["street number is missing", "postal code does not match the selected city", "unsupported apartment address format"]),
        "INVENTORY_ISSUE": ([409, 422], "Inventory", "/inventory/reserve", ["requested item is out of stock", "warehouse reservation capacity reached", "no available stock for selected product"]),
        "PAYMENT_ISSUE": ([402, 409, 422], "Payment", "/payments/authorize", ["payment authorization declined", "payment provider could not confirm authorization", "payment reference requires customer verification"]),
        "DUPLICATE_ORDER": ([409, 422], "Order Management", "/orders/create", ["idempotency key already belongs to an order", "duplicate customer order reference detected", "order request was already accepted"]),
        "BUSINESS_RULE_VIOLATION": ([400, 409, 422], "Order Management", "/orders/validate", ["requested plan is not eligible for this account", "order violates an active contract restriction", "requested product combination is not permitted"]),
    }
    generic_messages = ["order could not be accepted", "request rejected by downstream validation", "order processing stopped after validation"]
    rows = []
    for index in range(n):
        label = rng.choice(list(scenarios))
        status_codes, service, endpoint, messages = scenarios[label]
        status_code = rng.choice(status_codes)
        if rng.random() < 0.12:
            service = rng.choice(["Order Management", "Integration Gateway", "OMS"])
            endpoint = rng.choice(["/orders/process", "/orders/submit", "/workflow/advance"])
        alternative_inventory = int(label == "INVENTORY_ISSUE" and rng.random() < 0.55)
        fixable = int(
            (label == "INVALID_ADDRESS" and rng.random() < 0.82)
            or (label == "INVENTORY_ISSUE" and alternative_inventory == 1)
        )
        rows.append(
            {
                "sample_id": f"rejection_{index:06d}",
                "status_code": status_code + (1 if status_code == 422 and rng.random() < 0.15 else 0),
                "service": service,
                "endpoint": endpoint,
                "rejection_reason": rng.choice(generic_messages if rng.random() < 0.18 else messages),
                "retry_count": rng.randint(0, 3),
                "alternative_inventory_available": alternative_inventory,
                "rejection_type": label,
                "fixable": fixable,
            }
        )
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
