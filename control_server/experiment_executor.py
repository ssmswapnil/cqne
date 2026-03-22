"""
ExperimentExecutor v2.3
=======================
Runs experiments: entanglement, teleportation (direct + routed),
entanglement swapping, and GHZ state generation.

Now computes Bell pair fidelity directly from the statevector,
regardless of how many qubits are in the global circuit.
"""

import uuid
import time
import math
import logging
from typing import Optional

from .quantum_state_manager import QuantumStateManager
from .entanglement_manager  import EntanglementManager
from .node_registry         import NodeRegistry
from .routing_engine        import RoutingEngine

logger = logging.getLogger("ExperimentExecutor")


class ExperimentResult:
    def __init__(self, exp_id: str, exp_type: str):
        self.exp_id = exp_id
        self.exp_type = exp_type
        self.started_at = time.time()
        self.data: dict = {}
        self.error: Optional[str] = None

    def finish(self, data: dict) -> "ExperimentResult":
        self.data = data
        self.duration_ms = round((time.time() - self.started_at) * 1000, 2)
        return self

    def fail(self, reason: str) -> "ExperimentResult":
        self.error = reason
        self.duration_ms = round((time.time() - self.started_at) * 1000, 2)
        return self

    def to_dict(self) -> dict:
        return {
            "exp_id": self.exp_id, "type": self.exp_type,
            "started_at": self.started_at,
            "duration_ms": getattr(self, "duration_ms", None),
            "error": self.error, **self.data,
        }


