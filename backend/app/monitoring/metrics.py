"""Prometheus metrics endpoint"""
from __future__ import annotations

from fastapi import APIRouter
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

router = APIRouter()

REQUESTS = Counter('orderflow_requests_total', 'Total requests')
FAILURES = Counter('orderflow_failures_total', 'Total failures')
ACTIVE_ORDERS = Gauge('orderflow_active_orders', 'Active orders')
RECOVERED = Counter('orderflow_recovered_total', 'Auto recovered orders')


@router.get("/metrics")
def metrics():
    data = generate_latest()
    return data
