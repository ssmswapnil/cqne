"""
QuantumStateManager v2.3
========================
Global statevector with configurable gate noise.

Max qubit limit: 20 qubits (2^20 = 1M amplitudes, ~16 MB).
Beyond this, experiments must reset first.

Noise models:
  - depolarizing: probability p of random Pauli (X/Y/Z) error per gate
  - dephasing: probability p of Z error per gate
"""

import logging
import threading
import random
from typing import Optional

from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator

logger = logging.getLogger("QuantumStateManager")

MAX_QUBITS = 20  # Safety limit: 2^20 = ~16MB. Beyond this, memory explodes.

SINGLE_QUBIT_GATES = {"H", "X", "Y", "Z", "S", "T", "SX"}
TWO_QUBIT_GATES    = {"CNOT", "CX", "CZ", "SWAP"}


class QubitRecord:
    def __init__(self, qubit_id: str, node_id: str):
        self.qubit_id = qubit_id
        self.node_id = node_id
        self.entangled_with: Optional[str] = None
        self.measured = False
        self.measurement_result: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "qubit_id": self.qubit_id, "node_id": self.node_id,
            "entangled_with": self.entangled_with,
            "measured": self.measured, "measurement_result": self.measurement_result,
        }


class QuantumStateManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._backend = AerSimulator()
        self._qubit_order: list[str] = []
        self._registry: dict[str, QubitRecord] = {}
        self._gate_log: list[tuple[str, list[int]]] = []
        self._circuit: Optional[QuantumCircuit] = None

        self._gate_error_rate: float = 0.0
        self._dephasing_rate: float = 0.0
        self._noise_enabled: bool = False
        self._noise_events: int = 0

        logger.info("QuantumStateManager initialised (max %d qubits)", MAX_QUBITS)

    # ── Noise config ──

    def set_noise(self, gate_error: float = 0.0, dephasing_rate: float = 0.0) -> None:
        self._gate_error_rate = max(0.0, min(1.0, gate_error))
        self._dephasing_rate = max(0.0, min(1.0, dephasing_rate))
        self._noise_enabled = (self._gate_error_rate > 0 or self._dephasing_rate > 0)
        logger.info("Noise: gate_error=%.4f, dephasing=%.4f, enabled=%s",
                     self._gate_error_rate, self._dephasing_rate, self._noise_enabled)

    def get_noise_config(self) -> dict:
        return {
            "gate_error_rate": self._gate_error_rate,
            "dephasing_rate": self._dephasing_rate,
            "noise_enabled": self._noise_enabled,
            "noise_events": self._noise_events,
        }

    def _apply_noise(self, qubit_idx: int) -> None:
        if not self._noise_enabled or self._circuit is None:
            return
        if self._gate_error_rate > 0 and random.random() < self._gate_error_rate:
            pauli = random.choice(["x", "y", "z"])
            getattr(self._circuit, pauli)(qubit_idx)
            self._noise_events += 1
            logger.info("NOISE: depolarizing %s on qubit %d", pauli.upper(), qubit_idx)
        if self._dephasing_rate > 0 and random.random() < self._dephasing_rate:
            self._circuit.z(qubit_idx)
            self._noise_events += 1
            logger.info("NOISE: dephasing Z on qubit %d", qubit_idx)

    # ── Public API ──

    def allocate_qubit(self, node_id: str, qubit_id: Optional[str] = None) -> str:
        with self._lock:
            if len(self._qubit_order) >= MAX_QUBITS:
                raise RuntimeError(
                    f"Maximum qubit limit ({MAX_QUBITS}) reached. "
                    f"Click 'Reset all' to clear the circuit before running more experiments."
                )
            qubit_id = qubit_id or f"{node_id}_q{len(self._qubit_order)}"
            if qubit_id in self._registry:
                raise ValueError(f"Qubit '{qubit_id}' already exists.")
            self._registry[qubit_id] = QubitRecord(qubit_id, node_id)
            self._qubit_order.append(qubit_id)
            self._rebuild_circuit()
            return qubit_id

    def apply_gate(self, gate: str, qubit_id: str, target_qubit_id: Optional[str] = None) -> None:
        with self._lock:
            gate = gate.upper()
            ctrl_idx = self._index(qubit_id)
            if gate in SINGLE_QUBIT_GATES:
                self._apply_single(gate, ctrl_idx)
                self._gate_log.append((gate, [ctrl_idx]))
                self._apply_noise(ctrl_idx)
            elif gate in TWO_QUBIT_GATES:
                if target_qubit_id is None:
                    raise ValueError(f"Gate '{gate}' requires a target_qubit_id.")
                tgt_idx = self._index(target_qubit_id)
                self._apply_two(gate, ctrl_idx, tgt_idx)
                self._gate_log.append((gate, [ctrl_idx, tgt_idx]))
                self._apply_noise(ctrl_idx)
                self._apply_noise(tgt_idx)
            else:
                raise ValueError(f"Unsupported gate '{gate}'.")

    def create_bell_pair(self, qubit_a_id: str, qubit_b_id: str) -> None:
        with self._lock:
            idx_a = self._index(qubit_a_id)
            idx_b = self._index(qubit_b_id)
            self._circuit.reset(idx_a)
            self._circuit.reset(idx_b)
            self._circuit.h(idx_a)
            self._apply_noise(idx_a)
            self._circuit.cx(idx_a, idx_b)
            self._apply_noise(idx_a)
            self._apply_noise(idx_b)
            self._gate_log.append(("BELL", [idx_a, idx_b]))
            self._registry[qubit_a_id].entangled_with = qubit_b_id
            self._registry[qubit_b_id].entangled_with = qubit_a_id
            logger.info("Bell pair: %s ↔ %s%s",
                         qubit_a_id, qubit_b_id,
                         " [NOISY]" if self._noise_enabled else "")

    def measure_qubit(self, qubit_id: str, shots: int = 1) -> int:
        with self._lock:
            if self._circuit is None:
                raise RuntimeError("No qubits allocated.")
            idx = self._index(qubit_id)
            if self._noise_enabled and self._dephasing_rate > 0:
                if random.random() < self._dephasing_rate:
                    self._circuit.z(idx)
                    self._noise_events += 1
            meas_circuit = self._circuit.copy()
            cr = ClassicalRegister(1, "meas")
            meas_circuit.add_register(cr)
            meas_circuit.measure(idx, cr[0])
            compiled = transpile(meas_circuit, self._backend)
            job = self._backend.run(compiled, shots=shots)
            counts = job.result().get_counts()
            result = int(max(counts, key=counts.get))
            rec = self._registry[qubit_id]
            rec.measured = True
            rec.measurement_result = result
            return result

    def get_statevector(self) -> list:
        with self._lock:
            if self._circuit is None:
                return []
            sv = Statevector(self._circuit)
            return sv.data.tolist()

    def get_statevector_serialisable(self) -> list[dict]:
        return [{"re": c.real, "im": c.imag} for c in self.get_statevector()]

    def get_registry_snapshot(self) -> dict:
        with self._lock:
            return {qid: rec.to_dict() for qid, rec in self._registry.items()}

    def list_qubits_for_node(self, node_id: str) -> list[str]:
        with self._lock:
            return [qid for qid, rec in self._registry.items() if rec.node_id == node_id]

    def qubit_count(self) -> int:
        return len(self._qubit_order)

    def reset_all(self) -> None:
        with self._lock:
            self._qubit_order.clear()
            self._gate_log.clear()
            self._registry.clear()
            self._circuit = None
            self._noise_events = 0

    def reset_node(self, node_id: str) -> None:
        with self._lock:
            nq = {qid for qid, rec in self._registry.items() if rec.node_id == node_id}
            if not nq: return
            for qid, rec in self._registry.items():
                if rec.entangled_with in nq: rec.entangled_with = None
            self._qubit_order = [q for q in self._qubit_order if q not in nq]
            for qid in nq: del self._registry[qid]
            self._gate_log.clear()
            self._rebuild_circuit()

    # ── Internal ──

    def _index(self, qubit_id: str) -> int:
        if qubit_id not in self._qubit_order:
            raise KeyError(f"Qubit '{qubit_id}' not found.")
        return self._qubit_order.index(qubit_id)

    def _rebuild_circuit(self) -> None:
        n = len(self._qubit_order)
        if n == 0: self._circuit = None; return
        self._circuit = QuantumCircuit(QuantumRegister(n, "q"))
        for gate, indices in self._gate_log:
            if gate == "BELL":
                self._circuit.reset(indices[0]); self._circuit.reset(indices[1])
                self._circuit.h(indices[0]); self._circuit.cx(indices[0], indices[1])
            elif len(indices) == 1: self._apply_single(gate, indices[0])
            else: self._apply_two(gate, indices[0], indices[1])

    def _apply_single(self, gate, idx):
        {"H": self._circuit.h, "X": self._circuit.x, "Y": self._circuit.y,
         "Z": self._circuit.z, "S": self._circuit.s, "T": self._circuit.t,
         "SX": self._circuit.sx}[gate](idx)

    def _apply_two(self, gate, ctrl, tgt):
        {"CNOT": self._circuit.cx, "CX": self._circuit.cx,
         "CZ": self._circuit.cz, "SWAP": self._circuit.swap}[gate](ctrl, tgt)
