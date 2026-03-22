"""
EntanglementManager
===================
Orchestrates entanglement with decoherence simulation.

Entangled pairs now track fidelity that decays over time:
    F(t) = F0 * exp(-decoherence_rate * t)

Pairs below the fidelity threshold are considered expired.
The routing engine can use fidelity info for max-fidelity routing.
"""

import uuid
import time
import math
import logging
from typing import Optional

from .quantum_state_manager import QuantumStateManager
from .node_registry import NodeRegistry

logger = logging.getLogger("EntanglementManager")


class EntanglementRecord:
    def __init__(
        self,
        link_id: str,
        node_a_id: str,
        qubit_a_id: str,
        node_b_id: str,
        qubit_b_id: str,
        initial_fidelity: float = 1.0,
        decoherence_rate: float = 0.01,
    ):
        self.link_id          = link_id
        self.node_a_id        = node_a_id
        self.qubit_a_id       = qubit_a_id
        self.node_b_id        = node_b_id
        self.qubit_b_id       = qubit_b_id
        self.created_at       = time.time()
        self.initial_fidelity = initial_fidelity
        self.decoherence_rate = decoherence_rate
        self.consumed         = False

    @property
    def age(self) -> float:
        """Seconds since creation."""
        return time.time() - self.created_at

    @property
    def fidelity(self) -> float:
        """Current fidelity after decoherence: F(t) = F0 * exp(-rate * t)."""
        if self.consumed:
            return 0.0
        return self.initial_fidelity * math.exp(-self.decoherence_rate * self.age)

    @property
    def is_alive(self) -> bool:
        """Pair is usable if fidelity > 0.5 and not consumed."""
        return not self.consumed and self.fidelity > 0.5

    def consume(self):
        """Mark pair as consumed (used in teleportation or swapping)."""
        self.consumed = True

    def to_dict(self) -> dict:
        return {
            "link_id":      self.link_id,
            "node_a":       self.node_a_id,
            "qubit_a":      self.qubit_a_id,
            "node_b":       self.node_b_id,
            "qubit_b":      self.qubit_b_id,
            "created_at":   self.created_at,
            "fidelity":     round(self.fidelity, 4),
            "age_seconds":  round(self.age, 1),
            "is_alive":     self.is_alive,
            "consumed":     self.consumed,
            "decoherence_rate": self.decoherence_rate,
        }


class EntanglementManager:
    def __init__(
        self,
        qsm: QuantumStateManager,
        node_registry: NodeRegistry,
        decoherence_rate: float = 0.01,
        fidelity_threshold: float = 0.5,
    ):
        self._qsm                = qsm
        self._nodes              = node_registry
        self._links: dict[str, EntanglementRecord] = {}
        self.decoherence_rate    = decoherence_rate      # F(t) decay rate
        self.fidelity_threshold  = fidelity_threshold    # below this = expired

    def set_decoherence_rate(self, rate: float):
        """Change the decoherence rate for future pairs."""
        self.decoherence_rate = rate
        logger.info("Decoherence rate set to %.4f", rate)

    def create_link(
        self,
        node_a_id: str,
        node_b_id: str,
        qubit_a_id: Optional[str] = None,
        qubit_b_id: Optional[str] = None,
        exp_id: str = "",
    ) -> EntanglementRecord:
        for nid in (node_a_id, node_b_id):
            if not self._nodes.is_online(nid):
                raise RuntimeError(f"Cannot create entanglement link: node '{nid}' is offline.")

        link_id    = str(uuid.uuid4())[:8]
        qubit_a_id = qubit_a_id or f"ent_{exp_id}_a"
        qubit_b_id = qubit_b_id or f"ent_{exp_id}_b"

        self._qsm.allocate_qubit(node_a_id, qubit_a_id)
        self._qsm.allocate_qubit(node_b_id, qubit_b_id)
        self._qsm.create_bell_pair(qubit_a_id, qubit_b_id)

        record = EntanglementRecord(
            link_id, node_a_id, qubit_a_id, node_b_id, qubit_b_id,
            initial_fidelity=1.0,
            decoherence_rate=self.decoherence_rate,
        )
        self._links[link_id] = record

        logger.info(
            "[%s] Entanglement link %s: %s:%s ↔ %s:%s (decoherence_rate=%.4f)",
            exp_id, link_id, node_a_id, qubit_a_id, node_b_id, qubit_b_id,
            self.decoherence_rate,
        )
        return record

    def get_link(self, link_id: str) -> Optional[EntanglementRecord]:
        return self._links.get(link_id)

    def all_links(self) -> list[dict]:
        """Return all links with current fidelity."""
        return [r.to_dict() for r in self._links.values()]

    def alive_links(self) -> list[dict]:
        """Return only alive (fidelity > threshold, not consumed) links."""
        return [r.to_dict() for r in self._links.values() if r.is_alive]

    def get_link_fidelity(self, node_a: str, node_b: str) -> float:
        """Get the best alive fidelity between two nodes. Returns 0 if none."""
        best = 0.0
        for r in self._links.values():
            if not r.is_alive:
                continue
            if (r.node_a_id == node_a and r.node_b_id == node_b) or \
               (r.node_a_id == node_b and r.node_b_id == node_a):
                best = max(best, r.fidelity)
        return best

    def cleanup_expired(self) -> int:
        """Remove expired pairs. Returns count removed."""
        expired = [lid for lid, r in self._links.items() if not r.is_alive]
        for lid in expired:
            del self._links[lid]
        if expired:
            logger.info("Cleaned up %d expired entanglement links", len(expired))
        return len(expired)

    def get_decoherence_config(self) -> dict:
        return {
            "decoherence_rate": self.decoherence_rate,
            "fidelity_threshold": self.fidelity_threshold,
            "active_pairs": len([r for r in self._links.values() if r.is_alive]),
            "expired_pairs": len([r for r in self._links.values() if not r.is_alive]),
            "total_pairs": len(self._links),
        }

    def reset(self) -> None:
        self._links.clear()
        logger.info("Entanglement links cleared")
