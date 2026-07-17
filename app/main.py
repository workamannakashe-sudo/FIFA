"""
app/main.py
~~~~~~~~~~~
FastAPI application entry point for SafePass 2026.

Exposes REST and WebSocket endpoints for:
- Real-time stadium telemetry (WebSocket fan-out with background push task)
- Congestion-aware evacuation routing (cached Dijkstra)
- Crowd crush prevention analytics
- AI incident triage (Gemini + offline fallback)
- RAG-powered fan chatbot
- Multi-level emergency alert escalation
- Tamper-evident SHA-256 audit log
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from copy import copy
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from app.config import (
    ALLOWED_ORIGINS,
    DEBUG,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)
from app.constants import AUDIT_GENESIS_HASH, SEATING_NODE_PREFIXES, SUPPORTED_ISO_LANGS
from app.engine import StadiumGraph
from app.mock_data import SCENARIOS, create_stadium_network
from app.security import (
    SecurityMiddleware,
    mask_pii_string,
    require_staff_key,
    sanitize_input,
)
from app.ai_helper import classify_incident, fan_chatbot_query, generate_accessible_instructions

__all__ = ["app"]

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("safepass.main")

# ---------------------------------------------------------------------------
# Telemetry cache — invalidated on every state mutation
# ---------------------------------------------------------------------------
_telemetry_cache: Optional[Dict] = None
_telemetry_cache_scenario: Optional[str] = None  # invalidate on scenario change


def _invalidate_cache() -> None:
    """Mark the telemetry cache as stale."""
    global _telemetry_cache, _telemetry_cache_scenario
    _telemetry_cache = None
    _telemetry_cache_scenario = None


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
stadium_state: StadiumGraph = create_stadium_network()
current_scenario_name: str = "normal"
_active_connections: Set[WebSocket] = set()

# ---------------------------------------------------------------------------
# Tamper-Evident Audit Log (Feature #99)
# SHA-256 hash chain: hash[i] = SHA-256(prev_hash | index | event_type | json(data))
# ---------------------------------------------------------------------------
AUDIT_LOG: List[Dict] = []


def _append_audit_event(event_type: str, data: Dict) -> Dict:
    """
    Append a new entry to the tamper-evident audit chain.

    Each entry's hash commits to the previous entry's hash, creating a
    blockchain-style linked chain that detects any retroactive modification.

    Parameters
    ----------
    event_type : str
        Short identifier for the class of event (e.g. ``"SCENARIO_LOAD"``).
    data : dict
        Structured payload associated with the event.

    Returns
    -------
    dict
        The newly appended audit entry.
    """
    index = len(AUDIT_LOG)
    prev_hash = AUDIT_LOG[-1]["hash"] if AUDIT_LOG else AUDIT_GENESIS_HASH
    timestamp = datetime.now(timezone.utc).isoformat()
    payload_str = (
        f"{prev_hash}|{index}|{event_type}|{json.dumps(data, sort_keys=True)}"
    )
    entry_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    entry: Dict = {
        "index": index,
        "timestamp": timestamp,
        "event_type": event_type,
        "data": data,
        "prev_hash": prev_hash,
        "hash": entry_hash,
    }
    AUDIT_LOG.append(entry)
    logger.info("[AUDIT] #%d %s | hash: %s…", index, event_type, entry_hash[:16])
    return entry


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

async def _ws_connect(websocket: WebSocket) -> None:
    await websocket.accept()
    _active_connections.add(websocket)
    logger.info("WS connected — %d active", len(_active_connections))


def _ws_disconnect(websocket: WebSocket) -> None:
    _active_connections.discard(websocket)
    logger.info("WS disconnected — %d active", len(_active_connections))


async def _broadcast(payload: Dict) -> None:
    """
    Fan-out *payload* to all active WebSocket clients.

    Iterates over a snapshot copy so that disconnections during broadcast
    do not cause mutation-during-iteration errors.
    """
    dead: List[WebSocket] = []
    for ws in copy(_active_connections):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _active_connections.discard(ws)


# ---------------------------------------------------------------------------
# Telemetry helper
# ---------------------------------------------------------------------------

def get_stadium_telemetry() -> Dict:
    """
    Build the full stadium state payload for REST/WebSocket consumers.

    Results are cached in ``_telemetry_cache`` and only recomputed when the
    cache has been invalidated by a state mutation (scenario load, occupancy
    update, edge block, alert lockdown).

    Returns
    -------
    dict
        Serialisable snapshot of the current stadium graph state including
        edges, routing plans, bottlenecks, and scenario metadata.
    """
    global _telemetry_cache

    if _telemetry_cache is not None:
        return _telemetry_cache

    edges: List[Dict] = []
    seen: Set[Tuple[str, str]] = set()
    for src, neighbours in stadium_state.adj.items():
        for tgt, edge in neighbours.items():
            edge_id = (min(src, tgt), max(src, tgt))
            if edge_id in seen:
                continue
            seen.add(edge_id)
            ew = edge.get_effective_weight()
            edges.append(
                {
                    "source": src,
                    "target": tgt,
                    "length": edge.length,
                    "capacity": edge.capacity,
                    "occupancy": edge.occupancy,
                    "is_blocked": edge.is_blocked,
                    "effective_weight": ew if ew != float("inf") else -1,
                }
            )

    seating_nodes = [
        n for n in stadium_state.nodes if n.startswith(SEATING_NODE_PREFIXES)
    ]
    routing_plans: Dict[str, Dict] = {}
    for node in seating_nodes:
        path, cost = stadium_state.calculate_evacuation_routes(node)
        routing_plans[node] = {
            "path": path,
            "evacuation_time_sec": round(cost, 2) if cost != float("inf") else -1,
        }

    _telemetry_cache = {
        "scenario": current_scenario_name,
        "nodes": sorted(stadium_state.nodes),
        "exits": sorted(stadium_state.exits),
        "edges": edges,
        "routing_plans": routing_plans,
        "bottlenecks": stadium_state.get_bottlenecks(),
        "timestamp": time.time(),
    }
    return _telemetry_cache


# ---------------------------------------------------------------------------
# Background task — periodic telemetry push
# ---------------------------------------------------------------------------

async def _periodic_telemetry_push(interval_seconds: float = 2.0) -> None:
    """Push fresh telemetry to all WebSocket subscribers every *interval_seconds*."""
    while True:
        await asyncio.sleep(interval_seconds)
        if _active_connections:
            await _broadcast({"type": "state_update", "data": get_stadium_telemetry()})


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Startup: seed audit log and launch background push task."""
    _append_audit_event("SYSTEM_START", {"version": application.version})
    asyncio.create_task(_periodic_telemetry_push())
    logger.info("SafePass 2026 started — background telemetry push active.")
    yield
    logger.info("SafePass 2026 shutdown.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SafePass 2026",
    description=(
        "Mission-Critical Stadium Intelligence & Fan Experience Platform "
        "for the FIFA World Cup 2026. Powered by congestion-aware Dijkstra routing, "
        "Google Gemini AI, and a SHA-256 tamper-evident audit chain."
    ),
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Staff-API-Key"],
)
app.add_middleware(
    SecurityMiddleware,
    rate_limit_max=RATE_LIMIT_MAX_REQUESTS,
    rate_limit_window=RATE_LIMIT_WINDOW_SECONDS,
)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class FanRegistration(BaseModel):
    """Fan self-registration payload for personalised egress routing."""

    name: str = Field(..., min_length=2, max_length=120, description="Full name")
    email: str = Field(..., max_length=254, description="Contact email address")
    phone: str = Field(..., max_length=20, description="Mobile phone number")
    ticket_id: str = Field(..., max_length=30, description="Ticket ID (e.g. TKT-1049-US)")
    start_zone: str = Field(..., max_length=60, description="Assigned seating zone node name")


