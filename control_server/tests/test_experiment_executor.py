"""
Integration tests for ExperimentExecutor.

These tests verify that the full experiment pipeline works correctly
when the NodeRegistry, EntanglementManager, and QuantumStateManager
are wired together.

Because we need nodes to be "online", we inject mock NodeRegistry
entries rather than spinning up actual HTTP servers.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from control_server.quantum_state_manager import QuantumStateManager
from control_server.node_registry         import NodeRegistry
from control_server.entanglement_manager  import EntanglementManager
from control_server.experiment_executor   import ExperimentExecutor


@pytest.fixture
def setup():
    qsm     = QuantumStateManager()
    nodes   = NodeRegistry()
    ent     = EntanglementManager(qsm, nodes)
    executor = ExperimentExecutor(qsm, ent, nodes)
    # Register two mock nodes so they appear online
    nodes.register("node_a", "http://fake-node-a:8000")
    nodes.register("node_b", "http://fake-node-b:8000")
    nodes.register("node_c", "http://fake-node-c:8000")
    return qsm, nodes, ent, executor


class TestEntangleExperiment:
    def test_entangle_produces_real_bell_pair(self, setup):
        qsm, _, _, executor = setup
        result = executor.run_entangle("node_a", "node_b")
        assert result.error is None
        d = result.to_dict()
        assert d["source"] == "node_a"
        assert d["target"] == "node_b"
        # The statevector must exist and show 4 amplitudes (2 qubits)
        sv = d["statevector"]
        assert len(sv) == 4

    def test_entangle_offline_node_fails(self, setup):
        _, nodes, _, executor = setup
        # node_c is online; node_x is not registered at all
        result = executor.run_entangle("node_a", "node_x")
        assert result.error is not None


class TestTeleportExperiment:
    def test_teleport_completes(self, setup):
        _, _, _, executor = setup
        result = executor.run_teleport("node_a", "node_b", shots=128)
        assert result.error is None
        d = result.to_dict()
        assert d["type"] == "teleport"
        assert d["m1"] in (0, 1)
        assert d["m2"] in (0, 1)
        assert d["final_result"] in (0, 1)

    def test_teleport_result_is_0_or_1(self, setup):
        _, _, _, executor = setup
        for _ in range(5):
            result = executor.run_teleport("node_a", "node_b", shots=1)
            assert result.error is None
            assert result.data["final_result"] in (0, 1)


class TestGHZExperiment:
    def test_ghz_three_nodes(self, setup):
        qsm, _, _, executor = setup
        result = executor.run_ghz(["node_a", "node_b", "node_c"])
        assert result.error is None
        d = result.to_dict()
        sv = d["statevector"]
        # 3-qubit GHZ: statevector has 8 entries
        assert len(sv) == 8

    def test_ghz_requires_two_or_more_nodes(self, setup):
        _, _, _, executor = setup
        result = executor.run_ghz(["node_a"])
        assert result.error is not None
