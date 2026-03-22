"""
Tests for QuantumStateManager — the core of the redesigned CQNE architecture.

These tests verify that entanglement is PHYSICALLY REAL in the global statevector,
not a registry flag.  This is the fundamental property the old design lacked.

Run:
    cd cqne_redesigned/control_server
    pytest tests/ -v
"""

import cmath
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from control_server.quantum_state_manager import QuantumStateManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def qsm():
    mgr = QuantumStateManager()
    yield mgr
    mgr.reset_all()


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

class TestAllocate:
    def test_allocate_returns_qubit_id(self, qsm):
        qid = qsm.allocate_qubit("node_a", "q0")
        assert qid == "q0"

    def test_auto_id_generated(self, qsm):
        qid = qsm.allocate_qubit("node_a")
        assert "node_a" in qid

    def test_duplicate_raises(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        with pytest.raises(ValueError, match="already exists"):
            qsm.allocate_qubit("node_a", "q0")

    def test_multiple_qubits_different_nodes(self, qsm):
        qa = qsm.allocate_qubit("node_a", "q_a")
        qb = qsm.allocate_qubit("node_b", "q_b")
        assert qa == "q_a"
        assert qb == "q_b"
        reg = qsm.get_registry_snapshot()
        assert reg["q_a"]["node_id"] == "node_a"
        assert reg["q_b"]["node_id"] == "node_b"

    def test_list_qubits_for_node(self, qsm):
        qsm.allocate_qubit("node_a", "q_a1")
        qsm.allocate_qubit("node_a", "q_a2")
        qsm.allocate_qubit("node_b", "q_b1")
        assert set(qsm.list_qubits_for_node("node_a")) == {"q_a1", "q_a2"}
        assert qsm.list_qubits_for_node("node_b") == ["q_b1"]


# ---------------------------------------------------------------------------
# Single-qubit gates
# ---------------------------------------------------------------------------

class TestSingleQubitGates:
    def test_hadamard_creates_superposition(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        qsm.apply_gate("H", "q0")
        sv = qsm.get_statevector()
        # |+⟩ = (|0⟩ + |1⟩) / √2  → both amplitudes ≈ 1/√2
        expected = 1.0 / math.sqrt(2)
        assert abs(abs(sv[0]) - expected) < 1e-6
        assert abs(abs(sv[1]) - expected) < 1e-6

    def test_x_gate_flips_qubit(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        qsm.apply_gate("X", "q0")
        sv = qsm.get_statevector()
        # After X: |1⟩ → amplitude[1] = 1, amplitude[0] = 0
        assert abs(sv[0]) < 1e-6
        assert abs(abs(sv[1]) - 1.0) < 1e-6

    def test_z_gate_phase_flip(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        qsm.apply_gate("H", "q0")  # |+⟩
        qsm.apply_gate("Z", "q0")  # |−⟩
        sv = qsm.get_statevector()
        expected = 1.0 / math.sqrt(2)
        assert abs(abs(sv[0]) - expected) < 1e-6
        assert abs(abs(sv[1]) - expected) < 1e-6
        # Z flips the sign of |1⟩ component
        assert sv[1].real < 0

    def test_unknown_gate_raises(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        with pytest.raises(ValueError, match="Unsupported gate"):
            qsm.apply_gate("NOTAGATE", "q0")

    def test_gate_on_missing_qubit_raises(self, qsm):
        with pytest.raises(KeyError):
            qsm.apply_gate("H", "nonexistent")


# ---------------------------------------------------------------------------
# Cross-node Bell pair — THIS IS THE CRITICAL TEST
# ---------------------------------------------------------------------------

class TestCrossNodeBellPair:
    """
    These tests verify that entanglement between qubits on different nodes
    is PHYSICALLY REAL — not a flag in a registry.

    A real Bell pair has the property that measuring one qubit collapses
    the other.  The statevector of a Bell pair has a specific structure:
      |Φ+⟩ = (|00⟩ + |11⟩) / √2

    This means:
      - amplitude[0] (|00⟩) ≈ 1/√2
      - amplitude[1] (|01⟩) ≈ 0
      - amplitude[2] (|10⟩) ≈ 0
      - amplitude[3] (|11⟩) ≈ 1/√2

    If entanglement were just a flag, the statevector would NOT show this
    structure — it would be a product state |0⟩ ⊗ |0⟩ with extra metadata.
    """

    def test_bell_pair_statevector_structure(self, qsm):
        """Verify the global statevector is actually |Φ+⟩ after create_bell_pair."""
        qsm.allocate_qubit("node_a", "q_a")
        qsm.allocate_qubit("node_b", "q_b")
        qsm.create_bell_pair("q_a", "q_b")

        sv = qsm.get_statevector()
        assert len(sv) == 4, "2-qubit system must have 4 amplitudes"

        expected = 1.0 / math.sqrt(2)
        # |Φ+⟩ = 1/√2 (|00⟩ + |11⟩)
        assert abs(abs(sv[0]) - expected) < 1e-6, f"|00⟩ amplitude wrong: {sv[0]}"
        assert abs(sv[1])                 < 1e-6, f"|01⟩ should be 0: {sv[1]}"
        assert abs(sv[2])                 < 1e-6, f"|10⟩ should be 0: {sv[2]}"
        assert abs(abs(sv[3]) - expected) < 1e-6, f"|11⟩ amplitude wrong: {sv[3]}"

    def test_bell_pair_is_not_product_state(self, qsm):
        """
        A product state |ψ⟩⊗|φ⟩ can be written as a tensor product.
        A Bell state CANNOT.  We check this by verifying the statevector
        cannot be factored as [a*c, a*d, b*c, b*d].
        """
        qsm.allocate_qubit("node_a", "q_a")
        qsm.allocate_qubit("node_b", "q_b")
        qsm.create_bell_pair("q_a", "q_b")
        sv = qsm.get_statevector()

        # For a product state: sv[0]*sv[3] == sv[1]*sv[2]
        # For |Φ+⟩: sv[0]*sv[3] = 1/2,  sv[1]*sv[2] = 0
        product_test = abs(sv[0] * sv[3]) - abs(sv[1] * sv[2])
        assert product_test > 0.4, (
            "Statevector looks like a product state — entanglement is not real!"
        )

    def test_entanglement_registry_records_partner(self, qsm):
        qsm.allocate_qubit("node_a", "q_a")
        qsm.allocate_qubit("node_b", "q_b")
        qsm.create_bell_pair("q_a", "q_b")
        reg = qsm.get_registry_snapshot()
        assert reg["q_a"]["entangled_with"] == "q_b"
        assert reg["q_b"]["entangled_with"] == "q_a"

    def test_three_node_ghz_statevector(self, qsm):
        """
        GHZ state across 3 qubits (different nodes):
          |GHZ⟩ = (|000⟩ + |111⟩) / √2

        Verify amplitudes[0] and amplitudes[7] ≈ 1/√2, rest ≈ 0.
        """
        for nid in ("node_a", "node_b", "node_c"):
            qsm.allocate_qubit(nid, f"q_{nid}")

        qsm.apply_gate("H", "q_node_a")
        qsm.apply_gate("CNOT", "q_node_a", "q_node_b")
        qsm.apply_gate("CNOT", "q_node_a", "q_node_c")

        sv = qsm.get_statevector()
        assert len(sv) == 8, "3-qubit system must have 8 amplitudes"

        expected = 1.0 / math.sqrt(2)
        assert abs(abs(sv[0]) - expected) < 1e-6, f"|000⟩ wrong: {sv[0]}"
        assert abs(abs(sv[7]) - expected) < 1e-6, f"|111⟩ wrong: {sv[7]}"
        for i in range(1, 7):
            assert abs(sv[i]) < 1e-6, f"sv[{i}] should be 0 in GHZ: {sv[i]}"


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

class TestMeasurement:
    def test_measure_zero_state_returns_zero(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        result = qsm.measure_qubit("q0", shots=100)
        assert result == 0

    def test_measure_one_state_returns_one(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        qsm.apply_gate("X", "q0")
        result = qsm.measure_qubit("q0", shots=100)
        assert result == 1

    def test_measurement_recorded_in_registry(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        qsm.measure_qubit("q0", shots=1)
        reg = qsm.get_registry_snapshot()
        assert reg["q0"]["measured"] is True
        assert reg["q0"]["measurement_result"] in (0, 1)

    def test_measure_missing_qubit_raises(self, qsm):
        qsm.allocate_qubit("node_a", "q0")
        with pytest.raises(KeyError):
            qsm.measure_qubit("does_not_exist")


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_all_clears_everything(self, qsm):
        qsm.allocate_qubit("node_a", "q_a")
        qsm.allocate_qubit("node_b", "q_b")
        qsm.create_bell_pair("q_a", "q_b")
        qsm.reset_all()
        assert qsm.get_registry_snapshot() == {}
        assert qsm.get_statevector() == []

    def test_reset_node_removes_only_that_node(self, qsm):
        qsm.allocate_qubit("node_a", "q_a")
        qsm.allocate_qubit("node_b", "q_b")
        qsm.reset_node("node_a")
        reg = qsm.get_registry_snapshot()
        assert "q_a" not in reg
        assert "q_b" in reg

    def test_reset_node_breaks_entanglement_ref_in_partner(self, qsm):
        qsm.allocate_qubit("node_a", "q_a")
        qsm.allocate_qubit("node_b", "q_b")
        qsm.create_bell_pair("q_a", "q_b")
        qsm.reset_node("node_a")
        reg = qsm.get_registry_snapshot()
        assert reg["q_b"]["entangled_with"] is None
