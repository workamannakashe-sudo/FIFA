"""
app/security.py
~~~~~~~~~~~~~~~
Security middleware and utilities for SafePass 2026.

Responsibilities
----------------
- **Rate limiting** — per-IP sliding window counter (in-memory).
- **Input sanitisation** — XSS / injection pattern removal.
- **PII masking** — email, phone, ticket-ID redaction in log strings.
- **Security headers** — OWASP-recommended HTTP response headers.
- **Staff authentication** — API-key dependency for privileged endpoints.
- **Request body size limit** — reject oversized payloads.
"""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Dict, Tuple

from fastapi import Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import MAX_REQUEST_BODY_KB, STAFF_API_KEY
from app.constants import MAX_BODY_BYTES

__all__ = [
    "SecurityMiddleware",
    "sanitize_input",
    "mask_pii_string",
    "require_staff_key",
]

logger = logging.getLogger("safepass.security")

# ---------------------------------------------------------------------------
# Compiled regex patterns — compiled once at module load for efficiency
# ---------------------------------------------------------------------------
_SCRIPT_TAG_RE = re.compile(r"<script.*?>.*?</script>", re.IGNORECASE | re.DOTALL)
_JS_PROTO_RE = re.compile(r"javascript:", re.IGNORECASE)
_EVENT_HANDLER_RE = re.compile(r"\bon\w+=", re.IGNORECASE)   # onerror=, onload=, etc.

EMAIL_REGEX = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
PHONE_REGEX = re.compile(
    r"\+?\d{1,4}?[.\-\s]?\(?\d{1,3}?\)?[.\-\s]?\d{1,4}[.\-\s]?\d{1,4}[.\-\s]?\d{1,9}"
)
TICKET_REGEX = re.compile(r"\b(?:TICKET|TKT)-\d{4,8}-[A-Z0-9]{2,4}\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Input sanitisation
# ---------------------------------------------------------------------------

def sanitize_input(text: str) -> str:
    """
    Sanitise a user-supplied string against XSS injection patterns.

    The function:
    1. Strips ``<script>`` blocks.
    2. Removes ``javascript:`` protocol references.
    3. Removes inline event handlers (``onerror=``, ``onload=``, …).
    4. HTML-escapes all remaining angle brackets and special characters.

    Parameters
    ----------
    text : str
        Raw input string from a query parameter or request body field.

    Returns
    -------
    str
        Sanitised string safe for logging and downstream processing.
        Non-string inputs are returned unchanged.
    """
    if not isinstance(text, str):
        return text
    clean = _SCRIPT_TAG_RE.sub("", text)
    clean = _JS_PROTO_RE.sub("", clean)
    clean = _EVENT_HANDLER_RE.sub("", clean)
    return html.escape(clean)


# ---------------------------------------------------------------------------
# PII masking
# ---------------------------------------------------------------------------

def mask_pii_string(text: str) -> str:
    """
    Redact personally identifiable information from a log string.

    Matches and masks:
    - **Email** addresses — ``j******e@e*****e.com``
    - **Phone** numbers — ``+***0199``
    - **Ticket IDs** — ``TKT-****-US``

    Parameters
    ----------
    text : str
        Raw string potentially containing PII.

    Returns
    -------
    str
        String with all detected PII replaced by masked equivalents.
    """
    if not isinstance(text, str):
        return text

    def _mask_email(match: re.Match) -> str:
        email = match.group(0)
        parts = email.split("@", 1)
        if len(parts) != 2:
            return email
        name, domain = parts
        masked_name = (
            name[0] + "*" * max(len(name) - 2, 1) + name[-1]
            if len(name) > 2
            else name[0] + "*"
        )
        dom_parts = domain.split(".", 1)
        dom_name = dom_parts[0]
        masked_dom = (
            dom_name[0] + "*" * max(len(dom_name) - 2, 1) + dom_name[-1]
            if len(dom_name) > 2
            else dom_name[0] + "*"
        )
        suffix = f".{dom_parts[1]}" if len(dom_parts) > 1 else ""
        return f"{masked_name}@{masked_dom}{suffix}"

    def _mask_phone(match: re.Match) -> str:
        phone = match.group(0)
        if len(re.sub(r"[.\-\s()]", "", phone)) > 4:
            return phone[0] + "***" + phone[-4:]
        return "***"

    def _mask_ticket(match: re.Match) -> str:
        parts = match.group(0).split("-", 2)
        return f"{parts[0]}-****-{parts[2]}" if len(parts) == 3 else "TKT-****-****"

    masked = EMAIL_REGEX.sub(_mask_email, text)
    masked = PHONE_REGEX.sub(_mask_phone, masked)
    masked = TICKET_REGEX.sub(_mask_ticket, masked)
    return masked


# ---------------------------------------------------------------------------
# Staff API-key dependency (FastAPI Depends)
# ---------------------------------------------------------------------------

async def require_staff_key(
    x_staff_api_key: str = Header(
        ...,
        alias="X-Staff-API-Key",
        description="Staff authentication key required for privileged operations.",
    ),
) -> None:
    """
    FastAPI dependency that enforces staff authentication via an API key
    supplied in the ``X-Staff-API-Key`` request header.

    Raises
    ------
    HTTPException
        403 Forbidden if the key is absent or does not match the configured
        ``STAFF_API_KEY`` environment variable.
    """
    if not STAFF_API_KEY or x_staff_api_key != STAFF_API_KEY:
        logger.warning("Unauthorised staff endpoint access attempt.")
        raise HTTPException(status_code=403, detail="Invalid or missing staff API key.")


# ---------------------------------------------------------------------------
# Security Middleware
# ---------------------------------------------------------------------------

class SecurityMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that enforces:

    1. **Per-IP rate limiting** — sliding window, configurable via env vars.
    2. **Query-parameter sanitisation** — rejects requests with XSS payloads
       in query strings.
    3. **Request body size limit** — rejects payloads larger than
       ``MAX_BODY_BYTES``.
    4. **OWASP security headers** on every response.
    """

    def __init__(
        self,
        app,
        rate_limit_max: int = 100,
        rate_limit_window: int = 60,
    ) -> None:
        super().__init__(app)
        self.rate_limit_max = rate_limit_max
        self.rate_limit_window = rate_limit_window
        # client_ip → (window_start_timestamp, request_count)
        self._clients: Dict[str, Tuple[float, int]] = {}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        client_ip: str = (
            request.client.host if request.client else "unknown"
        )

        # 1. Rate limiting — sliding window per IP
        now = time.monotonic()
        window_start, count = self._clients.get(client_ip, (now, 0))
        if now - window_start < self.rate_limit_window:
            if count >= self.rate_limit_max:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please retry after a minute."},
                )
            self._clients[client_ip] = (window_start, count + 1)
        else:
            self._clients[client_ip] = (now, 1)

        # 2. Query-parameter XSS check
        for key, value in request.query_params.items():
            if sanitize_input(value) != value:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Malicious content detected in query parameter '{key}'."},
                )

        # 3. Request body size limit (skip WebSocket upgrades & GET requests)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body exceeds {MAX_REQUEST_BODY_KB} KB limit."},
                )

        response = await call_next(request)

        # 4. OWASP security response headers
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=(), payment=()"
        )
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "media-src 'self';"
        )
        return response
