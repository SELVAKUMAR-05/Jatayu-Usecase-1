from __future__ import annotations

import asyncio
import json
import os
import random
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./orderflow.db")
engine_options: dict[str, Any] = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=engine_options, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(32))
    order_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(48))
    priority: Mapped[str] = mapped_column(String(16))
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(32), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    value: Mapped[float] = mapped_column(Float, default=129.99)
    correlation_id: Mapped[str] = mapped_column(String(48))


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(32))
    service: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    cause: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiRequest(Base):
    __tablename__ = "api_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), index=True)
    order_id: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(48))
    destination: Mapped[str] = mapped_column(String(48))
    endpoint: Mapped[str] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(8), default="POST")
    status_code: Mapped[int] = mapped_column(Integer)
    response_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Event(Base):
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(Text)
    service: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    order_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80))
    previous_state: Mapped[str] = mapped_column(Text, default="")
    new_state: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="success")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class SimulationState(Base):
    __tablename__ = "simulation_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    injected_service: Mapped[str | None] = mapped_column(String(48), nullable=True)
    injected_category: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, socket: WebSocket) -> None:
        await socket.accept()
        self.connections.add(socket)

    def disconnect(self, socket: WebSocket) -> None:
        self.connections.discard(socket)

    async def broadcast(self, data: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for socket in list(self.connections):
            try:
                await socket.send_json(data)
            except Exception:
                stale.append(socket)
        for socket in stale:
            self.disconnect(socket)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_database()
    global simulation_task
    simulation_task = asyncio.create_task(simulation_loop())
    try:
        yield
    finally:
        if simulation_task:
            simulation_task.cancel()
            try:
                await simulation_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="AstraX API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = ConnectionManager()
simulation_task: asyncio.Task | None = None
randomizer = random.Random()

SERVICES = [
    "Order Management", "Inventory", "Payment", "Provisioning",
    "Logistics", "Notification",
]
STAGES = ["Validation", "Inventory", "Payment", "Provisioning", "Logistics", "Completed"]
FAILURES = {
    "API_ERROR": ("Provisioning", 504, "Downstream activation gateway timed out"),
    "ORDER_DELAY": ("Logistics", 503, "Carrier callback exceeded the 30-minute SLA"),
    "ORDER_REJECTION": ("Inventory", 422, "Requested item is unavailable at the primary warehouse"),
}
SERVICE_HEALTH: dict[str, str] = {service: "healthy" for service in SERVICES}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def audit(db: Session, action: str, order_id: str | None = None, previous: str = "", new: str = "",
          result: str = "success", actor: str = "system") -> None:
    db.add(AuditLog(event_id=f"AUD-{secrets.token_hex(5).upper()}", order_id=order_id, actor=actor,
                    action=action, previous_state=previous, new_state=new, result=result))


def record_event(db: Session, order: Order, stage: str, message: str, service: str, status: str) -> None:
    db.add(Event(order_id=order.order_id, stage=stage, message=message, service=service, status=status))


def serialize_order(order: Order) -> dict[str, Any]:
    return {
        "order_id": order.order_id, "customer_id": order.customer_id, "order_type": order.order_type,
        "status": order.status, "stage": order.stage, "priority": order.priority,
        "failure_reason": order.failure_reason, "resolution_status": order.resolution_status,
        "created_at": order.created_at.isoformat(), "completed_at": order.completed_at.isoformat() if order.completed_at else None,
        "value": order.value, "correlation_id": order.correlation_id,
    }


def serialize_incident(incident: Incident) -> dict[str, Any]:
    return {
        "incident_id": incident.incident_id, "order_id": incident.order_id, "category": incident.category,
        "service": incident.service, "severity": incident.severity, "status": incident.status,
        "cause": incident.cause, "recommendation": incident.recommendation,
        "evidence": json.loads(incident.evidence), "confidence": incident.confidence,
        "created_at": incident.created_at.isoformat(),
    }


def detect(category: str, status_code: int, elapsed_ms: int, threshold_ms: int = 30000) -> tuple[bool, str]:
    if category == "API_ERROR":
        return status_code >= 400, "HTTP response indicates an API failure" if status_code >= 400 else "Normal response"
    if category == "ORDER_DELAY":
        return elapsed_ms > threshold_ms, "Stage duration exceeded configured SLA" if elapsed_ms > threshold_ms else "Within SLA"
    if category == "ORDER_REJECTION":
        return status_code in (400, 409, 422), "Business validation rejected the order" if status_code in (400, 409, 422) else "Accepted"
    return False, "Unclassified event"


def analyze(category: str, service: str, status_code: int, response_ms: int, reason: str) -> tuple[str, str, list[str], float]:
    if category == "API_ERROR":
        cause = f"{service} returned HTTP {status_code}; the dependency did not complete within its response window."
        recommendation = "Retry with bounded exponential backoff and the same idempotency key; escalate after three attempts."
        evidence = [f"HTTP {status_code} response recorded", f"Response time: {response_ms} ms", reason, "Order and request correlation IDs match"]
        confidence = 0.91
    elif category == "ORDER_DELAY":
        cause = f"{service} processing exceeded the configured stage SLA, indicating a queue or downstream latency bottleneck."
        recommendation = "Inspect the service queue and route through an available healthy processing path."
        evidence = [f"Observed stage duration: {response_ms} ms", "Duration exceeded the configured SLA", reason]
        confidence = 0.86
    else:
        cause = f"{service} rejected the order during deterministic business validation."
        recommendation = "Review the evidence and correct source data or reserve stock only with operator approval."
        evidence = [f"Validation returned HTTP {status_code}", reason, "No payment or irreversible action was retried"]
        confidence = 0.96
    return cause, recommendation, evidence, confidence


def create_order(db: Session, forced_category: str | None = None, forced_service: str | None = None) -> Order:
    number = int(time.time() * 1000) % 100000000
    order_id = f"ORD-{number:08d}-{randomizer.randint(10, 99)}"
    category = forced_category or (randomizer.choices(["NORMAL", *FAILURES.keys()], weights=[0.78, 0.1, 0.07, 0.05])[0])
    service, failure_code, reason = FAILURES.get(category, ("", 200, ""))
    service = forced_service or service
    if category == "NORMAL":
        service, failure_code, reason = "Order Management", 200, ""
    order = Order(
        order_id=order_id, customer_id=f"CUS-{randomizer.randint(10000, 99999)}",
        order_type=randomizer.choice(["New subscription", "Device upgrade", "Service add-on"]),
        status="Processing", stage="Validation", priority=randomizer.choice(["Standard", "High", "Critical"]),
        correlation_id=f"cor-{secrets.token_hex(8)}", value=round(randomizer.uniform(49.99, 899.99), 2),
    )
    db.add(order)
    db.flush()
    record_event(db, order, "Validation", "Order accepted by the validation service", "Order Management", "success")

    if category == "NORMAL":
        for stage, service_name in zip(STAGES[1:], SERVICES[1:]):
            order.stage = stage
            record_event(db, order, stage, f"{stage} stage completed successfully", service_name, "success")
        order.status, order.stage, order.completed_at = "Completed", "Completed", now()
        audit(db, "order.completed", order.order_id, "Processing", "Completed")
    else:
        order.stage = service
        order.status = "Delayed" if category == "ORDER_DELAY" else ("Rejected" if category == "ORDER_REJECTION" else "Failed")
        order.failure_reason = reason
        record_event(db, order, service, reason, service, "failure")
        response_ms = randomizer.randint(32000, 55000) if category == "ORDER_DELAY" else randomizer.randint(1400, 48000)
        detected, _ = detect(category, failure_code, response_ms)
        db.add(ApiRequest(request_id=f"REQ-{secrets.token_hex(5).upper()}", order_id=order_id,
                          source="Order Management", destination=service, endpoint=f"/{service.lower().replace(' ', '-')}/process",
                          method="POST", status_code=failure_code, response_ms=response_ms, error=reason))
        if detected:
            cause, recommendation, evidence, confidence = analyze(category, service, failure_code, response_ms, reason)
            incident = Incident(incident_id=f"INC-{secrets.token_hex(5).upper()}", order_id=order_id,
                                category=category, service=service,
                                severity="critical" if category == "API_ERROR" and failure_code >= 500 else "high",
                                status="pending_approval" if category != "API_ERROR" else "open",
                                cause=cause, recommendation=recommendation, evidence=json.dumps(evidence),
                                confidence=confidence)
            db.add(incident)
            order.resolution_status = "approval_required" if category != "API_ERROR" else "retrying"
            audit(db, "failure.detected", order_id, "Processing", order.status)
            audit(db, "root_cause.analyzed", order_id, "", cause)
            if category == "API_ERROR":
                # Demonstration uses a deterministic successful retry, with an explicit bounded attempt.
                db.add(ApiRequest(request_id=f"REQ-{secrets.token_hex(5).upper()}", order_id=order_id,
                                  source="Order Management", destination=service,
                                  endpoint=f"/{service.lower().replace(' ', '-')}/process",
                                  method="POST", status_code=200, response_ms=randomizer.randint(180, 900),
                                  retry_count=1))
                order.status, order.stage, order.resolution_status = "Completed", "Completed", "auto_recovered"
                order.completed_at = now()
                record_event(db, order, "Recovery", "Bounded retry succeeded using the original idempotency key", service, "recovered")
                incident.status, incident.resolved_at = "resolved", now()
                audit(db, "resolution.auto_retry", order_id, "Failed", "Completed")
    audit(db, "simulation.order_generated", order.order_id, "", order.status)
    db.commit()
    db.refresh(order)
    return order


def ensure_database() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.get(SimulationState, 1) is None:
            db.add(SimulationState(id=1, running=False))
            db.commit()
        if db.scalar(select(Order.id).limit(1)) is None:
            for category in ("NORMAL", "NORMAL", "NORMAL", "API_ERROR", "ORDER_DELAY", "ORDER_REJECTION"):
                create_order(db, category)


async def simulation_loop() -> None:
    while True:
        await asyncio.sleep(7)
        with SessionLocal() as db:
            state = db.get(SimulationState, 1)
            if state and state.running:
                order = create_order(db, state.injected_category, state.injected_service)
                state.injected_category, state.injected_service = None, None
                db.commit()
                await manager.broadcast({"type": "order.created", "order": serialize_order(order)})
                await manager.broadcast({"type": "dashboard.updated"})


class GenerateRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=50)


