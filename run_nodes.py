"""
run_nodes.py — Start 3 CQNE nodes as subprocesses in one terminal.

Terminal 1: venv\Scripts\python run_control.py
Terminal 2: venv\Scripts\python run_nodes.py
Then:       venv\Scripts\python demo_redesigned.py
"""
import os
import sys
import time
import subprocess
import signal

CONTROL_URL = os.getenv("CONTROL_URL", "http://localhost:8500")

NODES = [
    {"node_id": "node_a", "port": 8000},
    {"node_id": "node_b", "port": 8001},
    {"node_id": "node_c", "port": 8002},
]

# Use the same Python that's running this script (i.e. the venv python)
PYTHON = sys.executable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NODE_MAIN = os.path.join(SCRIPT_DIR, "node", "main.py")

processes = []


def cleanup(*args):
    print("\nShutting down all nodes...")
    for p in processes:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)


def main():
    print()
    print("=" * 60)
    print("  CQNE — Starting All Nodes")
    print("=" * 60)
    print(f"  Control Server: {CONTROL_URL}")
    print(f"  Python:         {PYTHON}")
    print()

    for cfg in NODES:
        nid  = cfg["node_id"]
        port = cfg["port"]

        env = os.environ.copy()
        env["NODE_ID"]      = nid
        env["NODE_PORT"]    = str(port)
        env["NODE_URL"]     = f"http://localhost:{port}"
        env["CONTROL_URL"]  = CONTROL_URL

        print(f"  Starting {nid} on port {port}...")

        p = subprocess.Popen(
            [PYTHON, NODE_MAIN],
            env=env,
            cwd=SCRIPT_DIR,
        )
        processes.append(p)
        time.sleep(2)  # give each node time to start and register

    print()
    print("=" * 60)
    print("  All 3 nodes running!")
    print()
    print("  node_a → http://localhost:8000")
    print("  node_b → http://localhost:8001")
    print("  node_c → http://localhost:8002")
    print()
    print("  Next step — open a 3rd terminal and run:")
    print(f"    cd {SCRIPT_DIR}")
    print(f"    venv\\Scripts\\python demo_redesigned.py")
    print()
    print("  Press Ctrl+C to stop all nodes.")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
