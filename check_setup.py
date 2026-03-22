"""
check_setup.py — Verify all dependencies are installed before running CQNE.
Run:  python check_setup.py
"""
import sys

print("CQNE Setup Check")
print("=" * 50)

errors = []

def check(module, name=None):
    name = name or module
    try:
        __import__(module)
        print(f"  OK  {name}")
    except ImportError:
        print(f"  MISSING  {name}")
        errors.append(name)

check("qiskit", "qiskit (>=1.0)")
check("qiskit_aer", "qiskit-aer (>=0.14)")
check("fastapi", "fastapi (>=0.110)")
check("uvicorn", "uvicorn")
check("httpx", "httpx (>=0.27)")
check("pydantic", "pydantic (>=2.0)")
check("yaml", "pyyaml (>=6.0)")

print()
if errors:
    print(f"Missing {len(errors)} package(s). Install with:")
    print(f"   pip install -r control_server/requirements.txt")
else:
    print("All dependencies installed!")
    print()
    print("To run:")
    print("  Terminal 1: python run_control.py")
    print("  Terminal 2: python run_nodes.py")
    print("  Dashboard:  http://localhost:8500/dashboard")
