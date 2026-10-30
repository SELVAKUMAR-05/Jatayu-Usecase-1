"""
Resolution engine with policies, retries, circuit breaker, idempotency, DLQ
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.core.utils import new_id, now_utc


class ActionRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Policy:
    name: str
    risk: ActionRisk
    auto_approve: bool
    max_retries: int = 3
    backoff_base: float = 0.5


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout_sec: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout_sec = timeout_sec
        self.failures = 0
        self.opened_at = None
        self.state = "closed"  # closed/open/half_open

    def allow_request(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.opened_at and (time.time() - self.opened_at) > self.timeout_sec:
                self.state = "half_open"
                return True
            return False
        return True

    def record_success(self):
        self.failures = 0
        self.state = "closed"
        self.opened_at = None

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.time()


class ResolutionEngine:
    def __init__(self):
        self.policies = {
            "retry_transient": Policy("retry_transient", ActionRisk.LOW, True, max_retries=5, backoff_base=0.3),
            "refresh_token": Policy("refresh_token", ActionRisk.LOW, True, max_retries=2),
            "throttle": Policy("throttle", ActionRisk.LOW, True),
            "fallback_route": Policy("fallback_route", ActionRisk.MEDIUM, False),
            "address_normalize": Policy("address_normalize", ActionRisk.MEDIUM, False),
            "inventory_reroute": Policy("inventory_reroute", ActionRisk.MEDIUM, False),
            "payment_retry": Policy("payment_retry", ActionRisk.HIGH, False),
            "payment_escalate": Policy("payment_escalate", ActionRisk.HIGH, False),
            "manual_review": Policy("manual_review", ActionRisk.HIGH, False),
        }
        self.breakers: dict[str, CircuitBreaker] = {}
        self.idempotency: dict[str, dict[str, Any]] = {}
        self.dlq: list[dict[str, Any]] = {}
        self.executions = []

    def get_breaker(self, service: str) -> CircuitBreaker:
        if service not in self.breakers:
            self.breakers[service] = CircuitBreaker()
        return self.breakers[service]

    def retry_with_backoff(self, fn, policy: Policy, *args, **kwargs):
        last_err = None
        for i in range(policy.max_retries):
            try:
                res = fn(*args, **kwargs)
                return {"ok": True, "result": res, "attempts": i + 1}
            except Exception as e:
                last_err = e
                if i < policy.max_retries - 1:
                    time.sleep(policy.backoff_base * (2 ** i) + random.uniform(0, 0.1))
        return {"ok": False, "error": str(last_err), "attempts": policy.max_retries}

    def execute(self, action: str, context: dict[str, Any]) -> dict[str, Any]:
        pol = self.policies.get(action)
        if not pol:
            return {"ok": False, "error": "unknown_action"}
        if not pol.auto_approve and pol.risk != ActionRisk.LOW:
            req_id = new_id("apr_")
            return {"ok": False, "status": "pending_approval", "approval_id": req_id, "action": action, "risk": pol.risk.value, "context": context}
        exec_id = new_id("rex_")
        res = {"ok": True, "execution_id": exec_id, "action": action, "risk": pol.risk.value, "status": "executed", "timestamp": now_utc().isoformat()}
        self.executions.append(res)
        return res

    def send_to_dlq(self, event: dict[str, Any], reason: str):
        item = {"dlq_id": new_id("dlq_"), "event": event, "reason": reason, "retries": 0, "status": "pending", "timestamp": now_utc().isoformat()}
        self.dlq.append(item)
        return item


resolution_engine = ResolutionEngine()
