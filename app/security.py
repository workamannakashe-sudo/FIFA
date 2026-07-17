import re
import html
import time
from typing import Dict, Tuple
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint

# Regex patterns for identifying PII
EMAIL_REGEX = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
PHONE_REGEX = re.compile(r'\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}')
TICKET_REGEX = re.compile(r'\b(?:TICKET|TKT)-\d{4,8}-[A-Z0-9]{2,4}\b', re.IGNORECASE)

def sanitize_input(text: str) -> str:
    """Sanitizes dynamic inputs against XSS and SQL injection patterns."""
    if not isinstance(text, str):
        return text
    # Remove script tags and dangerous patterns first
    clean = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.IGNORECASE)
    clean = re.sub(r'javascript:', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'onerror=', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'onload=', '', clean, flags=re.IGNORECASE)
    # Escape HTML tags
    clean = html.escape(clean)
    # Strip basic SQL injection characters (avoid matching harmless quotes but protect SQL parameters)
    clean = clean.replace("'", "''")
    return clean

def mask_pii_string(text: str) -> str:
    """Masks PII like email, phone, and ticket IDs from logs and payloads."""
    if not isinstance(text, str):
        return text
    
    # Mask Email
    def email_mask(match):
        email = match.group(0)
        parts = email.split('@')
        if len(parts) == 2:
            name, domain = parts[0], parts[1]
            masked_name = name[0] + "*" * (len(name) - 2) + name[-1] if len(name) > 2 else name[0] + "*"
            # Mask domain part
            dom_parts = domain.split('.')
            dom_name = dom_parts[0]
            masked_dom = dom_name[0] + "*" * (len(dom_name) - 2) + dom_name[-1] if len(dom_name) > 2 else dom_name[0] + "*"
            return f"{masked_name}@{masked_dom}.{'.'.join(dom_parts[1:])}"
        return email

    # Mask Phone
    def phone_mask(match):
        phone = match.group(0)
        clean_phone = re.sub(r'[-.\s\(\)]', '', phone)
        if len(clean_phone) > 4:
            return phone[0] + "***" + phone[-4:]
        return "***"

    # Mask Ticket ID
    def ticket_mask(match):
        ticket = match.group(0)
        parts = ticket.split('-')
        if len(parts) == 3:
            return f"{parts[0]}-****-{parts[2]}"
        return "TKT-****-****"

    masked = EMAIL_REGEX.sub(email_mask, text)
    masked = PHONE_REGEX.sub(phone_mask, masked)
    masked = TICKET_REGEX.sub(ticket_mask, masked)
    return masked


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rate_limit_max: int = 100, rate_limit_window: int = 60):
        super().__init__(app)
        self.rate_limit_max = rate_limit_max
        self.rate_limit_window = rate_limit_window
        # In-memory rate limiter: client_ip -> (timestamp_of_first_req, count)
        self.clients: Dict[str, Tuple[float, int]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        
        # 1. Rate Limiting Middleware Check
        now = time.time()
        if client_ip in self.clients:
            start_time, count = self.clients[client_ip]
            if now - start_time < self.rate_limit_window:
                if count >= self.rate_limit_max:
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limit exceeded. Try again in a minute."
                    )
                self.clients[client_ip] = (start_time, count + 1)
            else:
                # Reset window
                self.clients[client_ip] = (now, 1)
        else:
            self.clients[client_ip] = (now, 1)

        # 2. Input Sanitization for Query Params
        for key, value in request.query_params.items():
            sanitized = sanitize_input(value)
            if sanitized != value:
                raise HTTPException(status_code=400, detail=f"Malicious characters detected in query param: {key}")

        # Execute request downstream
        response = await call_next(request)
        
        # 3. Add Security Headers
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "media-src 'self';"
        )
        return response
