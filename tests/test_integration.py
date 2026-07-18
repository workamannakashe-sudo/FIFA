"""
tests/test_integration.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Integration tests for SafePass 2026 REST and WebSocket APIs.
"""

from app.config import STAFF_API_KEY


def test_api_status(test_client):
    """GET /api/status returns valid telemetry, nodes, and routing plans."""
    response = test_client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "scenario" in data
    assert "routing_plans" in data
    assert "edges" in data
    assert len(data["routing_plans"]) > 0


def test_scenario_switching(test_client):
    """Loading a simulation scenario overrides routing engine occupancies and blockages."""
    # 1. Load bottleneck scenario
    response = test_client.post("/api/scenarios/bottleneck")
    assert response.status_code == 200
    data = response.json()
    assert data["scenario"] == "bottleneck"
    assert len(data["data"]["bottlenecks"]) > 0

    # 2. Check status matches new scenario
    status_resp = test_client.get("/api/status")
    assert status_resp.json()["scenario"] == "bottleneck"

    # 3. Reset to normal scenario
    test_client.post("/api/scenarios/normal")
    assert test_client.get("/api/status").json()["scenario"] == "normal"


def test_announcement_endpoint(test_client):
    """GET /api/announcement returns path routes and translated instructions."""
    response = test_client.get("/api/announcement?zone=Section_101_Lower&lang=es")
    assert response.status_code == 200
    data = response.json()
    assert "instruction" in data
    assert "path" in data
    assert data["status"] == "success"


def test_announcement_endpoint_invalid_zone(test_client):
    """GET /api/announcement with invalid zone returns 404."""
    response = test_client.get("/api/announcement?zone=Invalid_Zone_123&lang=en")
    assert response.status_code == 404
    assert "Stadium zone not found" in response.json()["detail"]


def test_announcement_endpoint_xss_query_rejected(test_client):
    """GET /api/announcement with script tag in query parameter returns 400."""
    response = test_client.get("/api/announcement?zone=Section_101_Lower&lang=<script>alert(1)</script>")
    assert response.status_code == 400
    assert "Malicious content detected" in response.json()["detail"]


def test_fan_registration_xss_and_pii_masking(test_client):
    """POST /api/register_fan sanitizes name and masks sensitive contact information in response."""
    post_data = {
        "name": "Jane <script>alert(1)</script> Doe",
        "email": "jane.doe@example.com",
        "phone": "+1-555-0199",
        "ticket_id": "TKT-1049-US",
        "start_zone": "Section_101_Lower"
    }
    response = test_client.post("/api/register_fan", json=post_data)
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


def test_security_headers(test_client):
    """SecurityMiddleware injects OWASP-recommended security response headers."""
    response = test_client.get("/api/status")
    headers = response.headers
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in headers
    assert "Strict-Transport-Security" in headers
    assert "Content-Security-Policy" in headers


def test_cors_headers(test_client):
    """CORS middleware handles requests from whitelisted origins correctly."""
    # Origin not in whitelist should not receive access-control headers
    response = test_client.get("/api/status", headers={"Origin": "https://malicious.com"})
    assert "access-control-allow-origin" not in response.headers


def test_crush_risk_endpoint(test_client):
    """GET /api/crush_risk returns overall status and risk zones under congestion."""
    test_client.post("/api/scenarios/bottleneck")
    response = test_client.get("/api/crush_risk")
    assert response.status_code == 200
    data = response.json()
    assert "level" in data
    assert data["level"] in ("LOW", "MODERATE", "CRITICAL")
    assert "zones" in data

    # Clean up
    test_client.post("/api/scenarios/normal")


