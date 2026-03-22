# CQNE — Campus Quantum Network Emulator

A distributed quantum network simulator that emulates entanglement distribution, quantum teleportation, and GHZ state generation across multiple nodes connected over real TCP/IP. Built with Qiskit for quantum simulation and FastAPI for the network layer.

## What It Does

CQNE simulates a quantum internet on commodity hardware. Multiple node processes (representing quantum network nodes) connect to a central control server that maintains the global quantum state. Unlike toy simulations, CQNE uses a **real Qiskit statevector** — entanglement is physically real in the simulation, not a flag in a database.

**Core capabilities:**
- **Entanglement** — Create Bell pairs between any two nodes. Verified in the global statevector as |Φ+⟩ = (|00⟩ + |11⟩)/√2.
- **Quantum Teleportation** — Full protocol: Bell pair creation, Bell measurement, Pauli corrections. Supports both direct and multi-hop teleportation.
- **Multi-hop Routing** — Entanglement swapping at intermediate nodes. Node A can teleport to Node C through Node B without direct connectivity.
- **GHZ States** — N-qubit entanglement across any number of nodes.
- **Decoherence Simulation** — Entangled pairs decay over time: F(t) = F₀ × exp(-rate × t). Expired pairs are automatically cleaned up.
- **Gate Noise** — Configurable depolarizing and dephasing noise on every quantum gate operation. Makes teleportation fidelity realistic.
- **Two Routing Strategies** — Shortest path (BFS) and max fidelity (Dijkstra on -log fidelity). Switchable at runtime.
- **YAML Experiment Definitions** — Write experiment sequences in YAML files, execute them with one click from the dashboard.
- **SQLite Persistence** — Experiment results survive server restarts. Historical data available for analysis.
- **Live Web Dashboard** — Real-time topology visualization, experiment controls, fidelity monitoring, noise configuration.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Layer 5 — Application                              │
│  YAML experiments, demo scripts, dashboard           │
├─────────────────────────────────────────────────────┤
│  Layer 4 — Protocol                                 │
│  JSON over HTTP (REST API)                          │
├─────────────────────────────────────────────────────┤
│  Layer 3 — Router                                   │
│  BFS shortest path, Dijkstra max fidelity           │
├─────────────────────────────────────────────────────┤
│  Layer 2 — Control System                           │
│  QuantumStateManager (global Qiskit circuit)        │
│  EntanglementManager (decoherence, fidelity)        │
│  ExperimentExecutor (teleport, GHZ, entangle)       │
│  ResultsDatabase (SQLite)                           │
├─────────────────────────────────────────────────────┤
│  Layer 1 — Nodes                                    │
│  Thin FastAPI processes, no quantum state            │
│  Register + heartbeat only                           │
└─────────────────────────────────────────────────────┘
```

## Project Structure

```
cqne_redesigned/
├── control_server/
│   ├── control_server.py          # FastAPI app, all REST endpoints
│   ├── quantum_state_manager.py   # Global Qiskit QuantumCircuit + noise
│   ├── entanglement_manager.py    # Bell pairs + decoherence decay
│   ├── experiment_executor.py     # Teleport, GHZ, entangle logic
│   ├── routing_engine.py          # BFS + max-fidelity routing
│   ├── results_database.py        # SQLite persistent storage
│   ├── yaml_runner.py             # YAML experiment parser/executor
│   ├── node_registry.py           # Node online/offline tracking
│   ├── requirements.txt
│   ├── __init__.py
│   ├── static/
│   │   └── dashboard.html         # Live web dashboard
│   └── tests/
│       ├── test_quantum_state_manager.py
│       └── test_experiment_executor.py
├── node/
│   ├── main.py                    # Node process (register + heartbeat)
│   ├── requirements.txt
│   └── __init__.py
├── router/
│   └── router.py                  # Standalone router (for future hardware)
├── experiments/
│   ├── noise_comparison.yaml      # Compare fidelity under 3 noise levels
│   ├── routed_teleport.yaml       # Direct vs multi-hop teleportation
│   ├── decoherence_test.yaml      # Fidelity decay over time
│   └── stress_test.yaml           # Full network stress test
├── run_control.py                 # Launch control server
├── run_nodes.py                   # Launch all 3 node processes
├── run_node.py                    # Launch a single node (CLI args)
├── demo_redesigned.py             # Automated demo script
├── check_setup.py                 # Dependency checker
└── config.json                    # LAN IP configuration for multi-machine
```

## Quick Start

### Prerequisites
- Python 3.11+
- pip

### Setup

```bash
cd cqne_redesigned
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

