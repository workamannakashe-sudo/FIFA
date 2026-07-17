"""
app/config.py
~~~~~~~~~~~~~
Runtime configuration for SafePass 2026.

All settings are loaded from environment variables so the application
can be deployed to any environment without code changes.  Provide
values via a ``.env`` file (see ``.env.example`` at the repo root).
"""

from __future__ import annotations

import os

__all__ = [
    "HOST",
    "PORT",
    "DEBUG",
    "GEMINI_API_KEY",
    "RATE_LIMIT_WINDOW_SECONDS",
    "RATE_LIMIT_MAX_REQUESTS",
    "ALLOWED_ORIGINS",
    "STAFF_API_KEY",
    "MAX_REQUEST_BODY_KB",
]

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))
DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"

# ---------------------------------------------------------------------------
# AI / Gemini
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------
RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
RATE_LIMIT_MAX_REQUESTS: int = int(os.getenv("RATE_LIMIT_MAX", "100"))

# ---------------------------------------------------------------------------
# CORS  — comma-separated list of allowed origins
# Default: localhost only (never '*' in production)
# ---------------------------------------------------------------------------
_raw_origins: str = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
)
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Staff API Key — required in X-Staff-API-Key header for privileged endpoints
# Generate a strong random value and set it as an environment variable.
# Default is a dev-only placeholder that should NEVER be used in production.
# ---------------------------------------------------------------------------
STAFF_API_KEY: str = os.getenv("STAFF_API_KEY", "dev-only-change-me-in-production")

# ---------------------------------------------------------------------------
# Request Body Size Limit (KB)
# ---------------------------------------------------------------------------
MAX_REQUEST_BODY_KB: int = int(os.getenv("MAX_REQUEST_BODY_KB", "64"))
