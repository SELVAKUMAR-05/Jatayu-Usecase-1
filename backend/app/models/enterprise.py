"""
Extended database models for enterprise features
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(32), default="operator")
    hashed_password: Mapped[str] = mapped_column(String(256))


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default={})


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(48), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="healthy")
    health_score: Mapped[float] = mapped_column(Float, default=1.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


class ServiceDependency(Base):
    __tablename__ = "service_dependencies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_service: Mapped[str] = mapped_column(String(48))
    to_service: Mapped[str] = mapped_column(String(48))
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class DistributedTrace(Base):
    __tablename__ = "distributed_traces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    order_id: Mapped[str] = mapped_column(String(32), index=True)
    spans: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=[])


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    event_type: Mapped[str] = mapped_column(String(48))
    order_id: Mapped[str | None] = mapped_column(String(32), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default={})
    timestamp: Mapped[datetime]


class MLPrediction(Base):
    __tablename__ = "ml_predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(32), index=True)
    prediction: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default={})
    model_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime]


class RootCauseAnalysis(Base):
    __tablename__ = "root_cause_analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(40), index=True)
    order_id: Mapped[str] = mapped_column(String(32))
    root_cause: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=[])
    confidence: Mapped[float] = mapped_column(Float)
    recommended_recovery: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime]


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(40), unique=True)
    incident_id: Mapped[str | None] = mapped_column(String(40))
    order_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(48))
    risk: Mapped[str] = mapped_column(String(16))
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default={})
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requested_by: Mapped[str] = mapped_column(String(32), default="system")
    decided_by: Mapped[str | None] = mapped_column(String(32))
    decided_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class ResolutionExecution(Base):
    __tablename__ = "resolution_executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(40), unique=True)
    order_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default={})
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    executed_at: Mapped[datetime]


class FeedbackRecord(Base):
    __tablename__ = "feedback_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(40))
    order_id: Mapped[str] = mapped_column(String(32))
    prediction: Mapped[str | None] = mapped_column(String(32))
    actual_action: Mapped[str | None] = mapped_column(String(48))
    recovery_success: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    operator_feedback: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(48))
    version: Mapped[str] = mapped_column(String(32))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default={})
    artifact_path: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    trained_at: Mapped[datetime]


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default={})
    ip_address: Mapped[str | None] = mapped_column(String(64))
    timestamp: Mapped[datetime]


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dlq_id: Mapped[str] = mapped_column(String(40), unique=True)
    event: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    replayed_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class SimulationConfig(Base):
    __tablename__ = "simulation_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(48))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default={})
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime]
