"""
CQNE Control Server v2.5
=========================
Global statevector + routing + decoherence + gate noise + YAML + SQLite.

Dashboard: http://localhost:8500/dashboard
Swagger:   http://localhost:8500/docs
"""

import os
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .quantum_state_manager import QuantumStateManager
from .node_registry         import NodeRegistry
from .entanglement_manager  import EntanglementManager
from .experiment_executor   import ExperimentExecutor
from .results_database      import ResultsDatabase
from .routing_engine        import RoutingEngine
from .yaml_runner           import YAMLExperimentRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger("ControlServer")
STATIC_DIR = Path(__file__).parent / "static"
EXPERIMENTS_DIR = Path(__file__).parent.parent / "experiments"

# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
qsm      = QuantumStateManager()
node_reg = NodeRegistry()
ent_mgr  = EntanglementManager(qsm, node_reg, decoherence_rate=0.01)
router   = RoutingEngine()
executor = ExperimentExecutor(qsm, ent_mgr, node_reg, router)
results  = ResultsDatabase()  # Now SQLite-backed!
yaml_runner = YAMLExperimentRunner(qsm, ent_mgr, executor, router, results)
router.set_fidelity_function(ent_mgr.get_link_fidelity)

app = FastAPI(title="CQNE Control Server", version="2.5.0",
    description="Quantum network emulator with SQLite persistence.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    node_id: str; url: str
class HeartbeatRequest(BaseModel):
    node_id: str
class EntangleRequest(BaseModel):
    node_a_id: str = Field(default="node_a"); node_b_id: str = Field(default="node_b")
class TeleportRequest(BaseModel):
    source_node_id: str = Field(default="node_a"); target_node_id: str = Field(default="node_b"); shots: int = 128
class GHZRequest(BaseModel):
    node_ids: list[str] = Field(default=["node_a", "node_b", "node_c"])
class TopologyRequest(BaseModel):
    adjacency: dict[str, list[str]] = Field(default={"node_a": ["node_b"], "node_b": ["node_a", "node_c"], "node_c": ["node_b"]})
class RouteRequest(BaseModel):
    source: str = Field(default="node_a"); target: str = Field(default="node_c")
class DecoherenceRequest(BaseModel):
    rate: float = Field(default=0.05)
class StrategyRequest(BaseModel):
    strategy: str = Field(default="shortest_path")
class NoiseRequest(BaseModel):
    gate_error: float = Field(default=0.02); dephasing: float = Field(default=0.01)
class YAMLRunRequest(BaseModel):
    yaml_text: str

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _save_and_return(result) -> dict:
    d = result.to_dict(); results.save(d)
    if result.error: raise HTTPException(status_code=500, detail=result.error)
    return d

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=(STATIC_DIR / "dashboard.html").read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    topo = router.get_topology()
    return {
        "status": "ok", "version": "2.5.0", "database": "sqlite",
        "nodes_online": len(node_reg.online_nodes()),
        "total_experiments": results.count(),
        "topology_mode": "custom" if topo else "full_mesh",
        "routing_strategy": router.get_strategy(),
        "noise": qsm.get_noise_config(),
    }

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
@app.post("/nodes/register")
def register_node(req: RegisterRequest):
    node_reg.register(req.node_id, req.url); return {"status": "registered", "node_id": req.node_id}
@app.post("/nodes/heartbeat")
def heartbeat(req: HeartbeatRequest):
    try: node_reg.heartbeat(req.node_id); return {"status": "ok"}
    except KeyError: raise HTTPException(status_code=404, detail=f"Node '{req.node_id}' not registered.")

# ---------------------------------------------------------------------------
# Network status
# ---------------------------------------------------------------------------
@app.get("/network/status")
def network_status():
    topo = router.get_topology(); ent_mgr.cleanup_expired()
    return {
        "topology": node_reg.snapshot(), "links": ent_mgr.all_links(),
        "alive_links": ent_mgr.alive_links(), "qubit_count": len(qsm.get_registry_snapshot()),
        "routing": topo, "topology_mode": "custom" if topo else "full_mesh",
        "routing_strategy": router.get_strategy(), "decoherence": ent_mgr.get_decoherence_config(),
        "noise": qsm.get_noise_config(),
    }

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
@app.post("/routing/set_topology")
def set_topology(req: TopologyRequest):
    router.set_topology(req.adjacency); return {"status": "topology_set", "adjacency": req.adjacency}
@app.post("/routing/clear_topology")
def clear_topology():
    router.clear_topology(); return {"status": "full_mesh"}
@app.get("/routing/topology")
def get_topology():
    topo = router.get_topology(); return {"mode": "custom" if topo else "full_mesh", "adjacency": topo}
@app.post("/routing/find_path")
def find_path(req: RouteRequest):
    online = {n.node_id for n in node_reg.online_nodes()}
    path, fidelity = router.find_path_with_fidelity(req.source, req.target, online)
    if path is None: raise HTTPException(status_code=404, detail=f"No path from {req.source} to {req.target}")
    return {"path": path, "hops": len(path) - 1, "estimated_fidelity": fidelity}
@app.post("/routing/set_strategy")
def set_strategy(req: StrategyRequest):
    router.set_strategy(req.strategy); return {"strategy": req.strategy}

# ---------------------------------------------------------------------------
# Decoherence & Noise
# ---------------------------------------------------------------------------
@app.post("/decoherence/set_rate")
def set_decoherence_rate(req: DecoherenceRequest):
    ent_mgr.set_decoherence_rate(req.rate); return {"decoherence_rate": req.rate}
@app.post("/noise/set")
def set_noise(req: NoiseRequest):
    qsm.set_noise(gate_error=req.gate_error, dephasing_rate=req.dephasing)
    return {"gate_error": req.gate_error, "dephasing": req.dephasing}

# ---------------------------------------------------------------------------
# Experiments (individual)
# ---------------------------------------------------------------------------
@app.post("/experiment/entangle")
def experiment_entangle(req: EntangleRequest):
    return _save_and_return(executor.run_entangle(req.node_a_id, req.node_b_id))
@app.post("/experiment/teleport")
def experiment_teleport(req: TeleportRequest):
    return _save_and_return(executor.run_teleport(req.source_node_id, req.target_node_id, req.shots))
@app.post("/experiment/ghz")
def experiment_ghz(req: GHZRequest):
    return _save_and_return(executor.run_ghz(req.node_ids))

# ---------------------------------------------------------------------------
# YAML Experiments
# ---------------------------------------------------------------------------
@app.post("/experiment/yaml/run")
def run_yaml_experiment(req: YAMLRunRequest):
    try: return yaml_runner.run(req.yaml_text)
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@app.get("/experiment/yaml/templates")
def list_yaml_templates():
    if not EXPERIMENTS_DIR.exists(): return {"templates": []}
    templates = []
    for f in sorted(EXPERIMENTS_DIR.glob("*.yaml")):
        import yaml
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            templates.append({"filename": f.name, "name": data.get("name", f.stem),
                              "description": data.get("description", ""), "steps": len(data.get("steps", []))})
        except: templates.append({"filename": f.name, "name": f.stem, "steps": 0})
    return {"templates": templates}

@app.get("/experiment/yaml/template/{filename}")
def get_yaml_template(filename: str):
    fpath = EXPERIMENTS_DIR / filename
    if not fpath.exists(): raise HTTPException(status_code=404, detail=f"Template '{filename}' not found.")
    return {"filename": filename, "content": fpath.read_text(encoding="utf-8")}

@app.post("/experiment/yaml/run_template/{filename}")
def run_yaml_template(filename: str):
    fpath = EXPERIMENTS_DIR / filename
    if not fpath.exists(): raise HTTPException(status_code=404, detail=f"Template '{filename}' not found.")
    try: return yaml_runner.run(fpath.read_text(encoding="utf-8"))
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

# ---------------------------------------------------------------------------
# Results (SQLite-backed, persistent)
# ---------------------------------------------------------------------------
@app.get("/experiment/results")
def list_results():
    return {"experiments": results.recent(100)}

@app.get("/experiment/results/{exp_id}")
def get_result(exp_id: str):
    r = results.get(exp_id)
    if r is None: raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found.")
    return r

@app.get("/experiment/summary")
def get_summary():
    return results.summary()

@app.get("/experiment/stats")
def get_stats():
    """Detailed statistics: avg fidelity, avg duration, total experiments."""
    return results.stats()

@app.get("/experiment/fidelity_history")
def fidelity_history(limit: int = 100):
    """Fidelity values over time for charting."""
    return {"history": results.fidelity_history(limit=limit)}

@app.post("/experiment/clear_history")
def clear_history():
    """Clear all experiment history from the database."""
    results.reset()
    return {"status": "history_cleared"}

# ---------------------------------------------------------------------------
# Quantum state
# ---------------------------------------------------------------------------
@app.get("/quantum/statevector")
def get_statevector():
    sv = qsm.get_statevector_serialisable()
    return {"statevector": sv, "qubit_count": len(qsm.get_registry_snapshot())}
@app.get("/quantum/registry")
def get_registry():
    return {"registry": qsm.get_registry_snapshot()}

@app.post("/quantum/reset")
def reset_quantum_state():
    """Reset quantum state and entanglement links. Experiment history is preserved in SQLite."""
    qsm.reset_all()
    ent_mgr.reset()
    # NOTE: We do NOT call results.reset() here anymore.
    # Experiment history persists across resets. Use /experiment/clear_history to clear it.
    return {"status": "quantum_state_reset", "note": "Experiment history preserved in database."}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("CONTROL_PORT", "8500"))
    uvicorn.run("control_server:app", host="0.0.0.0", port=port)
