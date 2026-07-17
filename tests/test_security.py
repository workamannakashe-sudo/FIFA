"""
tests/test_security.py
~~~~~~~~~~~~~~~~~~~~~~
Unit tests for input sanitisation, PII masking, cryptographic audit logs, and security helpers.
"""

import hashlib
import json
import pytest
from fastapi import HTTPException
from app.security import sanitize_input, mask_pii_string, require_staff_key
from app.constants import AUDIT_GENESIS_HASH


def test_input_sanitization():
    """Verify XSS and injection patterns are neutralized."""
    # XSS Script tag stripping
    assert "script" not in sanitize_input("Hello <script>alert('hack')</script> world")
    
    # HTML tag escaping
    assert "&lt;div&gt;Test&lt;/div&gt;" in sanitize_input("<div>Test</div>")
    
    # Event handler stripping
    assert "onerror" not in sanitize_input("<img src=x onerror=alert(1)>")
    assert "onload" not in sanitize_input("<body onload=calc()>")


def test_pii_masking():
    """Verify sensitive fan identifiers are masked in logs and telemetry strings."""
    # Email
    assert "john.doe@example.com" not in mask_pii_string("Email is john.doe@example.com")
    assert "j******e@e*****e.com" in mask_pii_string("Email is john.doe@example.com")

    # Phone
    assert "+1-555-0199" not in mask_pii_string("Phone +1-555-0199 details")
    assert "+***0199" in mask_pii_string("Phone +1-555-0199 details")

    # Ticket ID
    assert "TKT-1049-US" not in mask_pii_string("Ticket TKT-1049-US checked")
    assert "TKT-****-US" in mask_pii_string("Ticket TKT-1049-US checked")


# ── Staff API Key Dependency Tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_require_staff_key_valid():
    """Verify require_staff_key runs without exception for a correct key."""
    from app.config import STAFF_API_KEY
    # Should complete successfully (return None)
    await require_staff_key(x_staff_api_key=STAFF_API_KEY)


@pytest.mark.asyncio
async def test_require_staff_key_invalid():
    """Verify require_staff_key raises 403 for an incorrect key."""
    with pytest.raises(HTTPException) as exc_info:
        await require_staff_key(x_staff_api_key="wrong-key")
    assert exc_info.value.status_code == 403
    assert "Invalid or missing staff API key" in exc_info.value.detail


# ── Feature #99 — Cryptographic Hash Chain Validation ────────────────────────

def _make_entry(index: int, event_type: str, data: dict, prev_hash: str) -> dict:
    """Helper representing main.py audit block hash logic."""
    timestamp = "2026-07-17T12:00:00Z"
    payload_str = f"{prev_hash}|{index}|{event_type}|{json.dumps(data, sort_keys=True)}"
    entry_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    return {
        "index": index,
        "timestamp": timestamp,
        "event_type": event_type,
        "data": data,
        "prev_hash": prev_hash,
        "hash": entry_hash,
    }


def _verify_chain(audit_log: list) -> dict:
    """Helper representing main.py audit chain integrity logic."""
    if not audit_log:
        return {"valid": True, "tampered_entries": []}
    
    tampered = []
    prev_hash = AUDIT_GENESIS_HASH
    
    for entry in audit_log:
        payload_str = f"{prev_hash}|{entry['index']}|{entry['event_type']}|{json.dumps(entry['data'], sort_keys=True)}"
        expected = hashlib.sha256(payload_str.encode()).hexdigest()
        if entry["hash"] != expected or entry["prev_hash"] != prev_hash:
            tampered.append(entry["index"])
        prev_hash = entry["hash"]
    
    return {"valid": len(tampered) == 0, "tampered_entries": tampered}


def test_audit_chain_empty():
    result = _verify_chain([])
    assert result["valid"] is True
    assert result["tampered_entries"] == []


def test_audit_chain_single_valid():
    entry = _make_entry(0, "STARTUP", {"status": "ok"}, AUDIT_GENESIS_HASH)
    result = _verify_chain([entry])
    assert result["valid"] is True


def test_audit_chain_tamper():
    log = []
    prev = AUDIT_GENESIS_HASH
    for i in range(3):
        entry = _make_entry(i, f"EVENT_{i}", {"val": i}, prev)
        log.append(entry)
        prev = entry["hash"]
        
    # Attack: Retroactive tampering of event 1 data payload
    log[1]["data"]["val"] = 9999
    
    result = _verify_chain(log)
    assert result["valid"] is False
    assert 1 in result["tampered_entries"]


# ── Feature #44 — Offline Triage Classifier Tests ─────────────────────────────

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
