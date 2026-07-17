import pytest
import hashlib
import json
from app.security import sanitize_input, mask_pii_string

def test_input_sanitization():
    # 1. Test XSS Script Removal
    xss_payload = "Hello <script>alert('hack')</script> world"
    assert "script" not in sanitize_input(xss_payload)
    
    # 2. Test HTML escaping
    html_payload = "<div>Test</div>"
    assert "&lt;div&gt;Test&lt;/div&gt;" in sanitize_input(html_payload)
    
    # 3. Test inline handlers removal
    onload_payload = "<img src=x onerror=alert(1)>"
    assert "onerror" not in sanitize_input(onload_payload)
    
    # 4. Test SQL quotes escaping
    sql_payload = "SELECT * FROM users WHERE name = 'admin' --"
    sanitized_sql = sanitize_input(sql_payload)
    assert "&#x27;admin&#x27;" in sanitized_sql


def test_pii_masking():
    # 1. Test Email Masking
    log_line = "Admin email is john.doe@example.com for registry"
    masked = mask_pii_string(log_line)
    assert "john.doe@example.com" not in masked
    assert "j******e@e*****e.com" in masked
    
    # 2. Test Phone Masking
    log_line_2 = "Contact fan at +1-555-0199 for tickets"
    masked_2 = mask_pii_string(log_line_2)
    assert "+1-555-0199" not in masked_2
    assert "+***0199" in masked_2 or "***" in masked_2
    
    # 3. Test Ticket ID Masking
    log_line_3 = "Egress route for ticket TICKET-1049-US is Gate A"
    masked_3 = mask_pii_string(log_line_3)
    assert "TICKET-1049-US" not in masked_3
    assert "TICKET-****-US" in masked_3 or "TKT-****-****" in masked_3


# ── Feature #99 — Tamper-Evident Audit Log Tests ──────────────────────────────

_GENESIS_HASH = "0" * 64


def _make_entry(index: int, event_type: str, data: dict, prev_hash: str) -> dict:
    """Replicates the main.py _append_audit_event() hashing logic."""
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    payload_str = f"{prev_hash}|{index}|{event_type}|{json.dumps(data, sort_keys=True)}"
    entry_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    return {
        "index": index, "timestamp": timestamp, "event_type": event_type,
        "data": data, "prev_hash": prev_hash, "hash": entry_hash,
    }


def _verify_chain(audit_log: list) -> dict:
    """Replicates /api/audit_verify logic for pure unit testing."""
    if not audit_log:
        return {"valid": True, "tampered_entries": []}
    tampered = []
    prev_hash = _GENESIS_HASH
    for entry in audit_log:
        payload_str = f"{prev_hash}|{entry['index']}|{entry['event_type']}|{json.dumps(entry['data'], sort_keys=True)}"
        expected = hashlib.sha256(payload_str.encode()).hexdigest()
        if entry["hash"] != expected or entry["prev_hash"] != prev_hash:
            tampered.append(entry["index"])
        prev_hash = entry["hash"]
    return {"valid": len(tampered) == 0, "tampered_entries": tampered}


def test_audit_chain_empty():
    """Empty audit log reports as valid."""
    result = _verify_chain([])
    assert result["valid"] is True
    assert result["tampered_entries"] == []


def test_audit_chain_single_entry_valid():
    """A single correctly-hashed entry verifies as valid."""
    entry = _make_entry(0, "SYSTEM_START", {"msg": "startup"}, _GENESIS_HASH)
    result = _verify_chain([entry])
    assert result["valid"] is True


def test_audit_chain_multi_entry_valid():
    """Five correctly-hashed entries all pass integrity verification."""
    log = []
    prev = _GENESIS_HASH
    events = [
        ("SCENARIO_LOAD", {"name": "normal"}),
        ("BOTTLENECK_DETECTED", {"count": 3}),
        ("INCIDENT_TRIAGE", {"category": "Medical", "severity": 4}),
        ("ALERT_L2_PA_AND_SMS_TRIGGER", {"zone": "Concourse_East_1"}),
        ("CRUSH_RISK_DETECTED", {"level": "MODERATE"}),
    ]
    for i, (etype, data) in enumerate(events):
        entry = _make_entry(i, etype, data, prev)
        log.append(entry)
        prev = entry["hash"]
    result = _verify_chain(log)
    assert result["valid"] is True
    assert len(result["tampered_entries"]) == 0


def test_audit_chain_tamper_detection():
    """Modifying a stored entry's data AFTER hashing must cause verification to FAIL."""
    log = []
    prev = _GENESIS_HASH
    for i in range(3):
        entry = _make_entry(i, f"EVENT_{i}", {"value": i}, prev)
        log.append(entry)
        prev = entry["hash"]
    # Silently alter entry 1's data
    log[1]["data"]["value"] = 9999
    result = _verify_chain(log)
    assert result["valid"] is False
    assert 1 in result["tampered_entries"]


# ── Feature #44 — Offline Triage Keyword Classifier Tests ─────────────────────

def test_offline_triage_medical():
    from app.ai_helper import _offline_triage
    result = _offline_triage("Fan collapsed unconscious near Gate B2, not breathing")
    assert result["category"] == "Medical"
    assert result["severity"] >= 4


def test_offline_triage_security():
    from app.ai_helper import _offline_triage
    result = _offline_triage("Fight breaking out in Section 104, weapon possibly involved")
    assert result["category"] == "Security"


def test_offline_triage_equipment():
    from app.ai_helper import _offline_triage
    result = _offline_triage("Turnstile scanner stuck at Gate A1, queue forming")
    assert result["category"] == "Equipment"


def test_offline_triage_returns_recommended_action():
    from app.ai_helper import _offline_triage
    result = _offline_triage("Crowd is surging and pushing in the east concourse")
    assert "recommended_action" in result
    assert len(result["recommended_action"]) > 10
