"""
CQNE Node Launcher — Run from cqne_redesigned directory.

Usage (run 2-3 of these in separate terminals):
    python run_node.py --id node_a --port 8000
    python run_node.py --id node_b --port 8001
    python run_node.py --id node_c --port 8002

Or with env vars:
    NODE_ID=node_a NODE_PORT=8000 python run_node.py
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser(description="Start a CQNE node")
    parser.add_argument("--id",   default=None, help="Node ID (e.g. node_a)")
    parser.add_argument("--port", default=None, type=int, help="Port (e.g. 8000)")
    parser.add_argument("--control", default=None, help="Control server URL")
    args = parser.parse_args()

    # CLI args override env vars
    if args.id:
        os.environ["NODE_ID"] = args.id
    if args.port:
        os.environ["NODE_PORT"] = str(args.port)
    if args.control:
        os.environ["CONTROL_URL"] = args.control

    node_id = os.getenv("NODE_ID", "node_default")
    port    = int(os.getenv("NODE_PORT", "8000"))
    ctrl    = os.getenv("CONTROL_URL", "http://localhost:8500")

    # Set NODE_URL so registration uses localhost properly
    os.environ["NODE_URL"] = f"http://localhost:{port}"

    print(f"\n🔵 Starting CQNE Node '{node_id}' on port {port}")
    print(f"   Control Server: {ctrl}\n")

    import uvicorn
    uvicorn.run(
        "node.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
