from fastapi.testclient import TestClient

from app.main import analyze, app, detect


def test_api_error_detection() -> None:
    assert detect("API_ERROR", 504, 2000)[0] is True
    assert detect("API_ERROR", 200, 2000)[0] is False


def test_delay_detection_uses_sla_threshold() -> None:
    assert detect("ORDER_DELAY", 200, 30001, 30000)[0] is True
    assert detect("ORDER_DELAY", 200, 29999, 30000)[0] is False


def test_rejection_detection() -> None:
    assert detect("ORDER_REJECTION", 422, 120)[0] is True
    assert detect("ORDER_REJECTION", 200, 120)[0] is False


def test_analysis_is_evidence_based_and_rule_labelled() -> None:
    cause, recommendation, evidence, confidence = analyze(
        "API_ERROR", "Provisioning", 504, 32000, "gateway timeout"
    )
    assert "HTTP 504" in cause
    assert "exponential backoff" in recommendation
    assert any("32000 ms" in item for item in evidence)
    assert 0 < confidence <= 1


def test_business_action_requires_operator_approval() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/simulation/inject-failure",
            json={"category": "ORDER_REJECTION", "service": "Inventory"},
        )
        order_id = response.json()["order"]["order_id"]
        incidents = client.get("/api/monitoring/incidents").json()
        incident = next(item for item in incidents if item["order_id"] == order_id)

        rejected = client.post(f"/api/resolutions/{incident['incident_id']}/retry")
        assert rejected.status_code == 403

        approved = client.post(f"/api/resolutions/{incident['incident_id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["order"]["status"] == "Completed"
        assert approved.json()["incident"]["status"] == "resolved"

        audit = client.get("/api/audit-logs").json()
        assert any(item["order_id"] == order_id and item["action"] == "resolution.approve" for item in audit)


def test_v2_risky_action_cannot_be_auto_approved_by_request() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v2/resolution/execute",
            json={"action": "fallback_route", "context": {}, "auto_approve": True},
        )

    assert response.status_code == 403


def test_v2_analytics_and_approvals_use_persisted_records() -> None:
    with TestClient(app) as client:
        injected = client.post(
            "/api/simulation/inject-failure",
            json={"category": "ORDER_REJECTION", "service": "Inventory"},
        ).json()["order"]

        metrics = client.get("/api/v2/analytics/metrics").json()
        approvals = client.get("/api/v2/approvals/pending").json()["approvals"]
        order_count = len(client.get("/api/orders?limit=500").json()["items"])
        incident_count = len(client.get("/api/monitoring/incidents?limit=500").json())
        approval = next(item for item in approvals if item["order_id"] == injected["order_id"])
        decision = client.post(
            "/api/v2/approvals/decide",
            json={"approval_id": approval["incident_id"], "decision": "approve"},
        )
        audit = client.get("/api/audit-logs?limit=500").json()

    assert metrics["orders_total"] == order_count
    assert metrics["incidents_total"] == incident_count
    assert metrics["sla_compliance"] is not None
    assert metrics["sla_metric_basis"] == "Persisted per-order SLA deadlines"
    assert any(item["order_id"] == injected["order_id"] for item in approvals)
    assert decision.status_code == 200
    assert decision.json()["incident"]["status"] == "resolved"
    assert decision.json()["order"]["status"] == "Completed"
    assert any(item["order_id"] == injected["order_id"] and item["action"] == "resolution.approve" for item in audit)


def test_order_sla_deadlines_are_persisted_and_used_for_metrics() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/orders",
            json={"order_type": "Service add-on", "priority": "High"},
        )
        order = response.json()
        metrics = client.get("/api/v2/analytics/metrics").json()
        saved_order = client.get(f"/api/orders/{order['order_id']}").json()

    assert response.status_code == 201
    assert order["sla_deadline_ms"] > 0
    assert saved_order["sla_deadline_ms"] == order["sla_deadline_ms"]
    assert metrics["sla_compliance"] is not None
    assert metrics["sla_metric_basis"] == "Persisted per-order SLA deadlines"


def test_delay_model_api_is_deterministic_and_reports_synthetic_basis() -> None:
    with TestClient(app) as client:
        payload = {
            "processing_duration_ms": 90000,
            "current_stage": "PROVISIONING",
            "queue_depth": 130,
            "service_latency_ms": 4200,
            "previous_stage_duration_ms": 22000,
            "historical_service_latency_ms": 700,
            "sla_utilization": 0.75,
        }
        response = client.post(
            "/api/v2/ml/delay-predict",
            json=payload,
        )
        repeated = client.post("/api/v2/ml/delay-predict", json=payload)
        invalid = client.post("/api/v2/ml/delay-predict", json={"processing_duration_ms": 100})

    assert response.status_code == 200
    assert invalid.status_code == 422
    prediction = response.json()
    assert repeated.json() == prediction
    assert 0 <= prediction["sla_breach_probability"] <= 1
    assert prediction["estimated_remaining_processing_ms"] >= 0
    assert prediction["automatic_action"] is False
    assert prediction["probabilities_calibrated"] is False
    assert "synthetic" in prediction["data_source"]