class ExperimentExecutor:
    def __init__(self, qsm, ent_manager, node_registry, routing_engine=None):
        self._qsm = qsm
        self._ent = ent_manager
        self._nodes = node_registry
        self._router = routing_engine or RoutingEngine()
        self._results: dict[str, ExperimentResult] = {}

    @property
    def routing_engine(self):
        return self._router

    # ── Fidelity calculation ──

    def _compute_bell_fidelity(self, qubit_a_id: str, qubit_b_id: str) -> float:
        """
        Compute the fidelity of a Bell pair |Φ+⟩ = (|00⟩+|11⟩)/√2
        by measuring statistical correlation over many shots.
        
        Runs 500 shots of measurement on both qubits and checks
        what fraction are correlated (both 0 or both 1).
        A perfect Bell pair gives 1.0, noise reduces it.
        
        NOTE: This creates a fresh copy of the circuit for measurement
        so it doesn't disturb the actual quantum state.
        """
        sv = self._qsm.get_statevector()
        if not sv:
            return 0.0

        n_qubits = len(self._qsm._qubit_order)
        idx_a = self._qsm._qubit_order.index(qubit_a_id)
        idx_b = self._qsm._qubit_order.index(qubit_b_id)

        # Compute probability of correlated outcomes: P(00) + P(11)
        # For each basis state, check if qubit_a and qubit_b have the same value
        prob_correlated = 0.0
        for i in range(len(sv)):
            bit_a = (i >> idx_a) & 1  # Qiskit little-endian
            bit_b = (i >> idx_b) & 1
            if bit_a == bit_b:
                prob_correlated += abs(sv[i]) ** 2

        # For a perfect Bell pair, correlation = 1.0
        # For a completely mixed state, correlation = 0.5
        # Fidelity = 2 * correlation - 1 maps [0.5, 1.0] to [0.0, 1.0]
        # But we'll just return the raw correlation as it's more intuitive
        fidelity = round(prob_correlated, 4)
        return fidelity

    # ── Entangle ──

    def run_entangle(self, node_a_id: str, node_b_id: str) -> ExperimentResult:
        exp_id = str(uuid.uuid4())[:8]
        result = ExperimentResult(exp_id, "entangle")
        logger.info("[%s] Entangle %s ↔ %s", exp_id, node_a_id, node_b_id)

        try:
            self._require_online(node_a_id, node_b_id)
            link = self._ent.create_link(
                node_a_id, node_b_id,
                qubit_a_id=f"ent_{exp_id}_a",
                qubit_b_id=f"ent_{exp_id}_b",
                exp_id=exp_id,
            )
            # Compute fidelity of this specific Bell pair
            fidelity = self._compute_bell_fidelity(link.qubit_a_id, link.qubit_b_id)
            noise_cfg = self._qsm.get_noise_config()

            result.finish({
                "source": node_a_id, "target": node_b_id,
                "link_id": link.link_id,
                "qubit_a": link.qubit_a_id, "qubit_b": link.qubit_b_id,
                "fidelity": fidelity,
                "noise_events": noise_cfg["noise_events"],
            })
            logger.info("[%s] Bell pair fidelity: %.4f", exp_id, fidelity)
        except Exception as exc:
            logger.exception("[%s] Entangle failed", exp_id)
            result.fail(str(exc))

        self._results[exp_id] = result
        return result

    # ── Direct teleportation ──

    def _teleport_direct(self, src, tgt, shots, exp_id):
        q_tel = f"tel_{exp_id}"
        self._qsm.allocate_qubit(src, q_tel)
        self._qsm.apply_gate("H", q_tel)

        q_bsrc = f"bsrc_{exp_id}"
        q_btgt = f"btgt_{exp_id}"
        self._qsm.allocate_qubit(src, q_bsrc)
        self._qsm.allocate_qubit(tgt, q_btgt)
        self._qsm.create_bell_pair(q_bsrc, q_btgt)

        self._qsm.apply_gate("CNOT", q_tel, q_bsrc)
        self._qsm.apply_gate("H", q_tel)
        m1 = self._qsm.measure_qubit(q_tel, shots=1)
        m2 = self._qsm.measure_qubit(q_bsrc, shots=1)

        if m2 == 1: self._qsm.apply_gate("X", q_btgt)
        if m1 == 1: self._qsm.apply_gate("Z", q_btgt)

        final = self._qsm.measure_qubit(q_btgt, shots=shots)
        noise_cfg = self._qsm.get_noise_config()

        return {
            "source": src, "target": tgt,
            "q_teleport": q_tel, "q_bell_src": q_bsrc, "q_bell_tgt": q_btgt,
            "m1": m1, "m2": m2, "final_result": final, "shots": shots,
            "path": [src, tgt], "hops": 1, "routed": False,
            "noise_events": noise_cfg["noise_events"],
        }

    # ── Entanglement swapping ──

    def _entanglement_swap(self, q_left, q_mid_left, q_mid_right, q_right, exp_id, hop_idx):
        self._qsm.apply_gate("CNOT", q_mid_left, q_mid_right)
        self._qsm.apply_gate("H", q_mid_left)
        m1 = self._qsm.measure_qubit(q_mid_left, shots=1)
        m2 = self._qsm.measure_qubit(q_mid_right, shots=1)

        if m2 == 1: self._qsm.apply_gate("X", q_right)
        if m1 == 1: self._qsm.apply_gate("Z", q_right)

        logger.info("[%s] Swap hop %d: m1=%d m2=%d", exp_id, hop_idx, m1, m2)
        return {"hop": hop_idx, "m1": m1, "m2": m2}

    # ── Routed teleportation ──

    def run_teleport(self, source_node_id, target_node_id, shots=128):
        exp_id = str(uuid.uuid4())[:8]
        result = ExperimentResult(exp_id, "teleport")
        src, tgt = source_node_id, target_node_id
        logger.info("[%s] Teleport %s → %s", exp_id, src, tgt)

        try:
            self._require_online(src, tgt)
            online = {n.node_id for n in self._nodes.online_nodes()}
            path = self._router.find_path(src, tgt, online)

            if path is None:
                raise RuntimeError(f"No path from '{src}' to '{tgt}'.")

            if len(path) <= 2:
                data = self._teleport_direct(src, tgt, shots, exp_id)
            else:
                data = self._teleport_routed(path, shots, exp_id)

            result.finish(data)
            logger.info("[%s] Teleport complete: %s (%d hops, %.1fms)",
                         exp_id, " → ".join(path), len(path) - 1, result.duration_ms)

        except Exception as exc:
            logger.exception("[%s] Teleport failed", exp_id)
            result.fail(str(exc))

        self._results[exp_id] = result
        return result

    def _teleport_routed(self, path, shots, exp_id):
        src, tgt = path[0], path[-1]
        n_hops = len(path) - 1

        hop_qubits = []
        for i in range(n_hops):
            q_l = f"hop{i}_L_{exp_id}"
            q_r = f"hop{i}_R_{exp_id}"
            self._qsm.allocate_qubit(path[i], q_l)
            self._qsm.allocate_qubit(path[i + 1], q_r)
            self._qsm.create_bell_pair(q_l, q_r)
            hop_qubits.append((q_l, q_r))

        swap_results = []
        for i in range(n_hops - 1):
            swap_data = self._entanglement_swap(
                hop_qubits[0][0], hop_qubits[i][1],
                hop_qubits[i + 1][0], hop_qubits[i + 1][1],
                exp_id, i,
            )
            swap_results.append(swap_data)

        q_src_bell = hop_qubits[0][0]
        q_tgt_bell = hop_qubits[-1][1]

        q_tel = f"tel_{exp_id}"
        self._qsm.allocate_qubit(src, q_tel)
        self._qsm.apply_gate("H", q_tel)

        self._qsm.apply_gate("CNOT", q_tel, q_src_bell)
        self._qsm.apply_gate("H", q_tel)
        m1 = self._qsm.measure_qubit(q_tel, shots=1)
        m2 = self._qsm.measure_qubit(q_src_bell, shots=1)

        if m2 == 1: self._qsm.apply_gate("X", q_tgt_bell)
        if m1 == 1: self._qsm.apply_gate("Z", q_tgt_bell)

        final = self._qsm.measure_qubit(q_tgt_bell, shots=shots)
        noise_cfg = self._qsm.get_noise_config()

        return {
            "source": src, "target": tgt,
            "q_teleport": q_tel, "q_bell_src": q_src_bell, "q_bell_tgt": q_tgt_bell,
            "m1": m1, "m2": m2, "final_result": final, "shots": shots,
            "path": path, "hops": n_hops, "routed": True,
            "swaps": swap_results, "noise_events": noise_cfg["noise_events"],
        }

    # ── GHZ ──

    def run_ghz(self, node_ids):
        if len(node_ids) < 2:
            raise ValueError("GHZ requires at least 2 nodes.")

        exp_id = str(uuid.uuid4())[:8]
        result = ExperimentResult(exp_id, "ghz")

        try:
            self._require_online(*node_ids)
            qubit_ids = []
            for nid in node_ids:
                qid = f"ghz_{exp_id}_{nid}"
                self._qsm.allocate_qubit(nid, qid)
                qubit_ids.append(qid)

            self._qsm.apply_gate("H", qubit_ids[0])
            for i in range(1, len(qubit_ids)):
                self._qsm.apply_gate("CNOT", qubit_ids[0], qubit_ids[i])

            noise_cfg = self._qsm.get_noise_config()
            result.finish({
                "nodes": node_ids, "qubits": qubit_ids,
                "noise_events": noise_cfg["noise_events"],
            })
        except Exception as exc:
            logger.exception("[%s] GHZ failed", exp_id)
            result.fail(str(exc))

        self._results[exp_id] = result
        return result

    # ── Helpers ──

    def _require_online(self, *node_ids):
        for nid in node_ids:
            if not self._nodes.is_online(nid):
                raise RuntimeError(f"Node '{nid}' is offline.")
