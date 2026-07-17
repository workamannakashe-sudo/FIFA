"""
run.py
~~~~~~
Application execution entry point for SafePass 2026.

Launches the FastAPI server with local uvicorn runner, pulling host and port
configurations directly from the settings environment variables.
"""

from __future__ import annotations

import uvicorn

from app.config import HOST, PORT

if __name__ == "__main__":
    print(f"Launching SafePass 2026 Egress Router on http://{HOST}:{PORT}")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
