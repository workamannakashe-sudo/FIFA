import os

# Server settings
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# Gemini API setting
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Security Rate Limiting
# Max requests allowed from a single IP address in a time window
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX", "100"))