class EdgeStateUpdate(BaseModel):
    """Payload for dynamic occupancy updates via the sandbox editor."""

    source: str = Field(..., max_length=60)
    target: str = Field(..., max_length=60)
    occupancy: float = Field(..., ge=0.0, le=10_000.0)


class EdgeBlockUpdate(BaseModel):
    """Payload for toggling edge blockage state."""

    source: str = Field(..., max_length=60)
    target: str = Field(..., max_length=60)
    is_blocked: bool


class IncidentReport(BaseModel):
    """Free-text incident description submitted by stadium staff."""

    description: str = Field(
        ...,
        min_length=5,
        max_length=1_000,
        description="Plain-language description of the incident",
    )


class ChatMessage(BaseModel):
    """Fan chatbot query."""

    message: str = Field(..., min_length=1, max_length=500)
    lang: str = Field("en", min_length=2, max_length=5, description="ISO 639-1 language code")
    history: List[Dict] = Field(
        default_factory=list,
        description="Last N conversation turns [{role, text}]",
        max_length=10,
    )

    @field_validator("lang")
    @classmethod
    def validate_lang(cls, v: str) -> str:
        code = v.strip().lower()[:2]
        if code not in SUPPORTED_ISO_LANGS:
            raise ValueError(f"Unsupported language code '{v}'. Supported: {sorted(SUPPORTED_ISO_LANGS)}")
        return code