class OrderCreateRequest(BaseModel):
    order_type: str = Field(default="New subscription", min_length=3, max_length=40)
    priority: str = Field(default="Standard", pattern="^(Standard|High|Critical)$")


class InjectRequest(BaseModel):
    category: str = Field(pattern="^(API_ERROR|ORDER_DELAY|ORDER_REJECTION)$")
    service: str = Field(min_length=2, max_length=48)


class ActionRequest(BaseModel):
    feedback: str | None = Field(default=None, max_length=500)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "AstraX"}


@app.get("/api/dashboard/overview")
def dashboard_overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    orders = list(db.scalars(select(Order)).all())
    incidents = list(db.scalars(select(Incident)).all())
    requests = list(db.scalars(select(ApiRequest)).all())
    total = len(orders)
    completed = sum(order.status == "Completed" for order in orders)
    failed = sum(order.status in ("Failed", "Rejected") for order in orders)
    delayed = sum(order.status == "Delayed" for order in orders)
    open_incidents = sum(incident.status in ("open", "pending_approval", "escalated") for incident in incidents)
    api_errors = sum(request.status_code >= 400 for request in requests)
    error_rate = round(100 * api_errors / max(len(requests), 1), 1)
    history: list[dict[str, Any]] = []
    for offset in range(6, -1, -1):
        day = (now() - timedelta(days=offset)).date()
        day_orders = [order for order in orders if order.created_at.date() == day]
        history.append({"label": day.strftime("%a"), "success": sum(o.status == "Completed" for o in day_orders),
                        "failed": sum(o.status in ("Failed", "Rejected") for o in day_orders),
                        "delayed": sum(o.status == "Delayed" for o in day_orders)})
    recent = db.scalars(select(Incident).order_by(Incident.created_at.desc()).limit(6)).all()
    return {
        "metrics": {"total_orders": total, "completed_orders": completed, "failed_orders": failed,
                    "delayed_orders": delayed, "rejected_orders": sum(o.status == "Rejected" for o in orders),
                    "api_error_rate": error_rate, "auto_recovered": sum(i.status == "resolved" and i.category == "API_ERROR" for i in incidents),
                    "pending_approvals": sum(i.status == "pending_approval" for i in incidents),
                    "success_rate": round(100 * completed / max(total, 1), 1)},
        "processing_overview": history,
        "failure_distribution": [
            {"name": "API errors", "value": sum(i.category == "API_ERROR" for i in incidents), "color": "#67e8f9"},
            {"name": "Order delays", "value": sum(i.category == "ORDER_DELAY" for i in incidents), "color": "#818cf8"},
            {"name": "Order rejections", "value": sum(i.category == "ORDER_REJECTION" for i in incidents), "color": "#f472b6"},
        ],
        "service_health": [{"name": service, "status": SERVICE_HEALTH.get(service, "healthy"),
                            "latency": randomizer.randint(42, 320), "uptime": round(randomizer.uniform(98.8, 99.99), 2)}
                           for service in SERVICES],
        "recent_incidents": [serialize_incident(i) for i in recent],
    }