pip install -r control_server/requirements.txt
pip install -r node/requirements.txt
pip install pyyaml
```

### Run (Single Laptop)

**Terminal 1 — Control Server:**
```bash
python run_control.py
```

**Terminal 2 — All Nodes:**
```bash
python run_nodes.py
```

**Dashboard:** Open http://localhost:8500/dashboard

**Swagger API:** Open http://localhost:8500/docs

### Run (Multi-Machine / Raspberry Pi)

1. Edit `config.json` with your LAN IPs
2. On each Raspberry Pi:
   ```bash
   python run_node.py --node_id node_a --port 8000 --control_url http://<laptop_ip>:8500
   ```
3. On the control laptop:
   ```bash
   python run_control.py
   ```

## Dashboard

The dashboard at `http://localhost:8500/dashboard` provides:

- **Node status** — Online/offline indicators with heartbeat monitoring
- **Experiment controls** — Entangle, Teleport, GHZ with node selection
- **YAML runner** — Select and execute experiment templates from a dropdown
- **Routing controls** — Switch between full mesh and linear topology, change routing strategy
- **Noise & decoherence sliders** — Configure gate error, dephasing, and decoherence rates in real-time
- **Network topology** — SVG visualization showing nodes, connectivity, and entanglement links with fidelity percentages
- **Experiment history** — Scrollable log of all experiments with type, measurements, fidelity, timing, and routing info

## YAML Experiments

Define experiment sequences in YAML files in the `experiments/` folder:

```yaml
name: "My experiment"
description: "Test entanglement under noise"
steps:
  - action: reset
  - action: set_noise
    gate_error: 0.05
    dephasing: 0.02
  - action: entangle
    node_a: node_a
    node_b: node_b
    repeat: 10
  - action: set_topology
    adjacency:
      node_a: [node_b]
      node_b: [node_a, node_c]
      node_c: [node_b]
  - action: teleport
    source: node_a
    target: node_c
    repeat: 5
```

Available actions: `reset`, `set_noise`, `set_decoherence`, `set_topology`, `set_strategy`, `entangle`, `teleport`, `ghz`, `wait`

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/dashboard` | GET | Web dashboard |
| `/health` | GET | Server status |
| `/nodes/register` | POST | Register a node |
| `/nodes/heartbeat` | POST | Node keepalive |
| `/network/status` | GET | Full network state |
| `/experiment/entangle` | POST | Create Bell pair |
| `/experiment/teleport` | POST | Teleport a qubit |
| `/experiment/ghz` | POST | Create GHZ state |
| `/experiment/results` | GET | All experiment results |
| `/experiment/stats` | GET | Aggregate statistics |
| `/experiment/fidelity_history` | GET | Fidelity over time |
| `/experiment/yaml/run_template/{file}` | POST | Run a YAML template |
| `/experiment/yaml/templates` | GET | List YAML templates |
| `/routing/set_topology` | POST | Set custom topology |
| `/routing/clear_topology` | POST | Revert to full mesh |
| `/routing/set_strategy` | POST | Switch routing algorithm |
| `/noise/set` | POST | Configure gate noise |
| `/decoherence/set_rate` | POST | Set decoherence rate |
| `/quantum/reset` | POST | Reset quantum state |
| `/experiment/clear_history` | POST | Clear SQLite database |

## How It Works

### Global Statevector
All qubits from all nodes exist in **one shared Qiskit QuantumCircuit** on the control server. A CNOT between Node A's qubit and Node B's qubit is a real two-qubit gate in a shared statevector. Entanglement is physically real — measuring one qubit collapses the other.

### Teleportation Protocol
1. Prepare qubit to teleport in |+⟩
2. Create Bell pair between source and target
3. Bell measurement at source (CNOT + H + measure)
4. Classical communication of measurement results
5. Pauli corrections at target (X if m2=1, Z if m1=1)
6. Verify by measuring the target qubit

### Multi-hop Teleportation
For path [A, B, C]:
1. Create Bell pairs: A↔B and B↔C
2. Entanglement swapping at B (Bell measurement on B's two qubits)
3. Now A↔C are entangled end-to-end
4. Standard teleportation from A to C

### Noise Model
- **Depolarizing**: After each gate, probability `p` of a random Pauli (X, Y, or Z) error
- **Dephasing**: After each gate, probability `p` of a Z (phase flip) error
- **Decoherence**: Entangled pairs lose fidelity over time: F(t) = F₀ × exp(-rate × t)

## Tech Stack

- **Quantum simulation**: Qiskit + Qiskit Aer (statevector simulator)
- **Network layer**: FastAPI + Uvicorn (async HTTP)
- **Node communication**: httpx (async HTTP client)
- **Database**: SQLite (experiment persistence)
- **Experiment definitions**: PyYAML
- **Dashboard**: Vanilla HTML/CSS/JS (JetBrains Mono + DM Sans)

## License

MIT
