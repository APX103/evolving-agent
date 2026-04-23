"""Workflow graph engine tests."""
import pytest
import asyncio
from agent.workflow.graph import Graph, Node, Edge
from agent.workflow.visualizer import generate_mermaid


class TestGraphBuilder:
    def test_add_node_and_edge(self):
        g = Graph("test")
        n1 = Node("a", func=lambda s: s)
        n2 = Node("b", func=lambda s: s)
        g.add_node(n1).add_edge(Edge("a", "b"))
        g.add_node(n2)
        assert "a" in g.nodes
        assert "b" in g.nodes
        assert len(g.edges) == 1

    def test_mermaid_output(self):
        g = Graph("test")
        g.add_node(Node("start", func=lambda s: s))
        g.add_node(Node("end", func=lambda s: s))
        g.add_edge(Edge("start", "end"))
        mermaid = generate_mermaid(g)
        assert "flowchart TD" in mermaid
        assert "start" in mermaid
        assert "end" in mermaid


class TestGraphExecution:
    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        g = Graph("seq")
        state = {"value": 0}

        async def inc(s):
            s["value"] += 1

        g.add_node(Node("a", func=inc))
        g.add_node(Node("b", func=inc))
        g.add_edge(Edge("a", "b"))

        await g.execute(state)
        assert state["value"] == 2

    @pytest.mark.asyncio
    async def test_conditional_branch(self):
        g = Graph("cond")
        state = {"path": ""}

        async def step_a(s):
            s["path"] += "A"

        async def step_b(s):
            s["path"] += "B"

        async def step_c(s):
            s["path"] += "C"

        g.add_node(Node("a", func=step_a))
        g.add_node(Node("b", func=step_b))
        g.add_node(Node("c", func=step_c))
        g.add_edge(Edge("a", "b", condition=lambda s: True))
        g.add_edge(Edge("a", "c", condition=lambda s: False))

        await g.execute(state)
        assert state["path"] == "AB"

    @pytest.mark.asyncio
    async def test_retry_loop(self):
        g = Graph("retry")
        state = {"attempts": 0}

        async def fail_once(s):
            s["attempts"] += 1
            if s["attempts"] < 2:
                raise RuntimeError("fail")

        g.add_node(Node("a", func=fail_once, retry_count=2))
        await g.execute(state)
        assert state["attempts"] == 2

    @pytest.mark.asyncio
    async def test_subgraph_nesting(self):
        inner = Graph("inner")
        state = {"count": 0}

        async def inc(s):
            s["count"] += 1

        inner.add_node(Node("x", func=inc))
        inner.add_node(Node("y", func=inc))
        inner.add_edge(Edge("x", "y"))

        outer = Graph("outer")
        outer.add_node(Node("sub", subgraph=inner))
        await outer.execute(state)
        assert state["count"] == 2