@app.get("/api/dashboard/failure-distribution")
def failure_distribution(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return dashboard_overview(db)["failure_distribution"]


@app.get("/api/dashboard/service-health")
def service_health() -> list[dict[str, Any]]:
    return [{"name": name, "status": status} for name, status in SERVICE_HEALTH.items()]


@app.get("/api/orders")
def list_orders(status: str | None = None, search: str | None = None, limit: int = Query(100, ge=1, le=500),
                offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> dict[str, Any]:
    query = select(Order).order_by(Order.created_at.desc())
    if status:
        query = query.where(Order.status == status)
    if search:
        query = query.where(Order.order_id.ilike(f"%{search}%"))
    orders = db.scalars(query.offset(offset).limit(limit)).all()
    return {"items": [serialize_order(o) for o in orders], "limit": limit, "offset": offset}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = db.scalar(select(Order).where(Order.order_id == order_id))
    if order is None:
        raise HTTPException(404, "Order not found")
    return serialize_order(order)


@app.post("/api/orders", status_code=201)
async def create_order_endpoint(payload: OrderCreateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    order = create_order(db, "NORMAL")
    order.order_type, order.priority = payload.order_type, payload.priority
    db.commit()
    await manager.broadcast({"type": "order.created", "order": serialize_order(order)})
    await manager.broadcast({"type": "dashboard.updated"})
    return serialize_order(order)


@app.get("/api/orders/{order_id}/timeline")
def order_timeline(order_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    if db.scalar(select(Order.id).where(Order.order_id == order_id)) is None:
        raise HTTPException(404, "Order not found")
    events = db.scalars(select(Event).where(Event.order_id == order_id).order_by(Event.created_at)).all()
    return [{"stage": e.stage, "message": e.message, "service": e.service, "status": e.status,
             "timestamp": e.created_at.isoformat()} for e in events]


@app.get("/api/monitoring/incidents")
def list_incidents(status: str | None = None, limit: int = Query(100, ge=1, le=500),
                   db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    query = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if status:
        query = select(Incident).where(Incident.status == status).order_by(Incident.created_at.desc()).limit(limit)
    return [serialize_incident(i) for i in db.scalars(query).all()]


@app.get("/api/monitoring/api-logs")
def api_logs(order_id: str | None = None, limit: int = Query(100, ge=1, le=500),
             db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    query = select(ApiRequest).order_by(ApiRequest.created_at.desc()).limit(limit)
    if order_id:
        query = select(ApiRequest).where(ApiRequest.order_id == order_id).order_by(ApiRequest.created_at.desc()).limit(limit)
    return [{"request_id": r.request_id, "order_id": r.order_id, "source": r.source, "destination": r.destination,
             "endpoint": r.endpoint, "method": r.method, "status_code": r.status_code, "response_ms": r.response_ms,
             "error": r.error, "retry_count": r.retry_count, "timestamp": r.created_at.isoformat()}
            for r in db.scalars(query).all()]


@app.get("/api/monitoring/services")
def monitoring_services() -> list[dict[str, Any]]:
    return [{"name": name, "status": status, "latency": randomizer.randint(42, 320)} for name, status in SERVICE_HEALTH.items()]


@app.post("/api/simulation/start")
async def simulation_start(db: Session = Depends(get_db)) -> dict[str, Any]:
    state = db.get(SimulationState, 1)
    state.running = True
    audit(db, "simulation.started", new="running")
    db.commit()
    await manager.broadcast({"type": "simulation.status", "running": True})
    return {"running": True}


@app.post("/api/simulation/pause")
async def simulation_pause(db: Session = Depends(get_db)) -> dict[str, Any]:
    state = db.get(SimulationState, 1)
    state.running = False
    audit(db, "simulation.paused", new="paused")
    db.commit()
    await manager.broadcast({"type": "simulation.status", "running": False})
    return {"running": False}


@app.post("/api/simulation/stop")
async def simulation_stop(db: Session = Depends(get_db)) -> dict[str, Any]:
    return await simulation_pause(db)


@app.post("/api/simulation/generate")
async def simulation_generate(payload: GenerateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    orders = [create_order(db) for _ in range(payload.count)]
    await manager.broadcast({"type": "simulation.batch", "count": len(orders)})
    await manager.broadcast({"type": "dashboard.updated"})
    return {"generated": len(orders), "orders": [serialize_order(o) for o in orders]}


@app.post("/api/simulation/inject-failure")
async def inject_failure(payload: InjectRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.service not in SERVICES:
        raise HTTPException(400, "Unknown service")
    order = create_order(db, payload.category, payload.service)
    await manager.broadcast({"type": "incident.created", "order_id": order.order_id})
    await manager.broadcast({"type": "dashboard.updated"})
    return {"order": serialize_order(order)}


@app.get("/api/simulation/status")
def simulation_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    state = db.get(SimulationState, 1)
    return {"running": bool(state and state.running), "interval_seconds": 7,
            "services": SERVICES, "injected_failure": state.injected_category if state else None}


def resolve_incident(db: Session, incident: Incident, approved: bool, action: str) -> dict[str, Any]:
    if incident.status not in ("open", "pending_approval", "escalated"):
        raise HTTPException(409, f"Incident is already {incident.status}")
    order = db.scalar(select(Order).where(Order.order_id == incident.order_id))
    if order is None:
        raise HTTPException(404, "Associated order not found")
    if incident.category != "API_ERROR" and not approved:
        raise HTTPException(403, "This business action requires operator approval")
    previous = order.status
    if incident.category == "API_ERROR" and action in ("approve", "retry"):
        # A retry is bounded and uses a stable synthetic idempotency key (the order correlation ID).
        db.add(ApiRequest(request_id=f"REQ-{secrets.token_hex(5).upper()}", order_id=order.order_id,
                          source="Order Management", destination=incident.service,
                          endpoint=f"/{incident.service.lower().replace(' ', '-')}/process",
                          method="POST", status_code=200, response_ms=randomizer.randint(170, 950), retry_count=1))
        order.status, order.stage, order.resolution_status = "Completed", "Completed", "recovered"
        order.completed_at, incident.status, incident.resolved_at = now(), "resolved", now()
        record_event(db, order, "Recovery", "Operator-approved bounded retry succeeded", incident.service, "recovered")
    elif approved:
        order.status, order.stage, order.resolution_status = "Completed", "Completed", "approved_recovery"
        order.completed_at, incident.status, incident.resolved_at = now(), "resolved", now()
        record_event(db, order, "Recovery", f"Operator approved {action}; simulation recovered order", incident.service, "recovered")
    elif action == "reject":
        incident.status, order.resolution_status = "rejected", "operator_rejected"
        record_event(db, order, "Operator review", "Recommended action rejected by operator", incident.service, "review")
    elif action == "escalate":
        incident.status = "escalated"
        record_event(db, order, "Escalation", "Incident escalated for specialist review", incident.service, "escalated")
    audit(db, f"resolution.{action}", order.order_id, previous,
          f"{order.status} / {incident.status}", actor="operator")
    db.commit()
    return {"incident": serialize_incident(incident), "order": serialize_order(order)}


@app.post("/api/resolutions/{incident_id}/approve")
async def approve_resolution(incident_id: str, payload: ActionRequest | None = None,
                             db: Session = Depends(get_db)) -> dict[str, Any]:
    incident = db.scalar(select(Incident).where(Incident.incident_id == incident_id))
    if incident is None:
        raise HTTPException(404, "Incident not found")
    result = resolve_incident(db, incident, True, "approve")
    await manager.broadcast({"type": "incident.updated", "incident_id": incident_id})
    await manager.broadcast({"type": "dashboard.updated"})
    return result


@app.post("/api/resolutions/{incident_id}/reject")
async def reject_resolution(incident_id: str, payload: ActionRequest | None = None,
                            db: Session = Depends(get_db)) -> dict[str, Any]:
    incident = db.scalar(select(Incident).where(Incident.incident_id == incident_id))
    if incident is None:
        raise HTTPException(404, "Incident not found")
    result = resolve_incident(db, incident, False, "reject")
    return result


@app.post("/api/resolutions/{incident_id}/retry")
async def retry_resolution(incident_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    incident = db.scalar(select(Incident).where(Incident.incident_id == incident_id))
    if incident is None:
        raise HTTPException(404, "Incident not found")
    result = resolve_incident(db, incident, incident.category == "API_ERROR", "retry")
    await manager.broadcast({"type": "dashboard.updated"})
    return result


@app.post("/api/resolutions/{incident_id}/escalate")
async def escalate_resolution(incident_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    incident = db.scalar(select(Incident).where(Incident.incident_id == incident_id))
    if incident is None:
        raise HTTPException(404, "Incident not found")
    return resolve_incident(db, incident, False, "escalate")


@app.get("/api/resolutions")
def resolutions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    incidents = db.scalars(select(Incident).where(Incident.status.in_(("open", "pending_approval", "escalated")))
                           .order_by(Incident.created_at.desc())).all()
    return [serialize_incident(i) for i in incidents]


@app.get("/api/ai/root-cause/{incident_id}")
def root_cause(incident_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    incident = db.scalar(select(Incident).where(Incident.incident_id == incident_id))
    if incident is None:
        raise HTTPException(404, "Incident not found")
    return serialize_incident(incident)


@app.post("/api/ai/analyze/{order_id}")
def analyze_order(order_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    incident = db.scalar(select(Incident).where(Incident.order_id == order_id).order_by(Incident.created_at.desc()))
    if incident is None:
        raise HTTPException(404, "No failure evidence available for this order")
    return serialize_incident(incident)


@app.get("/api/analytics/overview")
def analytics_overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    data = dashboard_overview(db)
    orders = list(db.scalars(select(Order)).all())
    incidents = list(db.scalars(select(Incident)).all())
    requests = list(db.scalars(select(ApiRequest)).all())
    resolved = [i for i in incidents if i.status == "resolved"]
    recoveries = [o for o in orders if o.resolution_status in ("auto_recovered", "recovered", "approved_recovery")]
    durations = [(i.resolved_at - i.created_at).total_seconds() for i in resolved if i.resolved_at]
    return {
        **data["metrics"],
        "completion_percentage": data["metrics"]["success_rate"],
        "rejection_percentage": round(100 * data["metrics"]["rejected_orders"] / max(len(orders), 1), 1),
        "api_failure_percentage": data["metrics"]["api_error_rate"],
        "manual_interventions": sum(i.status == "resolved" and i.category != "API_ERROR" for i in incidents),
        "mttd_seconds": 1.8 if incidents else 0,
        "mttr_seconds": round(sum(durations) / len(durations), 1) if durations else 0,
        "sla_compliance": round(100 * sum(o.status == "Completed" for o in orders) / max(len(orders), 1), 1),
        "estimated_recovered_value": round(sum(o.value for o in recoveries), 2),
        "api_requests": len(requests),
    }


@app.get("/api/analytics/recovery")
def analytics_recovery(db: Session = Depends(get_db)) -> dict[str, Any]:
    incidents = list(db.scalars(select(Incident)).all())
    total = len(incidents)
    resolved = sum(i.status == "resolved" for i in incidents)
    common = max((i.category for i in incidents), key=lambda category: sum(x.category == category for x in incidents)) if incidents else "none"
    return {"successful_recoveries": resolved, "failed_recoveries": total - resolved,
            "success_rate": round(100 * resolved / max(total, 1), 1), "most_common_failure": common,
            "most_successful_resolution": "Bounded retry with idempotency" if resolved else "No recovery data",
            "average_recovery_seconds": analytics_overview(db)["mttr_seconds"]}


@app.get("/api/analytics/sla")
def analytics_sla(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"compliance_percentage": analytics_overview(db)["sla_compliance"], "target_percentage": 99.0}


@app.get("/api/audit-logs")
def audit_logs(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return [{"event_id": a.event_id, "order_id": a.order_id, "actor": a.actor, "action": a.action,
             "previous_state": a.previous_state, "new_state": a.new_state, "result": a.result,
             "timestamp": a.created_at.isoformat()} for a in rows]


@app.get("/api/orders.csv")
def orders_csv(db: Session = Depends(get_db)):
    from fastapi.responses import Response
    lines = ["order_id,customer_id,status,stage,priority,value,created_at"]
    for order in db.scalars(select(Order).order_by(Order.created_at.desc())).all():
        lines.append(",".join([order.order_id, order.customer_id, order.status, order.stage, order.priority,
                               f"{order.value:.2f}", order.created_at.isoformat()]))
    return Response("\n".join(lines), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=orderflow-orders.csv"})


@app.websocket("/ws")
async def websocket_endpoint(socket: WebSocket) -> None:
    await manager.connect(socket)
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(socket)
