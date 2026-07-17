import hashlib
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

from app.config import DEBUG, RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS
from app.engine import StadiumGraph
from app.mock_data import create_stadium_network, SCENARIOS
from app.security import SecurityMiddleware, sanitize_input, mask_pii_string
from app.ai_helper import generate_accessible_instructions, classify_incident, fan_chatbot_query

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("safepass.main")

# Initialize FastAPI App
app = FastAPI(
    title="SafePass 2026",
    description="Mission-Critical Crowd Dynamics and Evacuation Engine for FIFA 2026",
    version="1.0.0"
)

# Enable CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Apply custom Security and PII protection middleware
app.add_middleware(
    SecurityMiddleware,
    rate_limit_max=RATE_LIMIT_MAX_REQUESTS,
    rate_limit_window=RATE_LIMIT_WINDOW_SECONDS
)

# Active Stadium State
stadium_state: StadiumGraph = create_stadium_network()
current_scenario_name = "normal"
active_connections: List[WebSocket] = []

# ---------------------------------------------------------------------------
# Feature #99 — Tamper-Evident Audit Log with SHA-256 Hash Chain
# ---------------------------------------------------------------------------
# Each entry: {index, timestamp, event_type, data, hash}
# hash = SHA-256(previous_hash + str(index) + event_type + json(data))
AUDIT_LOG: List[dict] = []
_GENESIS_HASH = "0" * 64  # Sentinel hash for the first entry


def _append_audit_event(event_type: str, data: dict) -> dict:
    """Appends a new tamper-evident entry to the audit log chain."""
    index = len(AUDIT_LOG)
    prev_hash = AUDIT_LOG[-1]["hash"] if AUDIT_LOG else _GENESIS_HASH
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Create deterministic payload string for hashing
    payload_str = f"{prev_hash}|{index}|{event_type}|{json.dumps(data, sort_keys=True)}"
    entry_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    
    entry = {
        "index": index,
        "timestamp": timestamp,
        "event_type": event_type,
        "data": data,
        "prev_hash": prev_hash,
        "hash": entry_hash,
    }
    AUDIT_LOG.append(entry)
    logger.info(f"[AUDIT] #{index} {event_type} | hash: {entry_hash[:16]}...")
    return entry

# Pydantic schemas for requests
class FanRegistration(BaseModel):
    name: str = Field(..., description="Full Name of the Fan")
    email: str = Field(..., description="Contact Email Address")
    phone: str = Field(..., description="Mobile Number")
    ticket_id: str = Field(..., description="Ticket Identifier (e.g. TICKET-1234-US)")
    start_zone: str = Field(..., description="Assigned seat zone (e.g. Stand_North_Lower)")

class EdgeStateUpdate(BaseModel):
    source: str
    target: str
    occupancy: float

class EdgeBlockUpdate(BaseModel):
    source: str
    target: str
    is_blocked: bool

class IncidentReport(BaseModel):
    description: str = Field(..., description="Free-text description of the incident", min_length=5, max_length=1000)

class ChatMessage(BaseModel):
    message: str = Field(..., description="Fan question or message", min_length=1, max_length=500)
    lang: str = Field("en", description="ISO language code for response")
    history: List[dict] = Field(default_factory=list, description="Previous conversation turns [{role, text}]")

class AlertCommand(BaseModel):
    level: int = Field(..., description="Alert level: 1=App Notification, 2=PA+SMS, 3=Full Lockdown", ge=1, le=3)
    zone: str = Field(..., description="Affected stadium zone/node")
    message: str = Field(..., description="Alert message for broadcast", min_length=5, max_length=500)

# WebSockets Connection Manager
async def connect_websocket(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"WebSocket client connected. Active connections: {len(active_connections)}")

def disconnect_websocket(websocket: WebSocket):
    if websocket in active_connections:
        active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Active connections: {len(active_connections)}")

async def broadcast_updates(data: dict):
    for connection in active_connections:
        try:
            await connection.send_json(data)
        except Exception:
            # Client disconnected or failed to receive
            pass

