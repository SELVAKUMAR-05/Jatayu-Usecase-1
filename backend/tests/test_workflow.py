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