class AlertCommand(BaseModel):
    """Emergency alert dispatch payload (staff only)."""

    level: int = Field(
        ..., ge=1, le=3,
        description="1=App Notification, 2=PA+SMS Trigger, 3=Full Zone Lockdown",
    )
    zone: str = Field(..., min_length=2, max_length=60, description="Affected zone node name")
    message: str = Field(..., min_length=5, max_length=500, description="Alert message text")


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def get_dashboard() -> HTMLResponse:
    """Serve the interactive HTML dashboard."""
    try:
        with open("app/templates/index.html", encoding="utf-8") as fh:
            return HTMLResponse(content=fh.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>SafePass 2026: dashboard template not found.</h1>",
            status_code=404,
        )


@app.get("/api/status", summary="Current stadium telemetry snapshot")
async def get_status() -> Dict:
    """Return the cached stadium graph state (edges, routing plans, bottlenecks)."""
    return get_stadium_telemetry()


@app.get("/api/scenarios", summary="List available simulation scenarios")
async def list_scenarios() -> List[Dict]:
    """List all preloaded crowd scenarios available for demonstration."""
    return [
        {
            "id": k,
            "title": v["title"],
            "description": v["description"],
            "incident": v["incident"],
        }
        for k, v in SCENARIOS.items()
    ]


@app.post("/api/scenarios/{scenario_name}", summary="Load a simulation scenario")
async def load_scenario(scenario_name: str) -> Dict:
    """
    Load a named crowd scenario into the routing engine and broadcast the
    updated state to all connected WebSocket clients.
    """
    global current_scenario_name
    if scenario_name not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_name}' not found.")

    scenario = SCENARIOS[scenario_name]
    current_scenario_name = scenario_name
    stadium_state.reset_congestion()

    for src, tgt in scenario["blocked_edges"]:
        stadium_state.set_edge_blocked(src, tgt, True)
    for (src, tgt), occ in scenario["occupancies"].items():
        stadium_state.update_edge_occupancy(src, tgt, occ)

    _invalidate_cache()
    telemetry = get_stadium_telemetry()
    await _broadcast({"type": "state_update", "data": telemetry})
    _append_audit_event("SCENARIO_LOAD", {"scenario": scenario_name})
    logger.info("Scenario '%s' loaded.", scenario_name)
    return {"status": "success", "scenario": scenario_name, "data": telemetry}


@app.post("/api/update_occupancy", summary="Update corridor occupancy (sandbox)")
async def update_occupancy(data: EdgeStateUpdate) -> Dict:
    """Dynamically set the occupancy of a corridor for live congestion simulation."""
    if data.source not in stadium_state.nodes or data.target not in stadium_state.nodes:
        raise HTTPException(status_code=404, detail="One or both nodes not found.")
    stadium_state.update_edge_occupancy(data.source, data.target, data.occupancy)
    _invalidate_cache()
    telemetry = get_stadium_telemetry()
    await _broadcast({"type": "state_update", "data": telemetry})
    return {"status": "success", "data": telemetry}


@app.post("/api/block_edge", summary="Block or unblock a corridor (sandbox)")
async def block_edge(data: EdgeBlockUpdate) -> Dict:
    """Toggle the blocked state of a specific corridor for incident management."""
    if data.source not in stadium_state.nodes or data.target not in stadium_state.nodes:
        raise HTTPException(status_code=404, detail="One or both nodes not found.")
    stadium_state.set_edge_blocked(data.source, data.target, data.is_blocked)
    _invalidate_cache()
    telemetry = get_stadium_telemetry()
    await _broadcast({"type": "state_update", "data": telemetry})
    return {"status": "success", "data": telemetry}


@app.get("/api/announcement", summary="Multilingual egress instruction for a zone")
async def get_announcement(
    zone: str = Query(..., max_length=60, description="Zone requesting evacuation instructions"),
    lang: str = Query("en", max_length=5, description="ISO 639-1 language code"),
) -> Dict:
    """
    Compute the shortest evacuation route from *zone* and return a translated,
    screen-reader-friendly instruction string via Gemini AI (with offline fallback).
    """
    zone = sanitize_input(zone)
    lang = sanitize_input(lang).strip().lower()[:2]

    if zone not in stadium_state.nodes:
        raise HTTPException(status_code=404, detail="Stadium zone not found.")

    path, time_cost = stadium_state.calculate_evacuation_routes(zone)

    if time_cost == float("inf") or not path:
        msg = await generate_accessible_instructions("blocked", zone, "All Exits", lang)
        return {"path": [], "evacuation_time_sec": -1, "instruction": msg, "status": "danger"}

    target_exit = path[-1]
    is_congested = any(
        (
            stadium_state.adj[path[i]][path[i + 1]].capacity > 0
            and stadium_state.adj[path[i]][path[i + 1]].occupancy
            >= stadium_state.adj[path[i]][path[i + 1]].capacity
        )
        for i in range(len(path) - 1)
        if path[i + 1] in stadium_state.adj.get(path[i], {})
    )

    event_type = "congestion" if is_congested else "evacuate"
    msg = await generate_accessible_instructions(event_type, zone, target_exit, lang)
    return {
        "path": path,
        "evacuation_time_sec": round(time_cost, 2),
        "instruction": msg,
        "status": "warning" if is_congested else "success",
    }


