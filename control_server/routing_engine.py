"""
RoutingEngine
=============
Computes entanglement paths between nodes.

Strategies:
  - shortest_path (default): minimum hops (BFS)
  - max_fidelity: highest end-to-end fidelity (Dijkstra-like)
    Falls back to shortest_path if no fidelity data exists.
"""

import logging
import math
import heapq
from collections import deque
from typing import Optional, Callable

logger = logging.getLogger("RoutingEngine")


class RoutingEngine:
    def __init__(self):
        self._adjacency: Optional[dict[str, set[str]]] = None
        self._strategy: str = "shortest_path"
        self._fidelity_fn: Optional[Callable[[str, str], float]] = None

    def set_topology(self, adjacency: dict[str, list[str]]) -> None:
        self._adjacency = {k: set(v) for k, v in adjacency.items()}
        logger.info("Custom topology set: %s", {k: list(v) for k, v in self._adjacency.items()})

    def clear_topology(self) -> None:
        self._adjacency = None
        logger.info("Topology cleared — full mesh")

    def get_topology(self) -> Optional[dict]:
        if self._adjacency is None:
            return None
        return {k: list(v) for k, v in self._adjacency.items()}

    def set_strategy(self, strategy: str) -> None:
        if strategy not in ("shortest_path", "max_fidelity"):
            raise ValueError(f"Unknown strategy: {strategy}")
        self._strategy = strategy
        logger.info("Routing strategy: '%s'", strategy)

    def get_strategy(self) -> str:
        return self._strategy

    def set_fidelity_function(self, fn: Callable[[str, str], float]) -> None:
        self._fidelity_fn = fn

    def find_path(self, source: str, target: str, online_nodes: set[str]) -> Optional[list[str]]:
        if source not in online_nodes or target not in online_nodes:
            return None
        if source == target:
            return [source]

        if self._strategy == "max_fidelity" and self._fidelity_fn is not None:
            path = self._find_max_fidelity_path(source, target, online_nodes)
            if path is not None:
                return path
            # Fall back to shortest path if max fidelity finds no route
            logger.info("Max-fidelity found no path, falling back to shortest_path")

        return self._find_shortest_path(source, target, online_nodes)

    def find_path_with_fidelity(self, source: str, target: str, online_nodes: set[str]) -> tuple[Optional[list[str]], float]:
        path = self.find_path(source, target, online_nodes)
        if path is None or len(path) < 2:
            return path, 0.0

        if self._fidelity_fn:
            fidelity = 1.0
            for i in range(len(path) - 1):
                hop_f = self._fidelity_fn(path[i], path[i + 1])
                if hop_f > 0:
                    fidelity *= hop_f
                else:
                    fidelity *= 0.95  # default per-hop estimate when no link data
        else:
            fidelity = 0.95 ** (len(path) - 1)

        return path, round(fidelity, 4)

    def _find_shortest_path(self, source: str, target: str, online_nodes: set[str]) -> Optional[list[str]]:
        visited = {source}
        queue = deque([[source]])
        while queue:
            path = queue.popleft()
            current = path[-1]
            if current == target:
                logger.info("Shortest path: %s (%d hops)", " -> ".join(path), len(path) - 1)
                return path
            for neighbor in self._get_neighbors(current, online_nodes):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return None

    def _find_max_fidelity_path(self, source: str, target: str, online_nodes: set[str]) -> Optional[list[str]]:
        if not self._fidelity_fn:
            return None

        # Check if any fidelity data exists at all
        has_any_fidelity = False
        for node in online_nodes:
            for neighbor in self._get_neighbors(node, online_nodes):
                if self._fidelity_fn(node, neighbor) > 0:
                    has_any_fidelity = True
                    break
            if has_any_fidelity:
                break

        if not has_any_fidelity:
            # No fidelity data available — can't do max fidelity routing
            return None

        # Dijkstra: minimize -log(fidelity) = maximize fidelity product
        heap = [(0.0, [source])]
        visited = set()

        while heap:
            neg_log_f, path = heapq.heappop(heap)
            current = path[-1]

            if current == target:
                fidelity = math.exp(-neg_log_f)
                logger.info("Max-fidelity path: %s (fidelity=%.4f)", " -> ".join(path), fidelity)
                return path

            if current in visited:
                continue
            visited.add(current)

            for neighbor in self._get_neighbors(current, online_nodes):
                if neighbor not in visited:
                    hop_fidelity = self._fidelity_fn(current, neighbor)
                    if hop_fidelity > 0:
                        new_cost = neg_log_f - math.log(hop_fidelity)
                        heapq.heappush(heap, (new_cost, path + [neighbor]))

        return None  # no path with fidelity data — caller will fall back

    def _get_neighbors(self, node_id: str, online_nodes: set[str]) -> set[str]:
        if self._adjacency is not None:
            return self._adjacency.get(node_id, set()) & online_nodes
        else:
            return online_nodes - {node_id}