# Helper to pack current stadium state response
def get_stadium_telemetry() -> dict:
    edges = []
    seen = set()
    for src in stadium_state.adj:
        for tgt, edge in stadium_state.adj[src].items():
            edge_id = tuple(sorted([src, tgt]))
            if edge_id in seen:
                continue
            seen.add(edge_id)
            edges.append({
                "source": src,
                "target": tgt,
                "length": edge.length,
                "capacity": edge.capacity,
                "occupancy": edge.occupancy,
                "is_blocked": edge.is_blocked,
                "effective_weight": edge.get_effective_weight()
            })
            
    # Calculate shortest path evacuation plans for all seating zones
    # Includes Sections (lower/upper), VIP suites, and Wheelchair zones
    seat_prefixes = ("Section_", "Stand_", "VIP_Suite", "Wheelchair_Zone")
    stands = [n for n in stadium_state.nodes if n.startswith(seat_prefixes)]
    routing_plans = {}
    for stand in stands:
        path, time_cost = stadium_state.calculate_evacuation_routes(stand)
        routing_plans[stand] = {
            "path": path,
            "evacuation_time_sec": round(time_cost, 2) if time_cost != float('inf') else -1
        }
        
    return {
        "scenario": current_scenario_name,
        "nodes": list(stadium_state.nodes),
        "exits": list(stadium_state.exits),
        "edges": edges,
        "routing_plans": routing_plans,
        "bottlenecks": stadium_state.get_bottlenecks(threshold=1.2),
        "timestamp": time.time()
    }


