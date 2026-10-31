"""API routers for new enterprise endpoints"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.inference import (
    delay_prediction_service,
    failure_classifier,
    ml_service,
    rejection_classifier,
)
from app.root_cause.agent import rca_agent
from app.resolution.engine import resolution_engine
from app.telemetry.collector import telemetry
router = APIRouter(prefix="/api/v2", tags=["enterprise"])


class DelayPredictionRequest(BaseModel):
    processing_duration_ms: float = Field(ge=0, allow_inf_nan=False)
    current_stage: str = Field(min_length=1, max_length=32)
    queue_depth: float = Field(ge=0, allow_inf_nan=False)
    service_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    previous_stage_duration_ms: float = Field(ge=0, allow_inf_nan=False)
    historical_service_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    sla_utilization: float = Field(ge=0, le=1.5, allow_inf_nan=False)


class FailurePredictionRequest(BaseModel):
    status_code: int = Field(ge=0, le=599)
    response_ms: float = Field(ge=0, allow_inf_nan=False)
    service: str = Field(min_length=1, max_length=48)
    endpoint: str = Field(min_length=1, max_length=120)
    error_message: str = Field(default="", max_length=1000)
    retry_count: int = Field(default=0, ge=0, le=20)
    order_id: str | None = Field(default=None, max_length=32)


class RejectionPredictionRequest(BaseModel):
    status_code: int = Field(ge=400, le=599)
    service: str = Field(min_length=1, max_length=48)
    endpoint: str = Field(min_length=1, max_length=120)
    rejection_reason: str = Field(min_length=3, max_length=1000)
    retry_count: int = Field(default=0, ge=0, le=20)
    alternative_inventory_available: bool = False
    order_id: str | None = Field(default=None, max_length=32)


class FeedbackRequest(BaseModel):
    prediction_id: int = Field(gt=0)
    actual_label: str = Field(min_length=1, max_length=48)
    prediction_correct: bool
    actor: str = Field(default="operator", min_length=1, max_length=40)


def get_db():
    from app.main import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/ml/metrics")
def ml_metrics():
    return {
        "ok": failure_classifier.loaded and rejection_classifier.loaded and delay_prediction_service.loaded,
        "models": {
            "legacy_failure_classifier": getattr(ml_service, "metrics", {}),
            "api_failure_classifier": getattr(failure_classifier, "metrics", {}),
            "order_rejection_classifier": getattr(rejection_classifier, "metrics", {}),
            "delay_prediction": getattr(delay_prediction_service, "metrics", {}),
        },
        "model_availability": {
            "api_failure_classifier": failure_classifier.loaded,
            "order_rejection_classifier": rejection_classifier.loaded,
            "delay_prediction": delay_prediction_service.loaded,
        },
    }


@router.post("/ml/predict")
def ml_predict(payload: FailurePredictionRequest, db: Session = Depends(get_db)):
    from app.main import MLPredictionRecord, Order, persist_ml_prediction

    features = payload.model_dump(exclude={"order_id"})
    result = failure_classifier.predict(features)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)
    if payload.order_id and db.scalar(select(Order.id).where(Order.order_id == payload.order_id)) is None:
        raise HTTPException(status_code=404, detail="Order not found")
    record = persist_ml_prediction(
        db, payload.order_id, None, "api_failure", result,
        {key: value for key, value in features.items() if key != "error_message"},
    )
    db.flush()
    db.commit()
    result["prediction_id"] = record.id if record else None
    return result


@router.post("/ml/rejections/predict")
def ml_rejection_predict(payload: RejectionPredictionRequest, db: Session = Depends(get_db)):
    from app.main import Order, persist_ml_prediction

    features = payload.model_dump(exclude={"order_id"})
    result = rejection_classifier.predict(features)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)
    if payload.order_id and db.scalar(select(Order.id).where(Order.order_id == payload.order_id)) is None:
        raise HTTPException(status_code=404, detail="Order not found")
    record = persist_ml_prediction(
        db, payload.order_id, None, "order_rejection", result,
        {key: value for key, value in features.items() if key != "rejection_reason"},
    )
    db.flush()
    db.commit()
    result["prediction_id"] = record.id if record else None
    return result


@router.get("/ml/predictions/recent")
def ml_recent_predictions(limit: int = 50, db: Session = Depends(get_db)):
    from app.main import MLPredictionRecord

    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    records = db.scalars(
        select(MLPredictionRecord).order_by(MLPredictionRecord.created_at.desc()).limit(limit)
    ).all()
    return {
        "predictions": [
            {
                "prediction_id": item.id,
                "order_id": item.order_id,
                "incident_id": item.incident_id,
                "task": item.task,
                "prediction": item.prediction,
                "confidence": item.confidence,
                "probabilities": json.loads(item.probabilities),
                "model_name": item.model_name,
                "model_version": item.model_version,
                "features": json.loads(item.safe_features),
                "created_at": item.created_at.isoformat(),
            }
            for item in records
        ]
    }


@router.post("/ml/feedback")
def ml_submit_feedback(payload: FeedbackRequest, db: Session = Depends(get_db)):
    from app.main import AuditLog, MLFeedbackRecord, MLPredictionRecord

    prediction = db.get(MLPredictionRecord, payload.prediction_id)
    if prediction is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    feedback = MLFeedbackRecord(
        prediction_id=prediction.id,
        actual_label=payload.actual_label,
        prediction_correct=payload.prediction_correct,
        actor=payload.actor,
    )
    db.add(feedback)
    db.add(
        AuditLog(
            event_id=f"AUD-{secrets.token_hex(5).upper()}",
            order_id=prediction.order_id,
            actor=payload.actor,
            action="ml.feedback.submitted",
            previous_state=prediction.prediction,
            new_state=payload.actual_label,
            result="success",
        )
    )
    db.commit()
    db.refresh(feedback)
    return {"ok": True, "feedback_id": feedback.id, "training_effect": "stored_for_future_review"}


@router.post("/ml/anomaly")
def ml_anomaly(features: dict):
    return ml_service.anomaly_score(features)


@router.post("/ml/delay-predict")
def ml_delay_predict(payload: DelayPredictionRequest):
    result = delay_prediction_service.predict(payload.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)
    return result


@router.post("/ml/orders/{order_id}/delay-predict")
def ml_order_delay_predict(order_id: str, db: Session = Depends(get_db)):
    from app.main import (
        ApiRequest,
        Event,
        MLPredictionRecord,
        Order,
        audit,
        persist_ml_prediction,
    )

    order = db.scalar(select(Order).where(Order.order_id == order_id))
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status == "Completed":
        raise HTTPException(status_code=409, detail="Delay prediction is only available for active or delayed orders")

    stage_map = {
        "Validation": "VALIDATING",
        "Inventory": "INVENTORY",
        "Payment": "PAYMENT",
        "Provisioning": "PROVISIONING",
        "Logistics": "LOGISTICS",
    }
    model_stage = stage_map.get(order.stage)
    if model_stage is None:
        raise HTTPException(status_code=422, detail=f"Unsupported current order stage: {order.stage}")

    current_time = datetime.now(timezone.utc)
    created_at = order.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    elapsed_ms = max(0, int((current_time - created_at).total_seconds() * 1000))
    events = db.scalars(
        select(Event).where(Event.order_id == order_id).order_by(Event.created_at.asc())
    ).all()
    stage_events = [event for event in events if event.stage == order.stage]
    previous_stage_duration_ms = 0
    if len(events) >= 2:
        current_event_time = stage_events[-1].created_at if stage_events else events[-1].created_at
        previous_event_time = next(
            (event.created_at for event in reversed(events[:-1]) if event.stage != order.stage),
            events[-2].created_at,
        )
        if current_event_time.tzinfo is None:
            current_event_time = current_event_time.replace(tzinfo=timezone.utc)
        if previous_event_time.tzinfo is None:
            previous_event_time = previous_event_time.replace(tzinfo=timezone.utc)
        previous_stage_duration_ms = max(
            0, int((current_event_time - previous_event_time).total_seconds() * 1000)
        )

    service_requests = db.scalars(
        select(ApiRequest)
        .where(ApiRequest.destination == order.stage)
        .order_by(ApiRequest.created_at.desc())
        .limit(50)
    ).all()
    service_latency_ms = service_requests[0].response_ms if service_requests else 0
    historical_service_latency_ms = (
        sum(request.response_ms for request in service_requests) / len(service_requests)
        if service_requests else service_latency_ms
    )
    active_orders = db.scalars(
        select(Order).where(
            Order.stage == order.stage,
            Order.status.in_(("Processing", "Delayed", "Failed")),
        )
    ).all()
    sla_deadline_ms = int(getattr(order, "sla_deadline_ms", delay_prediction_service.artifact.get("sla_deadline_ms", 30000)))
    features = {
        "processing_duration_ms": elapsed_ms,
        "current_stage": model_stage,
        "queue_depth": max(0, len(active_orders) - 1),
        "service_latency_ms": service_latency_ms,
        "previous_stage_duration_ms": previous_stage_duration_ms,
        "historical_service_latency_ms": historical_service_latency_ms,
        "sla_utilization": elapsed_ms / max(sla_deadline_ms, 1),
    }
    result = delay_prediction_service.predict(features)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)

    prediction = persist_ml_prediction(db, order_id, None, "delay", result, features)
    recent_candidate = db.scalar(
        select(Event.id).where(
            Event.order_id == order_id,
            Event.stage == "Delay Prediction",
            Event.created_at >= current_time - timedelta(minutes=5),
        ).limit(1)
    )
    alert_recorded = False
    if result["alert_candidate"] and recent_candidate is None:
        db.add(
            Event(
                order_id=order_id,
                stage="Delay Prediction",
                message=(
                    f"Model flagged SLA breach candidate at {result['sla_breach_probability']:.1%} "
                    f"probability; operator review required."
                ),
                service=order.stage,
                status="warning",
            )
        )
        audit(db, "delay.prediction.candidate", order_id, order.status, "operator_review")
        alert_recorded = True
    db.flush()
    db.commit()
    result.update(
        {
            "order_id": order_id,
            "prediction_id": prediction.id if prediction else None,
            "input_source": "persisted order, lifecycle events, and API requests",
            "sla_deadline_ms": sla_deadline_ms,
            "alert_recorded": alert_recorded,
        }
    )
    return result


@router.post("/rca/analyze")
def rca_analyze(payload: dict):
    return rca_agent.analyze(payload.get("incident", {}), payload.get("traces"), payload.get("logs"), payload.get("similar"))


@router.get("/rca/incidents/{incident_id}")
def rca_analyze_persisted_incident(incident_id: str, db: Session = Depends(get_db)):
    from app.main import ApiRequest, Event, Incident, MLPredictionRecord

    incident = db.scalar(select(Incident).where(Incident.incident_id == incident_id))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    current_logs = db.scalars(
        select(ApiRequest).where(ApiRequest.order_id == incident.order_id)
        .order_by(ApiRequest.created_at.asc())
    ).all()
    related_logs = db.scalars(
        select(ApiRequest).where(
            ApiRequest.destination == incident.service,
            ApiRequest.status_code >= 400,
        ).order_by(ApiRequest.created_at.desc()).limit(50)
    ).all()
    log_rows = {
        row.request_id: {
            "order_id": row.order_id,
            "source": row.source,
            "destination": row.destination,
            "endpoint": row.endpoint,
            "status_code": row.status_code,
            "response_ms": row.response_ms,
            "retry_count": row.retry_count,
            "error": row.error,
            "timestamp": row.created_at.isoformat(),
        }
        for row in [*related_logs, *current_logs]
    }
    events = db.scalars(
        select(Event).where(Event.order_id == incident.order_id).order_by(Event.created_at.asc())
    ).all()
    similar = db.scalars(
        select(Incident).where(
            Incident.category == incident.category,
            Incident.service == incident.service,
            Incident.incident_id != incident.incident_id,
        ).order_by(Incident.created_at.desc()).limit(10)
    ).all()
    predictions = db.scalars(
        select(MLPredictionRecord).where(
            (MLPredictionRecord.incident_id == incident_id)
            | (MLPredictionRecord.order_id == incident.order_id)
        ).order_by(MLPredictionRecord.created_at.desc()).limit(10)
    ).all()
    return rca_agent.analyze(
        {
            "incident_id": incident.incident_id,
            "order_id": incident.order_id,
            "category": incident.category,
            "service": incident.service,
            "status_code": next((row.status_code for row in current_logs if row.status_code >= 400), None),
            "reason": incident.cause,
        },
        logs=list(log_rows.values()),
        similar=[
            {"incident_id": row.incident_id, "service": row.service, "cause": row.cause}
            for row in similar
        ],
        events=[
            {"stage": row.stage, "service": row.service, "status": row.status,
             "message": row.message, "timestamp": row.created_at.isoformat()}
            for row in events
        ],
        model_predictions=[
            {"task": row.task, "prediction": row.prediction, "confidence": row.confidence,
             "model_version": row.model_version}
            for row in predictions
        ],
    )


@router.get("/resolution/recommendations/{incident_id}")
def recovery_recommendation(incident_id: str, db: Session = Depends(get_db)):
    from app.main import Incident, MLPredictionRecord

    incident = db.scalar(select(Incident).where(Incident.incident_id == incident_id))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    model_output = db.scalar(
        select(MLPredictionRecord).where(
            (MLPredictionRecord.incident_id == incident_id)
            | (MLPredictionRecord.order_id == incident.order_id)
        ).order_by(MLPredictionRecord.created_at.desc()).limit(1)
    )
    prediction = model_output.prediction if model_output else incident.category
    actions = {
        "API_TIMEOUT": "retry_transient",
        "SERVER_ERROR": "retry_transient",
        "NETWORK_FAILURE": "retry_transient",
        "AUTHENTICATION_FAILURE": "refresh_token",
        "RATE_LIMIT": "throttle",
        "SCHEMA_MISMATCH": "manual_review",
        "REQUEST_VALIDATION": "manual_review",
        "INVALID_ADDRESS": "address_normalize",
        "INVENTORY_ISSUE": "inventory_reroute",
        "PAYMENT_ISSUE": "payment_escalate",
        "DUPLICATE_ORDER": "manual_review",
        "BUSINESS_RULE_VIOLATION": "manual_review",
    }
    fallback = {
        "API_ERROR": "retry_transient",
        "ORDER_DELAY": "manual_review",
        "ORDER_REJECTION": "manual_review",
    }.get(incident.category, "manual_review")
    action = actions.get(prediction, fallback)
    policy = resolution_engine.policies.get(action)
    if policy is None:
        raise HTTPException(status_code=500, detail="No deterministic policy is configured for the recommendation")
    return {
        "incident_id": incident_id,
        "model_prediction": prediction if model_output else None,
        "prediction_confidence": model_output.confidence if model_output else None,
        "recommendation": action,
        "recommendation_source": "deterministic policy mapping from stored model output" if model_output else "deterministic category fallback",
        "risk": policy.risk.value,
        "requires_operator_approval": not policy.auto_approve or policy.risk.value != "low",
        "policy_validated": True,
        "execution_status": "not_executed",
    }


@router.post("/resolution/execute")
def resolution_execute(payload: dict):
    result = resolution_engine.execute(payload.get("action", ""), payload.get("context", {}))
    if result.get("status") == "pending_approval":
        raise HTTPException(
            status_code=403,
            detail="This action requires a persisted incident and operator decision",
        )
    return result


@router.get("/resolution/executions")
def resolution_executions():
    return {"executions": resolution_engine.executions[-50:]}


@router.get("/approvals/pending")
def approvals_pending(db: Session = Depends(get_db)):
    from app.main import Incident, serialize_incident

    incidents = db.scalars(
        select(Incident)
        .where(Incident.status == "pending_approval")
        .order_by(Incident.created_at.desc())
    ).all()
    return {"approvals": [serialize_incident(incident) for incident in incidents]}


@router.post("/approvals/decide")
def approvals_decide(payload: dict, db: Session = Depends(get_db)):
    from app.main import Incident, resolve_incident

    approval_id = payload.get("approval_id")
    decision = payload.get("decision")
    if decision not in {"approve", "reject", "escalate"}:
        raise HTTPException(status_code=422, detail="Decision must be approve, reject, or escalate")
    incident = db.scalar(
        select(Incident).where(Incident.incident_id == approval_id)
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Approval incident not found")
    result = resolve_incident(db, incident, decision == "approve", decision)
    return {"ok": True, "approval_id": approval_id, "decision": decision, **result}


@router.get("/telemetry/recent")
def telemetry_recent(limit: int = 100):
    return {"events": telemetry.get_recent(limit)}


@router.get("/tracing/dependency-map")
def dependency_map():
    return {
        "nodes": [
            {"id": "CRM", "status": "healthy", "latency_ms": 45},
            {"id": "OMS", "status": "healthy", "latency_ms": 62},
            {"id": "Inventory", "status": "healthy", "latency_ms": 38},
            {"id": "Payment", "status": "healthy", "latency_ms": 124},
            {"id": "Provisioning", "status": "healthy", "latency_ms": 256},
            {"id": "Logistics", "status": "healthy", "latency_ms": 89},
            {"id": "Notification", "status": "healthy", "latency_ms": 23},
        ],
        "edges": [
            {"from": "CRM", "to": "OMS"},
            {"from": "OMS", "to": "Inventory"},
            {"from": "OMS", "to": "Payment"},
            {"from": "Payment", "to": "Provisioning"},
            {"from": "Provisioning", "to": "Logistics"},
            {"from": "Logistics", "to": "Notification"},
        ],
    }


@router.get("/analytics/metrics")
def analytics_metrics(db: Session = Depends(get_db)):
    from app.main import ApiRequest, Incident, Order

    orders = db.scalars(select(Order)).all()
    incidents = db.scalars(select(Incident)).all()
    requests = db.scalars(select(ApiRequest)).all()
    requests_by_order: dict[str, list[ApiRequest]] = {}
    for request in requests:
        requests_by_order.setdefault(request.order_id, []).append(request)

    detection_seconds: list[float] = []
    resolution_seconds: list[float] = []
    for incident in incidents:
        failed_requests = [
            request for request in requests_by_order.get(incident.order_id, [])
            if request.status_code >= 400
        ]
        if failed_requests:
            detected_at = incident.created_at
            failure_at = min(request.created_at for request in failed_requests)
            if detected_at.tzinfo is None:
                detected_at = detected_at.replace(tzinfo=timezone.utc)
            if failure_at.tzinfo is None:
                failure_at = failure_at.replace(tzinfo=timezone.utc)
            detection_seconds.append(max(0.0, (detected_at - failure_at).total_seconds()))
        if incident.resolved_at is not None:
            resolved_at = incident.resolved_at
            created_at = incident.created_at
            if resolved_at.tzinfo is None:
                resolved_at = resolved_at.replace(tzinfo=timezone.utc)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            resolution_seconds.append(max(0.0, (resolved_at - created_at).total_seconds()))

    completed = sum(order.status == "Completed" for order in orders)
    recovered = sum(
        order.resolution_status in {"auto_recovered", "recovered", "approved_recovery"}
        for order in orders
    )
    resolved_count = sum(incident.status == "resolved" for incident in incidents)
    manual_count = sum(
        incident.status == "resolved" and incident.category != "API_ERROR"
        for incident in incidents
    )
    sla_orders = [order for order in orders if getattr(order, "sla_deadline_ms", None) is not None]
    sla_compliance = None
    if sla_orders:
        sla_met = 0
        for order in sla_orders:
            created_at = order.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if order.completed_at is not None:
                completed_at = order.completed_at
                if completed_at.tzinfo is None:
                    completed_at = completed_at.replace(tzinfo=timezone.utc)
                duration_ms = (completed_at - created_at).total_seconds() * 1000
                if duration_ms <= max(order.sla_deadline_ms, 1):
                    sla_met += 1
            elif order.status in {"Processing", "Delayed", "Failed", "Rejected"}:
                remaining_ms = max(order.sla_deadline_ms, 1) - (datetime.now(timezone.utc) - created_at).total_seconds() * 1000
                if remaining_ms >= 0:
                    sla_met += 1
        sla_compliance = round(100 * sla_met / len(sla_orders), 1)
    return {
        "orders_total": len(orders),
        "incidents_total": len(incidents),
        "mttd_min": round(sum(detection_seconds) / len(detection_seconds) / 60, 2) if detection_seconds else 0,
        "mttr_min": round(sum(resolution_seconds) / len(resolution_seconds) / 60, 2) if resolution_seconds else 0,
        "auto_recovery_rate": round(recovered / len(incidents), 4) if incidents else 0,
        "manual_intervention_rate": round(manual_count / resolved_count, 4) if resolved_count else 0,
        "sla_compliance": sla_compliance,
        "sla_metric_basis": "Persisted per-order SLA deadlines" if sla_compliance is not None else "Unavailable: per-order SLA deadlines are not persisted",
        "order_completion_rate": round(completed / len(orders), 4) if orders else 0,
    }
