#!/usr/bin/env python3
"""
Workflow Graph Engine tests
- Sequential execution
- Parallel execution
- Conditional branch
- Retry loop
- Subgraph nesting
- Mermaid visualizer
"""
import os
import sys
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agent.workflow import Graph, Node, Edge, generate_mermaid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_add(state):
    await asyncio.sleep(0.01)
    state["value"] = state.get("value", 0) + 1
    return state["value"]


def _sync_add(state):
    state["value"] = state.get("value", 0) + 1
    return state["value"]


# ---------------------------------------------------------------------------
# Sequential
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sequential_execution():
    """Nodes linked by edges run one after another."""
    g = Graph(name="seq").add_nodes(
        Node(name="a", func=_async_add),
        Node(name="b", func=_async_add),
        Node(name="c", func=_async_add),
    ).add_edges(
        Edge("a", "b"),
        Edge("b", "c"),
    )

    state = {"value": 0}
    result = await g.execute(state)

    assert result["value"] == 3
    assert set(result["__executed"]) == {"a", "b", "c"}
    assert result["__failed"] == []


# ---------------------------------------------------------------------------
# Parallel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_execution():
    """Independent nodes run in parallel (asyncio.gather)."""
    timestamps = {}

    async def _record(name, state):
        timestamps[name] = time.monotonic()
        await asyncio.sleep(0.05)
        return name

    g = Graph(name="par").add_nodes(
        Node(name="a", func=lambda s: _record("a", s)),
        Node(name="b", func=lambda s: _record("b", s)),
        Node(name="c", func=lambda s: _record("c", s)),
    )

    state = {}
    t0 = time.monotonic()
    result = await g.execute(state)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.12, f"Expected parallel, took {elapsed:.3f}s"
    assert set(result["__executed"]) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Conditional branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conditional_branch_true():
    """Edge with condition=True is followed."""
    g = Graph(name="cond_true").add_nodes(
        Node(name="start", func=lambda s: s.update({"flag": True}) or "ok"),
        Node(name="success_path", func=_async_add),
        Node(name="fail_path", func=lambda s: s.update({"value": 999}) or "nope"),
    ).add_edges(
        Edge("start", "success_path", condition=lambda s: s.get("flag") is True),
        Edge("start", "fail_path", condition=lambda s: s.get("flag") is not True),
    )

    state = {"value": 0}
    await g.execute(state)

    assert state["value"] == 1
    assert "fail_path" not in state.get("__executed", [])
    assert "success_path" in state["__executed"]


@pytest.mark.asyncio
async def test_conditional_branch_false():
    """Edge with condition=False is skipped."""
    g = Graph(name="cond_false").add_nodes(
        Node(name="start", func=lambda s: s.update({"flag": False}) or "ok"),
        Node(name="success_path", func=_async_add),
        Node(name="fail_path", func=_async_add),
    ).add_edges(
        Edge("start", "success_path", condition=lambda s: s.get("flag") is True),
        Edge("start", "fail_path", condition=lambda s: s.get("flag") is not True),
    )

    state = {"value": 0}
    await g.execute(state)

    assert state["value"] == 1
    assert "success_path" not in state.get("__executed", [])
    assert "fail_path" in state["__executed"]


# ---------------------------------------------------------------------------
# Retry loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_loop_success_on_second_attempt():
    """Node with retry_count retries on failure and eventually succeeds."""
    call_count = 0

    async def _flaky(state):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError(f"flaky error {call_count}")
        return "success"

    g = Graph(name="retry").add_nodes(
        Node(name="flaky", func=_flaky, retry_count=3),
    )

    state = {}
    await g.execute(state)

    assert call_count == 3
    assert state["flaky"] == "success"
    assert state["__failed"] == []


@pytest.mark.asyncio
async def test_retry_loop_exhausted():
    """Node that keeps failing beyond retry_count ends up in __failed."""
    call_count = 0

    async def _always_fail(state):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("always fail")

    g = Graph(name="retry_fail").add_nodes(
        Node(name="bad", func=_always_fail, retry_count=2),
        Node(name="after", func=_async_add),
    ).add_edges(
        Edge("bad", "after"),
    )

    state = {"value": 0}
    await g.execute(state)

    assert call_count == 3  # initial + 2 retries
    assert "bad" in state["__failed"]
    assert "after" not in state.get("__executed", [])


# ---------------------------------------------------------------------------
# Subgraph nesting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subgraph_nesting():
    """A Node containing a subgraph executes the subgraph and merges state."""
    inner = Graph(name="inner").add_nodes(
        Node(name="x", func=_async_add),
        Node(name="y", func=_async_add),
    ).add_edges(
        Edge("x", "y"),
    )

    outer = Graph(name="outer").add_nodes(
        Node(name="pre", func=_async_add),
        Node(name="sub", subgraph=inner),
        Node(name="post", func=_async_add),
    ).add_edges(
        Edge("pre", "sub"),
        Edge("sub", "post"),
    )

    state = {"value": 0}
    await outer.execute(state)

    assert state["value"] == 4
    assert set(state["__executed"]) == {"pre", "sub", "post"}


@pytest.mark.asyncio
async def test_subgraph_parallel_with_outer():
    """Subgraph node runs in parallel with other independent outer nodes."""
    inner = Graph(name="inner").add_nodes(
        Node(name="i1", func=lambda s: s.update({"inner_val": 10}) or 10),
    )

    outer = Graph(name="outer").add_nodes(
        Node(name="a", func=lambda s: s.update({"outer_val": 20}) or 20),
        Node(name="b", subgraph=inner),
    )

    state = {}
    await outer.execute(state)

    assert state.get("inner_val") == 10
    assert state.get("outer_val") == 20
    assert set(state["__executed"]) == {"a", "b"}


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_node_timeout():
    """Node with timeout raises if func exceeds timeout."""
    async def _slow(state):
        await asyncio.sleep(10)
        return "done"

    g = Graph(name="timeout").add_nodes(
        Node(name="slow", func=_slow, timeout=0.05),
    )

    state = {}
    await g.execute(state)

    assert "slow" in state["__failed"]


# ---------------------------------------------------------------------------
# Visualizer
# ---------------------------------------------------------------------------

def test_generate_mermaid():
    g = Graph(name="demo").add_nodes(
        Node(name="start", func=lambda s: s),
        Node(name="end", func=lambda s: s, retry_count=2, timeout=5.0),
    ).add_edges(
        Edge("start", "end", condition=lambda s: s.get("ok")),
    )

    mermaid = generate_mermaid(g)

    assert "flowchart" in mermaid
    assert "start" in mermaid
    assert "end" in mermaid
    assert "retry:2" in mermaid
    assert "timeout:5" in mermaid
    assert "demo" in mermaid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
