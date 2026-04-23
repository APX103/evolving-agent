"""A2A protocol basic tests."""
import pytest
from agent.a2a.models import AgentCard, AgentSkill, Task, Message, TextPart, TaskState
from agent.a2a.discovery import AgentDiscovery


class TestA2AModels:
    def test_agent_card_creation(self):
        card = AgentCard(
            name="test-agent",
            description="A test agent",
            url="http://localhost:8000",
            skills=[AgentSkill(id="echo", name="Echo", description="Echo back")],
        )
        assert card.name == "test-agent"
        assert len(card.skills) == 1

    def test_task_state_transitions(self):
        task = Task(id="t1")
        assert task.state == TaskState.SUBMITTED
        task.state = TaskState.COMPLETED
        assert task.state == TaskState.COMPLETED

    def test_message_serialization(self):
        msg = Message(role="user", parts=[TextPart(text="hello")])
        d = msg.model_dump()
        assert d["role"] == "user"
        assert d["parts"][0]["type"] == "text"


class TestAgentDiscovery:
    def test_cache_and_ttl(self):
        from agent.a2a.discovery import AgentDiscovery, _CacheEntry
        discovery = AgentDiscovery()
        card = AgentCard(name="cached", description="x", url="http://x")
        discovery._cache["http://x"] = _CacheEntry(card, 9999999999.0)
        import asyncio
        result = asyncio.run(discovery.discover("http://x"))
        assert result.name == "cached"