@app.post("/api/register_fan", summary="Register fan and receive personalised egress plan")
async def register_fan(fan: FanRegistration) -> Dict:
    """
    Accept fan registration, apply XSS sanitisation, mask PII in logs,
    and return a personalised evacuation route.
    """
    sanitized_name = sanitize_input(fan.name)
    sanitized_email = sanitize_input(fan.email)
    sanitized_phone = sanitize_input(fan.phone)
    sanitized_ticket = sanitize_input(fan.ticket_id)
    sanitized_zone = sanitize_input(fan.start_zone)

    if sanitized_zone not in stadium_state.nodes:
        raise HTTPException(status_code=404, detail="Assigned seating zone not found.")

    raw_log = (
        f"Fan Registration: name={fan.name}, email={fan.email}, "
        f"phone={fan.phone}, ticket={fan.ticket_id}, zone={fan.start_zone}"
    )
    logger.info("[SECURITY] %s", mask_pii_string(raw_log))

    path, cost = stadium_state.calculate_evacuation_routes(sanitized_zone)
    return {
        "status": "success",
        "fan": {
            "name": sanitized_name,
            "masked_email": mask_pii_string(sanitized_email),
            "masked_phone": mask_pii_string(sanitized_phone),
            "masked_ticket": mask_pii_string(sanitized_ticket),
            "zone": sanitized_zone,
        },
        "egress_plan": {
            "path": path,
            "estimated_exit_time_sec": round(cost, 2) if cost != float("inf") else -1,
        },
    }


@app.get("/api/crush_risk", summary="Crowd crush risk assessment (Feature #93)")
async def get_crush_risk() -> Dict:
    """
    Analyse all corridors with the LWR fluid-dynamics model.
    Returns severity level (LOW / MODERATE / CRITICAL) and affected zones.
    MODERATE and CRITICAL events are automatically written to the audit chain.
    """
    risk = stadium_state.get_crush_risk_zones()
    if risk["level"] in ("MODERATE", "CRITICAL"):
        _append_audit_event(
            "CRUSH_RISK_DETECTED",
            {
                "level": risk["level"],
                "zone_count": risk["zone_count"],
                "summary": risk["summary"],
            },
        )
    return risk


@app.post(
    "/api/triage",
    summary="AI incident triage classifier (Feature #44)",
    dependencies=[Depends(require_staff_key)],
)
async def triage_incident(report: IncidentReport) -> Dict:
    """
    Classify a free-text incident report using Gemini AI.

    Returns ``{category, severity 1-5, recommended_action, affected_zones}``.
    Falls back to offline keyword classification when Gemini is unavailable.

    **Requires** ``X-Staff-API-Key`` header.
    """
    sanitized = sanitize_input(report.description)
    result = await classify_incident(sanitized)
    _append_audit_event(
        "INCIDENT_TRIAGE",
        {
            "category": result.get("category"),
            "severity": result.get("severity"),
            "description_len": len(sanitized),
        },
    )
    return result


@app.post("/api/chat", summary="RAG-powered fan chatbot (Feature #23)")
async def chatbot(message: ChatMessage) -> Dict:
    """
    Answer fan questions using Gemini with the stadium knowledge base as
    in-prompt RAG context.  Supports multilingual responses and conversation
    history.  Falls back to keyword-matching when offline.
    """
    sanitized_msg = sanitize_input(message.message)
    response_text = await fan_chatbot_query(
        question=sanitized_msg,
        lang=message.lang,
        conversation_history=message.history,
    )
    return {"response": response_text, "lang": message.lang}


