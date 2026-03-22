"""
CQNE Layer 3 — Quantum Internet Router
=======================================

Runs on the dedicated router laptop.  Provides:

  POST /nodes/register          Node announces itself (called by nodes on startup)
  POST /nodes/heartbeat         Node keepalive ping
  GET  /nodes                   List all known nodes + online/offline status
  POST /route                   Request an entanglement path between two nodes
  GET  /topology                Return the full network graph
  GET  /health                  Liveness probe

Routing algorithm
-----------------
Currently uses shortest-path (BFS) over the live node graph.  Offline nodes
are excluded from path computation.  Nodes are marked offline if no heartbeat
is received within OFFLINE_THRESHOLD seconds.

Start
-----
  python router.py
  # or with custom port:
  ROUTER_PORT=9000 python router.py
"""

import os
import time
import logging
from collections import deque
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("Router")

OFFLINE_THRESHOLD = 90   # seconds — node considered offline after this many seconds without heartbeat

app = FastAPI(title="CQNE Quantum Internet Router", version="1.0.0")


# ---------------------------------------------------------------------------
# In-memory node table
# ---------------------------------------------------------------------------

class NodeRecord:
    def __init__(self, node_id: str, url: str):
        self.node_id    = node_id
        self.url        = url
        self.last_seen  = time.time()

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) < OFFLINE_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "node_id":   self.node_id,
            "url":       self.url,
            "online":    self.online,
            "last_seen": self.last_seen,
        }


_nodes: dict[str, NodeRecord] = {}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    node_id: str
    url:     str

class HeartbeatRequest(BaseModel):
    node_id: str

class RouteRequest(BaseModel):
    source_node_id: str
    target_node_id: str


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

def _compute_path(source: str, target: str) -> Optional[list[str]]:
    """
    BFS shortest path between source and target using only online nodes.
    Returns a list of node_id strings representing the path, or None if
    no path exists.

    In the physical CQNE topology all nodes connect through the router,
    so the path is always [source, target] if both are online.
    This function is written generically so it works for multi-hop too.
    """
    online_nodes = {nid for nid, rec in _nodes.items() if rec.online}
    if source not in online_nodes or target not in online_nodes:
        return None

    # BFS
    visited = {source}
    queue   = deque([[source]])

    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == target:
            return path
        # In a star topology every node is connected to every other node
        # via the router.  For a mesh you would consult an adjacency list.
        for neighbour in online_nodes:
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(path + [neighbour])

    return None   # no path found


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "role": "router", "nodes_registered": len(_nodes)}


@app.post("/nodes/register")
def register_node(req: RegisterRequest):
    """Called by a node on startup to announce itself."""
    if req.node_id in _nodes:
        _nodes[req.node_id].url        = req.url
        _nodes[req.node_id].last_seen  = time.time()
        logger.info("Re-registered node '%s' at %s", req.node_id, req.url)
    else:
        _nodes[req.node_id] = NodeRecord(req.node_id, req.url)
        logger.info("Registered new node '%s' at %s", req.node_id, req.url)
    return {"status": "registered", "node_id": req.node_id}


@app.post("/nodes/heartbeat")
def heartbeat(req: HeartbeatRequest):
    """Called by nodes every 30 s to stay marked as online."""
    if req.node_id not in _nodes:
        raise HTTPException(status_code=404, detail=f"Node '{req.node_id}' not registered.")
    _nodes[req.node_id].last_seen = time.time()
    return {"status": "ok", "node_id": req.node_id}


@app.get("/nodes")
def list_nodes():
    """Return all registered nodes with their online/offline status."""
    return {"nodes": [rec.to_dict() for rec in _nodes.values()]}


@app.post("/route")
def compute_route(req: RouteRequest):
    """
    Compute the best entanglement path between two nodes.
    Returns the ordered list of node IDs along the path.
    """
    if req.source_node_id not in _nodes:
        raise HTTPException(status_code=404, detail=f"Source node '{req.source_node_id}' not registered.")
    if req.target_node_id not in _nodes:
        raise HTTPException(status_code=404, detail=f"Target node '{req.target_node_id}' not registered.")

    path = _compute_path(req.source_node_id, req.target_node_id)
    if path is None:
        raise HTTPException(
            status_code=503,
            detail=f"No path found between '{req.source_node_id}' and '{req.target_node_id}'. "
                   f"One or both nodes may be offline."
        )

    logger.info("Route computed: %s → %s  via %s", req.source_node_id, req.target_node_id, path)
    return {
        "source": req.source_node_id,
        "target": req.target_node_id,
        "path":   path,
        "hops":   len(path) - 1,
    }


@app.get("/topology")
def topology():
    """Return the full network topology (all nodes, online status, URLs)."""
    return {
        "topology": {
            "nodes": [rec.to_dict() for rec in _nodes.values()],
            "online_count":  sum(1 for r in _nodes.values() if r.online),
            "offline_count": sum(1 for r in _nodes.values() if not r.online),
        }
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("ROUTER_PORT", "9000"))
    host = os.getenv("ROUTER_HOST", "0.0.0.0")
    logger.info("🔀 Starting CQNE Router on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
