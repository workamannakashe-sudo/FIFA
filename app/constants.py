"""
app/constants.py
~~~~~~~~~~~~~~~~
Centralised constants for SafePass 2026.

All magic numbers, threshold values, and configuration literals are
declared here so they can be imported, tested, and changed in one place.
"""

from __future__ import annotations

__all__ = [
    # LWR Crowd-Dynamics Model
    "LWR_ALPHA",
    "LWR_BETA",
    "LWR_MAX_RATIO_CAP",
    # Crush-Risk Thresholds
    "CRUSH_DENSITY_THRESHOLD",
    "CRUSH_WEIGHT_MULTIPLIER",
    "CRUSH_MODERATE_MAX_ZONES",
    # Bottleneck Detection
    "BOTTLENECK_OCCUPANCY_THRESHOLD",
    # Audit Log
    "AUDIT_GENESIS_HASH",
    # Routing
    "SEATING_NODE_PREFIXES",
    # API / Middleware
    "SUPPORTED_ISO_LANGS",
    "MAX_BODY_BYTES",
]

# ---------------------------------------------------------------------------
# LWR (Lighthill-Whitham-Richards) Crowd-Dynamics Model Parameters
# Weight formula: base_length × (1 + LWR_ALPHA × (density_ratio ^ LWR_BETA))
# ---------------------------------------------------------------------------
LWR_ALPHA: float = 2.5          # Congestion sensitivity coefficient
LWR_BETA: int = 2               # Quadratic congestion exponent
LWR_MAX_RATIO_CAP: float = 3.0  # Density ratio is capped at this value to prevent infinity

# ---------------------------------------------------------------------------
# Crowd Crush Prevention (Feature #93)
# Based on Fruin Level of Service E/F boundary criteria
# ---------------------------------------------------------------------------
CRUSH_DENSITY_THRESHOLD: float = 0.80   # >= 80 % occupancy / capacity
CRUSH_WEIGHT_MULTIPLIER: float = 3.0    # effective_weight >= 3 × base_length
CRUSH_MODERATE_MAX_ZONES: int = 2       # Zones ≤ this → MODERATE; above → CRITICAL

# ---------------------------------------------------------------------------
# Bottleneck Detection
# ---------------------------------------------------------------------------
BOTTLENECK_OCCUPANCY_THRESHOLD: float = 1.2  # occupancy / capacity ratio to flag a corridor

# ---------------------------------------------------------------------------
# Tamper-Evident Audit Log (Feature #99)
# ---------------------------------------------------------------------------
AUDIT_GENESIS_HASH: str = "0" * 64  # Sentinel SHA-256 hex string for genesis block

# ---------------------------------------------------------------------------
# Routing / Telemetry
# ---------------------------------------------------------------------------
#: Node name prefixes that identify seating areas and should receive routing plans
SEATING_NODE_PREFIXES: tuple[str, ...] = (
    "Section_",
    "Stand_",
    "VIP_Suite",
    "Wheelchair_Zone",
)

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
#: ISO 639-1 codes supported by the AI helper and chatbot
SUPPORTED_ISO_LANGS: frozenset[str] = frozenset(
    {"en", "es", "fr", "pt", "ar", "ja", "de", "zh", "hi", "ko"}
)

# ---------------------------------------------------------------------------
# API Security
# ---------------------------------------------------------------------------
#: Maximum accepted request body size in bytes (64 KB)
MAX_BODY_BYTES: int = 64 * 1024