def test_failure_and_rejection_models_persist_predictions_and_feedback() -> None:
    with TestClient(app) as client:
        failure = client.post(
            "/api/v2/ml/predict",
            json={
                "status_code": 504,
                "response_ms": 30000,
                "service": "Provisioning",
                "endpoint": "/provision/activate",
                "error_message": "gateway timed out waiting for downstream response",
                "retry_count": 0,
            },
        )
        rejection = client.post(
            "/api/v2/ml/rejections/predict",
            json={
                "status_code": 422,
                "service": "Address Validation",
                "endpoint": "/orders/address/validate",
                "rejection_reason": "postal code does not match the selected city",
                "retry_count": 0,
                "alternative_inventory_available": False,
            },
        )
        metrics = client.get("/api/v2/ml/metrics").json()
        prediction_id = rejection.json()["prediction_id"]
        feedback = client.post(
            "/api/v2/ml/feedback",
            json={
                "prediction_id": prediction_id,
                "actual_label": "INVALID_ADDRESS",
                "prediction_correct": True,
            },
        )
        recent = client.get("/api/v2/ml/predictions/recent?limit=20").json()["predictions"]

        injected = client.post(
            "/api/simulation/inject-failure",
            json={"category": "API_ERROR", "service": "Provisioning"},
        ).json()["order"]
        incidents = client.get("/api/monitoring/incidents").json()
        incident = next(item for item in incidents if item["order_id"] == injected["order_id"])

    assert failure.status_code == 200
    assert failure.json()["prediction"] in {"API_TIMEOUT", "SERVER_ERROR"}
    assert failure.json()["confidence"] > 0.4
    assert rejection.status_code == 200
    assert rejection.json()["rejection_type"] == "INVALID_ADDRESS"
    assert rejection.json()["fixability"] == "FIXABLE"
    assert rejection.json()["automatic_execution_allowed"] is False
    assert metrics["model_availability"]["api_failure_classifier"] is True
    assert feedback.status_code == 200
    assert feedback.json()["training_effect"] == "stored_for_future_review"
    assert any(item["prediction_id"] == prediction_id for item in recent)
    assert any("ML subtype:" in evidence for evidence in incident["evidence"])


def test_order_delay_prediction_uses_persisted_order_telemetry() -> None:
    with TestClient(app) as client:
        order = client.post(
            "/api/simulation/inject-failure",
            json={"category": "ORDER_DELAY", "service": "Logistics"},
        ).json()["order"]
        prediction = client.post(f"/api/v2/ml/orders/{order['order_id']}/delay-predict")
        history = client.get("/api/v2/ml/predictions/recent?limit=20").json()["predictions"]

    assert prediction.status_code == 200
    result = prediction.json()
    assert result["order_id"] == order["order_id"]
    assert result["input_source"] == "persisted order, lifecycle events, and API requests"
    assert result["automatic_action"] is False
    assert any(item["order_id"] == order["order_id"] and item["task"] == "delay" for item in history)


def test_persisted_rca_and_recommendation_use_evidence_and_policy() -> None:
    with TestClient(app) as client:
        order = client.post(
            "/api/simulation/inject-failure",
            json={"category": "API_ERROR", "service": "Provisioning"},
        ).json()["order"]
        incidents = client.get("/api/monitoring/incidents").json()
        incident = next(item for item in incidents if item["order_id"] == order["order_id"])
        rca = client.get(f"/api/v2/rca/incidents/{incident['incident_id']}").json()
        recommendation = client.get(
            f"/api/v2/resolution/recommendations/{incident['incident_id']}"
        ).json()

        rejection_order = client.post(
            "/api/simulation/inject-failure",
            json={"category": "ORDER_REJECTION", "service": "Inventory"},
        ).json()["order"]
        rejection_incident = next(
            item for item in client.get("/api/monitoring/incidents").json()
            if item["order_id"] == rejection_order["order_id"]
        )
        rejection_recommendation = client.get(
            f"/api/v2/resolution/recommendations/{rejection_incident['incident_id']}"
        ).json()

    assert rca["log_similarity_method"] == "TF-IDF"
    assert any("Provisioning HTTP 504" in evidence for evidence in rca["evidence"])
    assert rca["confidence_method"] == "evidence-count heuristic; not an ML probability"
    assert recommendation["recommendation"] == "retry_transient"
    assert recommendation["risk"] == "low"
    assert recommendation["policy_validated"] is True
    assert recommendation["execution_status"] == "not_executed"
    assert rejection_recommendation["risk"] == "medium"
    assert rejection_recommendation["requires_operator_approval"] is True


def test_invalid_address_and_hard_rejection_use_distinct_safe_paths() -> None:
    with TestClient(app) as client:
        address_order = client.post(
            "/api/simulation/inject-failure",
            json={"category": "ORDER_REJECTION", "service": "Address Validation"},
        ).json()["order"]
        incidents = client.get("/api/monitoring/incidents").json()
        address_incident = next(item for item in incidents if item["order_id"] == address_order["order_id"])
        address_action = client.get(
            f"/api/v2/resolution/recommendations/{address_incident['incident_id']}"
        ).json()

        hard_order = client.post(
            "/api/simulation/inject-failure",
            json={"category": "ORDER_REJECTION", "service": "Business Rules"},
        ).json()["order"]
        incidents = client.get("/api/monitoring/incidents").json()
        hard_incident = next(item for item in incidents if item["order_id"] == hard_order["order_id"])
        hard_action = client.get(
            f"/api/v2/resolution/recommendations/{hard_incident['incident_id']}"
        ).json()
        unsafe_retry = client.post(f"/api/resolutions/{hard_incident['incident_id']}/retry")

    assert any("ML rejection type: INVALID_ADDRESS" in item for item in address_incident["evidence"])
    assert address_action["recommendation"] == "address_normalize"
    assert address_action["requires_operator_approval"] is True
    assert any("ML rejection type: BUSINESS_RULE_VIOLATION" in item for item in hard_incident["evidence"])
    assert hard_action["recommendation"] == "manual_review"
    assert hard_action["risk"] == "high"
    assert hard_action["requires_operator_approval"] is True
    assert unsafe_retry.status_code == 403
