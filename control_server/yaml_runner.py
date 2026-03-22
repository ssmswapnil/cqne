"""
YAMLExperimentRunner
====================
Parse and execute experiment sequences defined in YAML files.

A researcher writes a YAML file describing what experiments to run,
with what parameters, and the system executes them in order.

Supports:
  - Sequential experiment steps
  - Configuring noise/decoherence/topology before experiments
  - Reset between experiments (optional)
  - Collecting all results into a single report

Example YAML:
  name: "Noise comparison"
  description: "Compare entanglement fidelity under different noise levels"
  steps:
    - action: reset
    - action: set_noise
      gate_error: 0.0
      dephasing: 0.0
    - action: entangle
      node_a: node_a
      node_b: node_b
      repeat: 5
    - action: reset
    - action: set_noise
      gate_error: 0.1
      dephasing: 0.05
    - action: entangle
      node_a: node_a
      node_b: node_b
      repeat: 5
"""

import time
import logging
from typing import Optional

import yaml

logger = logging.getLogger("YAMLExperimentRunner")


class YAMLExperimentRunner:
    """
    Parses YAML experiment definitions and executes them
    against the control server's components.
    """

    def __init__(self, qsm, ent_mgr, executor, router, results_db):
        self._qsm = qsm
        self._ent = ent_mgr
        self._executor = executor
        self._router = router
        self._results = results_db

    def parse(self, yaml_text: str) -> dict:
        """Parse a YAML experiment definition. Returns the parsed dict."""
        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

        if not isinstance(data, dict):
            raise ValueError("YAML must be a dict with 'name' and 'steps' keys.")
        if "steps" not in data:
            raise ValueError("YAML must contain a 'steps' list.")
        if not isinstance(data["steps"], list):
            raise ValueError("'steps' must be a list.")

        return data

    def run(self, yaml_text: str) -> dict:
        """
        Parse and execute a YAML experiment definition.
        Returns a report with all results.
        """
        data = self.parse(yaml_text)
        name = data.get("name", "Unnamed experiment")
        description = data.get("description", "")
        steps = data["steps"]

        logger.info("Running YAML experiment: '%s' (%d steps)", name, len(steps))
        started_at = time.time()

        report = {
            "name": name,
            "description": description,
            "total_steps": len(steps),
            "started_at": started_at,
            "step_results": [],
            "errors": [],
        }

        for i, step in enumerate(steps):
            if not isinstance(step, dict) or "action" not in step:
                report["errors"].append({"step": i, "error": "Step must be a dict with 'action' key."})
                continue

            action = step["action"]
            repeat = step.get("repeat", 1)

            for rep in range(repeat):
                try:
                    result = self._execute_step(action, step, i, rep)
                    report["step_results"].append({
                        "step": i, "repeat": rep, "action": action, "result": result
                    })
                except Exception as e:
                    logger.exception("Step %d (repeat %d) failed: %s", i, rep, e)
                    report["errors"].append({
                        "step": i, "repeat": rep, "action": action, "error": str(e)
                    })

        report["duration_ms"] = round((time.time() - started_at) * 1000, 2)
        report["completed_steps"] = len(report["step_results"])
        report["error_count"] = len(report["errors"])

        logger.info("YAML experiment '%s' complete: %d steps, %d errors, %.1fms",
                     name, report["completed_steps"], report["error_count"], report["duration_ms"])

        return report

    def _execute_step(self, action: str, step: dict, step_idx: int, repeat_idx: int) -> dict:
        """Execute a single step. Returns a result dict."""

        if action == "reset":
            self._qsm.reset_all()
            self._ent.reset()
            return {"status": "reset"}

        elif action == "set_noise":
            ge = step.get("gate_error", 0.0)
            dp = step.get("dephasing", 0.0)
            self._qsm.set_noise(gate_error=ge, dephasing_rate=dp)
            return {"gate_error": ge, "dephasing": dp}

        elif action == "set_decoherence":
            rate = step.get("rate", 0.01)
            self._ent.set_decoherence_rate(rate)
            return {"decoherence_rate": rate}

        elif action == "set_topology":
            adj = step.get("adjacency")
            if adj:
                self._router.set_topology(adj)
                return {"topology": "custom", "adjacency": adj}
            else:
                self._router.clear_topology()
                return {"topology": "full_mesh"}

        elif action == "set_strategy":
            strategy = step.get("strategy", "shortest_path")
            self._router.set_strategy(strategy)
            return {"strategy": strategy}

        elif action == "entangle":
            node_a = step.get("node_a", "node_a")
            node_b = step.get("node_b", "node_b")
            result = self._executor.run_entangle(node_a, node_b)
            d = result.to_dict()
            self._results.save(d)
            return d

        elif action == "teleport":
            src = step.get("source", "node_a")
            tgt = step.get("target", "node_b")
            shots = step.get("shots", 128)
            result = self._executor.run_teleport(src, tgt, shots)
            d = result.to_dict()
            self._results.save(d)
            return d

        elif action == "ghz":
            node_ids = step.get("nodes", ["node_a", "node_b", "node_c"])
            result = self._executor.run_ghz(node_ids)
            d = result.to_dict()
            self._results.save(d)
            return d

        elif action == "wait":
            seconds = step.get("seconds", 1)
            time.sleep(seconds)
            return {"waited": seconds}

        else:
            raise ValueError(f"Unknown action: '{action}'")

    def get_available_actions(self) -> list[dict]:
        """Return documentation of all available YAML actions."""
        return [
            {"action": "reset", "description": "Clear all quantum state, links, and results."},
            {"action": "set_noise", "params": {"gate_error": "float 0-1", "dephasing": "float 0-1"},
             "description": "Configure gate noise."},
            {"action": "set_decoherence", "params": {"rate": "float"},
             "description": "Set entanglement decoherence rate."},
            {"action": "set_topology", "params": {"adjacency": "dict or null"},
             "description": "Set network topology. Null = full mesh."},
            {"action": "set_strategy", "params": {"strategy": "shortest_path|max_fidelity"},
             "description": "Set routing strategy."},
            {"action": "entangle", "params": {"node_a": "str", "node_b": "str", "repeat": "int"},
             "description": "Create entangled Bell pair."},
            {"action": "teleport", "params": {"source": "str", "target": "str", "shots": "int", "repeat": "int"},
             "description": "Teleport a qubit."},
            {"action": "ghz", "params": {"nodes": "list[str]", "repeat": "int"},
             "description": "Create GHZ state across nodes."},
            {"action": "wait", "params": {"seconds": "float"},
             "description": "Wait (useful for decoherence tests)."},
        ]
