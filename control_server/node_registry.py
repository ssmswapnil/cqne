"""
NodeRegistry
============
Tracks every CQNE node: its ID, URL, online/offline status, and the
list of qubit IDs it logically "owns" in the global quantum state.

In the redesigned architecture nodes are logical abstractions — they
hold no quantum state themselves.  The NodeRegistry is the authoritative
source of which node_id maps to which IP:port and which qubits.
"""

import time
import logging
from typing import Optional

logger = logging.getLogger("NodeRegistry")

OFFLINE_THRESHOLD = 90  # seconds


class NodeRecord:
    def __init__(self, node_id: str, url: str):
        self.node_id   = node_id
        self.url       = url
        self.last_seen = time.time()

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) < OFFLINE_THRESHOLD

    def touch(self) -> None:
        self.last_seen = time.time()

    def to_dict(self) -> dict:
        return {
            "node_id":   self.node_id,
            "url":       self.url,
            "online":    self.online,
            "last_seen": self.last_seen,
        }


class NodeRegistry:
    """
    Thread-safe registry of all CQNE nodes.

    Nodes register themselves on startup and send periodic heartbeats.
    The control server uses this registry to:
      - verify nodes are online before starting experiments
      - look up the URL for a node when it needs to send a command
      - report network topology to operators
    """

    def __init__(self):
        self._nodes: dict[str, NodeRecord] = {}

    def register(self, node_id: str, url: str) -> NodeRecord:
        if node_id in self._nodes:
            self._nodes[node_id].url = url
            self._nodes[node_id].touch()
            logger.info("Re-registered node '%s' at %s", node_id, url)
        else:
            self._nodes[node_id] = NodeRecord(node_id, url)
            logger.info("Registered new node '%s' at %s", node_id, url)
        return self._nodes[node_id]

    def heartbeat(self, node_id: str) -> None:
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not registered.")
        self._nodes[node_id].touch()

    def get(self, node_id: str) -> Optional[NodeRecord]:
        return self._nodes.get(node_id)

    def get_url(self, node_id: str) -> str:
        rec = self._nodes.get(node_id)
        if rec is None:
            raise KeyError(f"Node '{node_id}' not in registry.")
        return rec.url

    def all_nodes(self) -> list[NodeRecord]:
        return list(self._nodes.values())

    def online_nodes(self) -> list[NodeRecord]:
        return [r for r in self._nodes.values() if r.online]

    def is_online(self, node_id: str) -> bool:
        rec = self._nodes.get(node_id)
        return rec is not None and rec.online

    def snapshot(self) -> dict:
        nodes = [r.to_dict() for r in self._nodes.values()]
        return {
            "nodes":         nodes,
            "online_count":  sum(1 for r in self._nodes.values() if r.online),
            "offline_count": sum(1 for r in self._nodes.values() if not r.online),
        }
