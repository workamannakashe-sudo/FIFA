import uvicorn
from app.config import HOST, PORT

if __name__ == "__main__":
    print(f"Launching SafePass 2026 Egress Router on http://{HOST}:{PORT}")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