# REST Endpoints
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serves the main interactive dashboard."""
    # We will serve the embedded HTML directly to keep it self-contained and fast.
    try:
        with open("app/templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>SafePass 2026 Dashboard template not found!</h1>", status_code=404)

@app.get("/api/status")
async def get_status():
    """Returns the current stadium telemetry and graph representation."""
    return get_stadium_telemetry()

@app.get("/api/scenarios")
async def get_all_scenarios():
    """Lists the available simulation scenarios."""
    return [
        {"id": k, "title": v["title"], "description": v["description"], "incident": v["incident"]}
        for k, v in SCENARIOS.items()
    ]

@app.post("/api/scenarios/{scenario_name}")
async def load_scenario(scenario_name: str):
    """Loads a specific scenario preset into memory."""
    global current_scenario_name
    if scenario_name not in SCENARIOS:
        raise HTTPException(status_code=404, detail="Scenario not found")
        
    scenario = SCENARIOS[scenario_name]
    current_scenario_name = scenario_name
    
    # Reset stadium graph congestion/blockages
    stadium_state.reset_congestion()
    
    # Apply scenario blocked edges
    for src, tgt in scenario["blocked_edges"]:
        stadium_state.set_edge_blocked(src, tgt, True)
        
    # Apply scenario occupancies
    for (src, tgt), occupancy in scenario["occupancies"].items():
        stadium_state.update_edge_occupancy(src, tgt, occupancy)
        
    telemetry = get_stadium_telemetry()
    await broadcast_updates({"type": "state_update", "data": telemetry})
    
    logger.info(f"Loaded scenario '{scenario_name}'. Broadcasted update.")
    return {"status": "success", "scenario": scenario_name, "data": telemetry}

@app.post("/api/update_occupancy")
async def update_occupancy(data: EdgeStateUpdate):
    """Dynamically update occupancy of an edge for live congestion simulation."""
    if data.source not in stadium_state.nodes or data.target not in stadium_state.nodes:
        raise HTTPException(status_code=404, detail="One or both nodes not found")
        
    stadium_state.update_edge_occupancy(data.source, data.target, data.occupancy)
    telemetry = get_stadium_telemetry()
    await broadcast_updates({"type": "state_update", "data": telemetry})
    return {"status": "success", "data": telemetry}

@app.post("/api/block_edge")
async def block_edge(data: EdgeBlockUpdate):
    """Dynamically blocks/unblocks an edge for live incident management."""
    if data.source not in stadium_state.nodes or data.target not in stadium_state.nodes:
        raise HTTPException(status_code=404, detail="One or both nodes not found")
        
    stadium_state.set_edge_blocked(data.source, data.target, data.is_blocked)
    telemetry = get_stadium_telemetry()
    await broadcast_updates({"type": "state_update", "data": telemetry})
    return {"status": "success", "data": telemetry}

@app.get("/api/announcement")
async def get_announcement(
    zone: str = Query(..., description="Zone requesting evacuation routing instructions"),
    lang: str = Query("en", description="Target ISO language code (e.g. es, fr, ar, ja)")
):
    """
    Computes shortest evacuation route from the requested zone and generates
    multimodal translated audio/text instructions. Uses Gemini with local fallbacks.
    """
    # Sanitize query parameters to prevent XSS
    zone = sanitize_input(zone)
    lang = sanitize_input(lang)
    
    if zone not in stadium_state.nodes:
        raise HTTPException(status_code=404, detail="Stadium zone not found")
        
    path, time_cost = stadium_state.calculate_evacuation_routes(zone)
    
    if time_cost == float('inf') or not path:
        msg = await generate_accessible_instructions("blocked", zone, "All Exits", lang)
        return {
            "path": [],
            "evacuation_time_sec": -1,
            "instruction": msg,
            "status": "danger"
        }
        
    target_exit = path[-1]
    
    # Classify condition based on bottleneck checks
    event_type = "evacuate"
    # Find if any edge on the path has high congestion (occupancy > capacity)
    is_congested = False
    for i in range(len(path) - 1):
        edge = stadium_state.adj[path[i]][path[i+1]]
        if edge.capacity > 0 and edge.occupancy >= edge.capacity:
            is_congested = True
            break
            
    if is_congested:
        event_type = "congestion"
        
    msg = await generate_accessible_instructions(event_type, zone, target_exit, lang)
    
    return {
        "path": path,
        "evacuation_time_sec": round(time_cost, 2),
        "instruction": msg,
        "status": "warning" if is_congested else "success"
    }

@app.post("/api/register_fan")
async def register_fan(fan: FanRegistration):
    """
    Simulates a fan registration for customized egress routing alerts.
    Demonstrates XSS input sanitization and PII masking.
    """
    # 1. Sanitize Inputs
    sanitized_name = sanitize_input(fan.name)
    sanitized_email = sanitize_input(fan.email)
    sanitized_phone = sanitize_input(fan.phone)
    sanitized_ticket = sanitize_input(fan.ticket_id)
    sanitized_zone = sanitize_input(fan.start_zone)
    
    if sanitized_zone not in stadium_state.nodes:
        raise HTTPException(status_code=404, detail="Assigned seating zone not found")
        
    # Log incoming request showing before/after PII masking in logger
    raw_log = f"Fan Registration Attempt: Name={fan.name}, Email={fan.email}, Phone={fan.phone}, Ticket={fan.ticket_id}, Zone={fan.start_zone}"
    masked_log = mask_pii_string(raw_log)
    logger.info(f"[SECURITY MASKED LOG] {masked_log}")
    
    # Calculate personalized route for response
    path, time_cost = stadium_state.calculate_evacuation_routes(sanitized_zone)
    
    # Return masked confirmation to client
    return {
        "status": "success",
        "fan": {
            "name": sanitized_name,
            "masked_email": mask_pii_string(sanitized_email),
            "masked_phone": mask_pii_string(sanitized_phone),
            "masked_ticket": mask_pii_string(sanitized_ticket),
            "zone": sanitized_zone
        },
        "egress_plan": {
            "path": path,
            "estimated_exit_time_sec": round(time_cost, 2) if time_cost != float('inf') else -1
        }
    }


@app.get("/api/crush_risk")
async def get_crush_risk():
    """
    Crowd Crush Prevention Algorithm (Feature #93).
    Analyzes all corridors using the LWR fluid-dynamics model to detect
    crush conditions: density >= 80% AND effective weight >= 3x base.
    Returns severity level (LOW / MODERATE / CRITICAL) and affected zones.
    """
    risk = stadium_state.get_crush_risk_zones()
    # Automatically log CRITICAL events to the audit chain
    if risk["level"] in ("MODERATE", "CRITICAL"):
        _append_audit_event(
            event_type="CRUSH_RISK_DETECTED",
            data={"level": risk["level"], "zone_count": risk["zone_count"], "summary": risk["summary"]}
        )
    return risk


@app.post("/api/triage")
async def triage_incident(report: IncidentReport):
    """
    AI Incident Triage Classifier (Feature #44).
    Accepts a free-text incident description. Uses Gemini to return a structured
    classification: {category, severity 1-5, recommended_action, affected_zones}.
    Falls back to offline keyword classifier if Gemini is unavailable.
    """
    sanitized_description = sanitize_input(report.description)
    result = await classify_incident(sanitized_description)
    
    # Audit every incident triage request
    _append_audit_event(
        event_type="INCIDENT_TRIAGE",
        data={"category": result.get("category"), "severity": result.get("severity"),
              "description_len": len(sanitized_description)}
    )
    return result


@app.post("/api/chat")
async def chatbot(message: ChatMessage):
    """
    RAG-Powered Fan Chatbot (Feature #23).
    Answers fan questions using Gemini with a curated stadium knowledge base
    as the in-prompt retrieval context. Supports multilingual responses and
    maintains conversation history for context. Offline fallback via keyword matching.
    """
    sanitized_msg = sanitize_input(message.message)
    sanitized_lang = sanitize_input(message.lang)
    response_text = await fan_chatbot_query(
        question=sanitized_msg,
        lang=sanitized_lang,
        conversation_history=message.history
    )
    return {"response": response_text, "lang": sanitized_lang}


@app.post("/api/alert")
async def dispatch_alert(alert: AlertCommand):
    """
    Emergency Multi-Level Alert Escalation Protocol (Feature #91).
    Level 1: App notification via WebSocket broadcast to all connected fans.
    Level 2: Simulated PA/SMS trigger + WebSocket broadcast.
    Level 3: Full Lockdown — blocks all edges in/out of affected zone + broadcast.
    All alert events are immutably written to the tamper-evident audit log.
    """
    sanitized_zone = sanitize_input(alert.zone)
    sanitized_message = sanitize_input(alert.message)
    
    if sanitized_zone not in stadium_state.nodes and alert.level == 3:
        raise HTTPException(status_code=404, detail=f"Zone '{sanitized_zone}' not found in stadium graph")
    
    level_labels = {1: "APP_NOTIFICATION", 2: "PA_AND_SMS_TRIGGER", 3: "FULL_LOCKDOWN"}
    event_type = f"ALERT_L{alert.level}_{level_labels[alert.level]}"
    
    lockdown_details = {}
    
    # Level 3: Physically block all edges connected to the affected zone
    if alert.level == 3 and sanitized_zone in stadium_state.nodes:
        stadium_state.set_node_blocked(sanitized_zone, True)
        lockdown_details["locked_zone"] = sanitized_zone
        lockdown_details["action"] = "All corridors leading to/from this zone have been blocked in the routing engine."
        
        # Broadcast updated telemetry immediately
        telemetry = get_stadium_telemetry()
        await broadcast_updates({"type": "state_update", "data": telemetry})
    
    # Broadcast alert notification to all WebSocket subscribers
    alert_payload = {
        "type": "emergency_alert",
        "data": {
            "level": alert.level,
            "zone": sanitized_zone,
            "message": sanitized_message,
            "event_type": event_type,
            "timestamp": time.time(),
            **lockdown_details
        }
    }
    await broadcast_updates(alert_payload)
    
    # Write to tamper-evident audit log
    audit_entry = _append_audit_event(
        event_type=event_type,
        data={"level": alert.level, "zone": sanitized_zone, "message": sanitized_message, **lockdown_details}
    )
    
    logger.warning(f"[ALERT L{alert.level}] Zone: {sanitized_zone} | {sanitized_message}")
    return {
        "status": "dispatched",
        "level": alert.level,
        "event_type": event_type,
        "zone": sanitized_zone,
        "audit_entry_index": audit_entry["index"],
        **lockdown_details
    }


@app.get("/api/audit_log")
async def get_audit_log(limit: int = Query(50, ge=1, le=500)):
    """
    Tamper-Evident Audit Log (Feature #99).
    Returns the most recent `limit` entries from the append-only audit event chain.
    Each entry contains a SHA-256 hash of (prev_hash + index + event_type + data).
    """
    recent = AUDIT_LOG[-limit:] if len(AUDIT_LOG) > limit else AUDIT_LOG
    return {"total_entries": len(AUDIT_LOG), "entries": recent}


@app.get("/api/audit_verify")
async def verify_audit_chain():
    """
    Audit Chain Integrity Verification (Feature #99).
    Re-computes the SHA-256 hash for every entry and verifies it matches the stored hash,
    and that each entry's prev_hash matches the previous entry's hash.
    Returns {valid: bool, verified_count: int, tampered_entries: []}.
    """
    if not AUDIT_LOG:
        return {"valid": True, "verified_count": 0, "tampered_entries": [], "message": "Audit log is empty."}
    
    tampered = []
    prev_hash = _GENESIS_HASH
    
    for entry in AUDIT_LOG:
        # Recompute hash
        payload_str = f"{prev_hash}|{entry['index']}|{entry['event_type']}|{json.dumps(entry['data'], sort_keys=True)}"
        expected_hash = hashlib.sha256(payload_str.encode()).hexdigest()
        
        if entry["hash"] != expected_hash or entry["prev_hash"] != prev_hash:
            tampered.append({"index": entry["index"], "event_type": entry["event_type"]})
        
        prev_hash = entry["hash"]
    
    return {
        "valid": len(tampered) == 0,
        "verified_count": len(AUDIT_LOG),
        "tampered_entries": tampered,
        "chain_tip_hash": AUDIT_LOG[-1]["hash"][:16] + "..." if AUDIT_LOG else None,
        "message": "Chain integrity verified — no tampering detected." if not tampered else f"{len(tampered)} entry/entries have been tampered with!"
    }


# WebSocket endpoint for real-time telemetry stream
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connect_websocket(websocket)
    # Send current state immediately on connection
    try:
        await websocket.send_json({"type": "state_update", "data": get_stadium_telemetry()})
        while True:
            # Keep connection alive, listen for messages
            data = await websocket.receive_text()
            # In dynamic mode, clients could send actions, but we just echo/keepalive
            await websocket.send_json({"type": "pong", "time": time.time()})
    except WebSocketDisconnect:
        disconnect_websocket(websocket)
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        disconnect_websocket(websocket)
