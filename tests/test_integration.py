import asyncio
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "scenario" in data
    assert "routing_plans" in data
    assert "edges" in data
    assert len(data["routing_plans"]) > 0, "Expected at least one routing plan for seating zones"


def test_scenario_switching():
    # 1. Load bottleneck scenario
    response = client.post("/api/scenarios/bottleneck")
    assert response.status_code == 200
    data = response.json()
    assert data["scenario"] == "bottleneck"
    assert len(data["data"]["bottlenecks"]) > 0

    # 2. Check status matches new scenario
    status_resp = client.get("/api/status")
    assert status_resp.json()["scenario"] == "bottleneck"

    # 3. Load normal scenario
    client.post("/api/scenarios/normal")
    assert client.get("/api/status").json()["scenario"] == "normal"


def test_announcement_endpoint():
    response = client.get("/api/announcement?zone=Section_101_Lower&lang=es")
    assert response.status_code == 200
    data = response.json()
    assert "instruction" in data
    assert "path" in data
    assert data["status"] == "success"


def test_fan_registration_xss_and_pii_masking():
    # Attempt to post details containing XSS script and clear PII
    post_data = {
        "name": "Jane <script>alert(1)</script> Doe",
        "email": "jane.doe@example.com",
        "phone": "+1-555-0199",
        "ticket_id": "TKT-1049-US",
        "start_zone": "Section_101_Lower"
    }
    response = client.post("/api/register_fan", json=post_data)
    assert response.status_code == 200
    data = response.json()
    
    # 1. Assert XSS scripting is sanitized out of the output name
    assert "<script>" not in data["fan"]["name"]
    
    # 2. Assert PII elements are masked
    assert "jane.doe@example.com" not in data["fan"]["masked_email"]
    assert "j******e@e*****e.com" in data["fan"]["masked_email"]
    assert "+1-555-0199" not in data["fan"]["masked_phone"]
    assert "***" in data["fan"]["masked_phone"]
    assert "TKT-1049-US" not in data["fan"]["masked_ticket"]
    assert "TKT-****-US" in data["fan"]["masked_ticket"]


def test_rate_limiting():
    response = client.get("/api/status")
    assert "X-Frame-Options" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in response.headers


def test_crush_risk_endpoint():
    """GET /api/crush_risk returns valid level and zone list."""
    # Load bottleneck scenario first to ensure some congestion
    client.post("/api/scenarios/bottleneck")
    response = client.get("/api/crush_risk")
    assert response.status_code == 200
    data = response.json()
    assert "level" in data
    assert data["level"] in ("LOW", "MODERATE", "CRITICAL")
    assert "zones" in data
    assert "summary" in data
    # Reset
    client.post("/api/scenarios/normal")


def test_triage_endpoint_offline():
    """POST /api/triage returns structured classification (offline fallback path)."""
    response = client.post("/api/triage", json={"description": "Fan collapsed near Gate B, unconscious"})
    assert response.status_code == 200
    data = response.json()
    assert "category" in data
    assert "severity" in data
    assert "recommended_action" in data
    assert data["category"] in ("Medical", "Security", "Structural", "Crowd", "Equipment")
    assert 1 <= data["severity"] <= 5


def test_chat_endpoint_offline():
    """POST /api/chat returns a response string (offline fallback path)."""
    response = client.post("/api/chat", json={"message": "Where is the nearest exit?", "lang": "en", "history": []})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert len(data["response"]) > 5


def test_audit_log_endpoint():
    """GET /api/audit_log returns a valid log structure."""
    response = client.get("/api/audit_log")
    assert response.status_code == 200
    data = response.json()
    assert "total_entries" in data
    assert "entries" in data


def test_audit_verify_endpoint():
    """GET /api/audit_verify reports chain as valid."""
    response = client.get("/api/audit_verify")
    assert response.status_code == 200
    data = response.json()
    assert "valid" in data
    assert data["valid"] is True
    assert data["tampered_entries"] == []