@app.post(
    "/api/alert",
    summary="Emergency multi-level alert escalation (Feature #91)",
    dependencies=[Depends(require_staff_key)],
)
async def dispatch_alert(alert: AlertCommand) -> Dict:
    """
    Dispatch a tiered emergency alert.

    - **Level 1**: WebSocket broadcast (app notification).
    - **Level 2**: Simulated PA / SMS trigger + WebSocket broadcast.
    - **Level 3**: Full zone lockdown — blocks all corridors to/from the
      affected zone in the routing engine, then broadcasts.

    All events are immutably written to the tamper-evident audit log.

    **Requires** ``X-Staff-API-Key`` header.
    """
    sanitized_zone = sanitize_input(alert.zone)
    sanitized_message = sanitize_input(alert.message)

    if alert.level == 3 and sanitized_zone not in stadium_state.nodes:
        raise HTTPException(
            status_code=404,
            detail=f"Zone '{sanitized_zone}' not found in stadium graph.",
        )

    level_labels = {
        1: "APP_NOTIFICATION",
        2: "PA_AND_SMS_TRIGGER",
        3: "FULL_LOCKDOWN",
    }
    event_type = f"ALERT_L{alert.level}_{level_labels[alert.level]}"
    lockdown_details: Dict = {}

    if alert.level == 3 and sanitized_zone in stadium_state.nodes:
        stadium_state.set_node_blocked(sanitized_zone, True)
        _invalidate_cache()
        lockdown_details = {
            "locked_zone": sanitized_zone,
            "action": "All corridors to/from this zone are now blocked in the routing engine.",
        }
        await _broadcast({"type": "state_update", "data": get_stadium_telemetry()})

    await _broadcast(
        {
            "type": "emergency_alert",
            "data": {
                "level": alert.level,
                "zone": sanitized_zone,
                "message": sanitized_message,
                "event_type": event_type,
                "timestamp": time.time(),
                **lockdown_details,
            },
        }
    )

    audit_entry = _append_audit_event(
        event_type,
        {
            "level": alert.level,
            "zone": sanitized_zone,
            "message": sanitized_message,
            **lockdown_details,
        },
    )
    logger.warning("[ALERT L%d] Zone=%s | %s", alert.level, sanitized_zone, sanitized_message)
    return {
        "status": "dispatched",
        "level": alert.level,
        "event_type": event_type,
        "zone": sanitized_zone,
        "audit_entry_index": audit_entry["index"],
        **lockdown_details,
    }


@app.get("/api/audit_log", summary="Retrieve tamper-evident audit log (Feature #99)")
async def get_audit_log(
    limit: int = Query(50, ge=1, le=500, description="Maximum entries to return"),
) -> Dict:
    """Return the most recent *limit* entries from the append-only audit chain."""
    recent = AUDIT_LOG[-limit:]
    return {"total_entries": len(AUDIT_LOG), "entries": recent}


@app.get("/api/audit_verify", summary="Verify SHA-256 audit chain integrity")
async def verify_audit_chain() -> Dict:
    """
    Re-compute the SHA-256 hash for every audit entry and verify the chain.

    Returns ``{valid: bool, verified_count: int, tampered_entries: list}``.
    Any mismatch indicates retroactive tampering.
    """
    if not AUDIT_LOG:
        return {
            "valid": True,
            "verified_count": 0,
            "tampered_entries": [],
            "message": "Audit log is empty.",
        }

    tampered: List[Dict] = []
    prev_hash = AUDIT_GENESIS_HASH

    for entry in AUDIT_LOG:
        payload_str = (
            f"{prev_hash}|{entry['index']}|{entry['event_type']}"
            f"|{json.dumps(entry['data'], sort_keys=True)}"
        )
        expected = hashlib.sha256(payload_str.encode()).hexdigest()
        if entry["hash"] != expected or entry["prev_hash"] != prev_hash:
            tampered.append({"index": entry["index"], "event_type": entry["event_type"]})
        prev_hash = entry["hash"]

    ok = len(tampered) == 0
    return {
        "valid": ok,
        "verified_count": len(AUDIT_LOG),
        "tampered_entries": tampered,
        "chain_tip_hash": AUDIT_LOG[-1]["hash"][:16] + "…" if AUDIT_LOG else None,
        "message": (
            "Chain integrity verified — no tampering detected."
            if ok
            else f"{len(tampered)} entry/entries appear tampered!"
        ),
    }


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    Real-time telemetry WebSocket.

    On connect, immediately pushes the current stadium state.
    Thereafter the background task pushes updates every 2 seconds.
    Clients may send any message to receive a ``pong`` keepalive.
    """
    await _ws_connect(websocket)
    try:
        await websocket.send_json({"type": "state_update", "data": get_stadium_telemetry()})
        while True:
            await websocket.receive_text()
            await websocket.send_json({"type": "pong", "time": time.time()})
    except WebSocketDisconnect:
        _ws_disconnect(websocket)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        _ws_disconnect(websocket)