def test_triage_endpoint_authorized(test_client):
    """POST /api/triage succeeds with correct staff API key."""
    headers = {"X-Staff-API-Key": STAFF_API_KEY}
    post_data = {"description": "Fan collapsed near Gate B, unconscious"}
    response = test_client.post("/api/triage", json=post_data, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "category" in data
    assert "severity" in data
    assert "recommended_action" in data


def test_triage_endpoint_unauthorized(test_client):
    """POST /api/triage returns 422 when API key header is missing, and 403 when wrong."""
    post_data = {"description": "Fan collapsed near Gate B, unconscious"}

    # Missing key header (FastAPI raises validation error)
    response = test_client.post("/api/triage", json=post_data)
    assert response.status_code == 422

    # Incorrect key header
    response = test_client.post("/api/triage", json=post_data, headers={"X-Staff-API-Key": "fake"})
    assert response.status_code == 403


def test_chat_endpoint_offline(test_client):
    """POST /api/chat provides a RAG response for stadium queries."""
    post_data = {
        "message": "Where is the nearest medical stand?",
        "lang": "en",
        "history": []
    }
    response = test_client.post("/api/chat", json=post_data)
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert len(data["response"]) > 0


def test_alert_endpoint_workflow(test_client):
    """POST /api/alert triggers lockdowns and creates verifiable audit records."""
    headers = {"X-Staff-API-Key": STAFF_API_KEY}

    # 1. Dispatch L3 lockdown on Gate_A1_North
    alert_payload = {
        "level": 3,
        "zone": "Gate_A1_North",
        "message": "Security emergency in plaza. Lockdown in effect."
    }
    response = test_client.post("/api/alert", json=alert_payload, headers=headers)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "dispatched"
    assert res_data["locked_zone"] == "Gate_A1_North"

    # 2. Check that the lockdown blocked adjacent corridors in live status
    status_resp = test_client.get("/api/status")
    edges = status_resp.json()["edges"]
    gate_edges = [e for e in edges if e["source"] == "Gate_A1_North" or e["target"] == "Gate_A1_North"]
    for e in gate_edges:
        assert e["is_blocked"] is True

    # 3. Verify audit log reflects the alert and is structurally intact
    verify_resp = test_client.get("/api/audit_verify")
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True


def test_websocket_telemetry(test_client):
    """WebSocket connection receives immediate status update and pong keepalives."""
    with test_client.websocket_connect("/ws") as websocket:
        # On connection, server pushes status update
        data = websocket.receive_json()
        assert data["type"] == "state_update"
        assert "nodes" in data["data"]

        # Test keepalive pong
        websocket.send_text("ping")
        resp = websocket.receive_json()
        assert resp["type"] == "pong"


def test_block_edge_endpoint(test_client):
    """POST /api/block_edge blocks and unblocks a corridor."""
    # Block corridor Section_101_Lower -> Concourse_North_1
    post_data = {"source": "Section_101_Lower", "target": "Concourse_North_1", "is_blocked": True}
    response = test_client.post("/api/block_edge", json=post_data)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify edge is blocked in status
    status_resp = test_client.get("/api/status")
    edge = [
        e for e in status_resp.json()["edges"]
        if (e["source"] == "Section_101_Lower" and e["target"] == "Concourse_North_1")
        or (e["source"] == "Concourse_North_1" and e["target"] == "Section_101_Lower")
    ][0]
    assert edge["is_blocked"] is True

    # Unblock corridor
    post_data["is_blocked"] = False
    response = test_client.post("/api/block_edge", json=post_data)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify edge is unblocked
    status_resp = test_client.get("/api/status")
    edge = [
        e for e in status_resp.json()["edges"]
        if (e["source"] == "Section_101_Lower" and e["target"] == "Concourse_North_1")
        or (e["source"] == "Concourse_North_1" and e["target"] == "Section_101_Lower")
    ][0]
    assert edge["is_blocked"] is False


def test_update_occupancy_endpoint(test_client):
    """POST /api/update_occupancy sets edge occupancy for live congestion routing."""
    # Set occupancy to 50
    post_data = {"source": "Section_101_Lower", "target": "Concourse_North_1", "occupancy": 50.0}
    response = test_client.post("/api/update_occupancy", json=post_data)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify occupancy in status
    status_resp = test_client.get("/api/status")
    edge = [
        e for e in status_resp.json()["edges"]
        if (e["source"] == "Section_101_Lower" and e["target"] == "Concourse_North_1")
        or (e["source"] == "Concourse_North_1" and e["target"] == "Section_101_Lower")
    ][0]
    assert edge["occupancy"] == 50.0

    # Reset occupancy
    post_data["occupancy"] = 0.0
    response = test_client.post("/api/update_occupancy", json=post_data)
    assert response.status_code == 200


# ── Additional Coverage Tests ──────────────────────────────────────────────────

def test_health_endpoint(test_client):
    """GET /api/health returns 200 with service status and operational metadata."""
    response = test_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "SafePass 2026"
    assert "audit_entries" in data
    assert "active_ws_connections" in data


def test_audit_log_endpoint(test_client):
    """GET /api/audit_log returns audit entries with correct structure."""
    response = test_client.get("/api/audit_log")
    assert response.status_code == 200
    data = response.json()
    assert "total_entries" in data
    assert "entries" in data
    assert isinstance(data["entries"], list)
    assert data["total_entries"] >= 1  # At least SYSTEM_START entry


def test_audit_log_limit_parameter(test_client):
    """GET /api/audit_log respects the limit query parameter."""
    response = test_client.get("/api/audit_log?limit=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["entries"]) <= 1


def test_audit_verify_endpoint(test_client):
    """GET /api/audit_verify confirms the hash chain is tamper-free."""
    response = test_client.get("/api/audit_verify")
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["verified_count"] >= 1
    assert data["tampered_entries"] == []
    assert "chain_tip_hash" in data


def test_load_scenario_not_found(test_client):
    """POST /api/scenarios/{name} with unknown scenario name returns 404."""
    response = test_client.post("/api/scenarios/nonexistent_scenario_xyz")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_register_fan_invalid_zone(test_client):
    """POST /api/register_fan with an invalid start_zone returns 404."""
    post_data = {
        "name": "Test Fan",
        "email": "test@example.com",
        "phone": "+1-555-9999",
        "ticket_id": "TKT-9999-US",
        "start_zone": "InvalidZone_XYZ_999",
    }
    response = test_client.post("/api/register_fan", json=post_data)
    assert response.status_code == 404
    assert "zone" in response.json()["detail"].lower()


def test_update_occupancy_invalid_nodes(test_client):
    """POST /api/update_occupancy with invalid node names returns 404."""
    post_data = {"source": "NonExistentNode_A", "target": "NonExistentNode_B", "occupancy": 50.0}
    response = test_client.post("/api/update_occupancy", json=post_data)
    assert response.status_code == 404


def test_block_edge_invalid_nodes(test_client):
    """POST /api/block_edge with invalid node names returns 404."""
    post_data = {"source": "BadNode_X", "target": "BadNode_Y", "is_blocked": True}
    response = test_client.post("/api/block_edge", json=post_data)
    assert response.status_code == 404


def test_chat_invalid_language(test_client):
    """POST /api/chat with an unsupported language code returns 422 validation error."""
    post_data = {
        "message": "Where is the exit?",
        "lang": "xx",  # not in SUPPORTED_ISO_LANGS
        "history": [],
    }
    response = test_client.post("/api/chat", json=post_data)
    assert response.status_code == 422


def test_chat_with_conversation_history(test_client):
    """POST /api/chat with conversation history returns a coherent response."""
    post_data = {
        "message": "And what about food options?",
        "lang": "en",
        "history": [
            {"role": "fan", "text": "Where is the first aid station?"},
            {"role": "assistant", "text": "First Aid is at Concourse North, South and West."},
        ],
    }
    response = test_client.post("/api/chat", json=post_data)
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert len(data["response"]) > 0


def test_list_scenarios_endpoint(test_client):
    """GET /api/scenarios returns a list of available scenarios with required fields."""
    response = test_client.get("/api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert isinstance(scenarios, list)
    assert len(scenarios) > 0
    for s in scenarios:
        assert "id" in s
        assert "title" in s
        assert "description" in s
