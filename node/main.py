"""
CQNE Node (Redesigned)
======================
Lightweight process: register + heartbeat. NO quantum state.
All quantum operations live on the Control Server.
"""

import os
import time
import logging
import threading

import httpx
import uvicorn
from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("Node")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NODE_ID      = os.getenv("NODE_ID",      "node_default")
NODE_HOST    = os.getenv("NODE_HOST",    "0.0.0.0")
NODE_PORT    = int(os.getenv("NODE_PORT",    "8000"))
NODE_URL     = os.getenv("NODE_URL",     f"http://localhost:{NODE_PORT}")
CONTROL_URL  = os.getenv("CONTROL_URL",  "http://localhost:8500").rstrip("/")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title=f"CQNE Node [{NODE_ID}]",
    version="2.0.0",
)


@app.get("/health")
def health():
    return {"status": "ok", "node_id": NODE_ID, "role": "node"}


@app.get("/info")
def info():
    return {"node_id": NODE_ID, "node_url": NODE_URL, "control_url": CONTROL_URL}


# ---------------------------------------------------------------------------
# Registration and heartbeat
# ---------------------------------------------------------------------------

def _register() -> bool:
    try:
        resp = httpx.post(
            f"{CONTROL_URL}/nodes/register",
            json={"node_id": NODE_ID, "url": NODE_URL},
            timeout=5.0,
        )
        resp.raise_for_status()
        logger.info("Registered '%s' with control server at %s", NODE_ID, CONTROL_URL)
        return True
    except Exception as exc:
        logger.warning("Registration failed for '%s': %s", NODE_ID, exc)
        return False


def _heartbeat():
    try:
        httpx.post(
            f"{CONTROL_URL}/nodes/heartbeat",
            json={"node_id": NODE_ID},
            timeout=5.0,
        )
    except Exception:
        pass


def _heartbeat_loop(interval=30):
    def _loop():
        while True:
            time.sleep(interval)
            _heartbeat()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup():
    logger.info("Node '%s' starting on %s:%d", NODE_ID, NODE_HOST, NODE_PORT)
    logger.info("  Control Server: %s", CONTROL_URL)

    for attempt in range(5):
        if _register():
            break
        logger.info("  Retry registration (%d/5)...", attempt + 2)
        time.sleep(2)

    _heartbeat_loop(30)


# ---------------------------------------------------------------------------
# Entry point — when run directly via: python node/main.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host=NODE_HOST, port=NODE_PORT)
