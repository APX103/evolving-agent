"""
Lightweight graph execution engine.

No external dependencies.  Pure asyncio + topological sort.
Supports:
  - sequential / parallel execution (asyncio.gather)
  - conditional edges  (callables evaluated against shared state)
  - retry loops        (per-Node retry_count)
  - subgraph nesting   (Node.subgraph -> Graph)
  - timeouts           (per-Node timeout in seconds)
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

State = Dict[str, Any]
Condition = Optional[Callable[[State], bool]]
NodeFunc = Callable[[State], Any]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """A node in the execution graph."""
    name: str
    func: Optional[NodeFunc] = None
    retry_count: int = 0
    timeout: Optional[float] = None
    subgraph: Optional["Graph"] = None

    def __post_init__(self):
        if self.func is None and self.subgraph is None:
            raise ValueError(f"Node '{self.name}' must have either func or subgraph")


@dataclass
class Edge:
    """Directed edge with optional condition."""
    source: str
    target: str
    condition: Condition = None


@dataclass
class Graph:
    """Execution graph."""
    name: str = "graph"
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Builder helpers
    # ------------------------------------------------------------------

    def add_node(self, node: Node) -> "Graph":
        self.nodes[node.name] = node
        return self

    def add_edge(self, edge: Edge) -> "Graph":
        self.edges.append(edge)
        return self

    def add_nodes(self, *nodes: Node) -> "Graph":
        for n in nodes:
            self.nodes[n.name] = n
        return self

    def add_edges(self, *edges: Edge) -> "Graph":
        self.edges.extend(edges)
        return self

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, state: State) -> State:
        """
        Execute the graph starting from *state*.

        Returns the mutated state dict (also mutated in-place).
        """
        logger.info(f"[Graph:{self.name}] start execution with {len(self.nodes)} nodes")

        # Build adjacency + in-degree
        in_degree: Dict[str, int] = {name: 0 for name in self.nodes}
        outgoing: Dict[str, List[Edge]] = {name: [] for name in self.nodes}

        for edge in self.edges:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise ValueError(f"Edge references unknown node: {edge}")
            in_degree[edge.target] += 1
            outgoing[edge.source].append(edge)

        remaining_in_degree = in_degree.copy()
        executed: Set[str] = set()
        failed: Set[str] = set()
        retry_attempts: Dict[str, int] = {}

        while len(executed) + len(failed) < len(self.nodes):
            ready = [
                name for name in self.nodes
                if name not in executed and name not in failed
                and remaining_in_degree[name] == 0
            ]

            if not ready:
                unresolved = [
                    name for name in self.nodes
                    if name not in executed and name not in failed
                ]
                if unresolved:
                    logger.error(
                        f"[Graph:{self.name}] deadlock / unsatisfied dependencies: {unresolved}"
                    )
                    for name in unresolved:
                        failed.add(name)
                        state.setdefault("__errors", []).append(
                            f"Node '{name}' deadlocked"
                        )
                break

            # Execute ready nodes in parallel
            logger.info(f"[Graph:{self.name}] ready nodes: {ready}")
            results = await asyncio.gather(
                *[self._run_node(name, state, retry_attempts) for name in ready],
                return_exceptions=True,
            )

            for name, result in zip(ready, results):
                if isinstance(result, Exception):
                    logger.error(f"[Graph:{self.name}] Node '{name}' failed: {result}")
                    failed.add(name)
                    state.setdefault("__errors", []).append(
                        f"Node '{name}': {result}"
                    )
                else:
                    executed.add(name)
                    state[name] = result
                    logger.info(f"[Graph:{self.name}] Node '{name}' succeeded")

                    for edge in outgoing[name]:
                        cond = edge.condition
                        if cond is None or cond(state):
                            remaining_in_degree[edge.target] -= 1
                        else:
                            logger.debug(
                                f"[Graph:{self.name}] Edge {edge.source}->{edge.target} "
                                "condition evaluated False"
                            )

        state["__executed"] = list(executed)
        state["__failed"] = list(failed)
        state["__graph_name"] = self.name
        logger.info(
            f"[Graph:{self.name}] finished: {len(executed)} succeeded, {len(failed)} failed"
        )
        return state

    # ------------------------------------------------------------------
    # Node runner
    # ------------------------------------------------------------------

    async def _run_node(
        self,
        name: str,
        state: State,
        retry_attempts: Dict[str, int],
    ) -> Any:
        """Run a single node with retry / timeout / subgraph support."""
        node = self.nodes[name]
        max_retries = node.retry_count
        attempt = 0

        while True:
            try:
                coro = self._invoke_node(node, state)
                if node.timeout is not None:
                    result = await asyncio.wait_for(coro, timeout=node.timeout)
                else:
                    result = await coro
                return result
            except Exception as exc:
                attempt += 1
                retry_attempts[name] = attempt
                if attempt <= max_retries:
                    logger.warning(
                        f"[Graph:{self.name}] Node '{name}' failed (attempt {attempt}), "
                        f"retrying... ({max_retries} max retries)"
                    )
                    await asyncio.sleep(0.05 * attempt)
                    continue
                else:
                    raise exc

    async def _invoke_node(self, node: Node, state: State) -> Any:
        """Invoke the node's func or subgraph."""
        if node.subgraph is not None:
            logger.info(f"[Graph:{self.name}] Entering subgraph '{node.subgraph.name}'")
            sub_state = await node.subgraph.execute(state.copy())
            for k, v in sub_state.items():
                if not k.startswith("__") or k in ("__errors",):
                    state[k] = v
            return sub_state.get("__result", sub_state)

        if node.func is None:
            raise RuntimeError(f"Node '{node.name}' has no func or subgraph")

        if inspect.iscoroutinefunction(node.func):
            return await node.func(state)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, node.func, state)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_node(self, name: str) -> Optional[Node]:
        return self.nodes.get(name)

    def predecessors(self, name: str) -> List[str]:
        return [e.source for e in self.edges if e.target == name]

    def successors(self, name: str) -> List[str]:
        return [e.target for e in self.edges if e.source == name]
