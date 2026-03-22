"""
CQNE Control Server — Entry point
Run from cqne_redesigned directory:
    venv\Scripts\python run_control.py
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

if __name__ == "__main__":
    port = int(os.getenv("CONTROL_PORT", "8500"))
    host = os.getenv("CONTROL_HOST", "0.0.0.0")
    print()
    print("=" * 60)
    print("  CQNE Control Server (Global Statevector)")
    print("=" * 60)
    print(f"  Port:       {port}")
    print(f"  Swagger UI: http://localhost:{port}/docs")
    print(f"  Health:     http://localhost:{port}/health")
    print("=" * 60)
    print()
    uvicorn.run(
        "control_server.control_server:app",
        host=host,
        port=port,
        log_level="info",
    )
